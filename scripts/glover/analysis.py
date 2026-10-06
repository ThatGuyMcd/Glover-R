"""Conservative CPU inventory. Candidates are NOT a verified function map.

This reports evidence and hazards rather than silently stubbing instructions or
promoting data pointers to trusted runtime hooks. The native-input builder combines this inventory with verified SDK evidence
and ROM-checked policy before generating the native ELF.
"""
from __future__ import annotations
from collections import defaultdict
import struct
from typing import Any


def signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def control_flow(word: int, pc: int) -> tuple[str, int | None] | None:
    op = word >> 26
    if op in (2, 3):
        return ("call" if op == 3 else "jump",
                ((pc + 4) & 0xf0000000) | ((word & 0x03ffffff) << 2))
    if op in (4, 5, 6, 7, 20, 21, 22, 23):
        return "branch", (pc + 4 + signed16(word & 0xffff) * 4) & 0xffffffff
    if op == 1 and ((word >> 16) & 31) in (0, 1, 2, 3, 16, 17, 18, 19):
        rt = (word >> 16) & 31
        return ("branch-call" if rt >= 16 else "branch",
                (pc + 4 + signed16(word & 0xffff) * 4) & 0xffffffff)
    if op == 0 and word & 63 in (8, 9):
        rs = (word >> 21) & 31
        return ("return" if word & 63 == 8 and rs == 31 else
                "indirect-call" if word & 63 == 9 else "indirect-jump"), None
    if op == 17 and (word >> 21) & 31 == 8:
        return "fp-branch", (pc + 4 + signed16(word & 0xffff) * 4) & 0xffffffff
    return None


def inventory(rom: bytes, profile: dict[str, Any]) -> dict[str, Any]:
    delta = profile["load_vram"] - profile["load_rom_offset"]
    code = [s for s in profile["sections"] if s["kind"] == "code"]
    data = [s for s in profile["sections"] if s["kind"] in ("data", "rodata")]
    def section_at(vram: int) -> dict[str, Any] | None:
        offset = vram - delta
        return next((s for s in code if s["start"] <= offset < s["end"] and not offset % 4), None)
    def is_prologue(vram: int) -> bool:
        if section_at(vram) is None:
            return False
        word = struct.unpack_from(">I", rom, vram-delta)[0]
        # Strong but not conclusive GCC/IDO stack-frame signature.
        return word & 0xffff0000 == 0x27bd0000 and signed16(word & 0xffff) < 0 and word % 8 == 0
    roots: dict[int, set[str]] = defaultdict(set)
    roots[profile["load_vram"]].add("mapped-entry-section")
    roots[profile["callable_entrypoint"]].add("verified-bootstrap-call")
    for section in code:
        roots[section["start"] + delta].add("mapped-code-section-start")
    calls, transfers, cop0, indirect, breakpoints = [], [], [], [], []
    branch_targets: set[int] = set()
    for section in code:
        for offset in range(section["start"], section["end"], 4):
            word = struct.unpack_from(">I", rom, offset)[0]
            pc = offset + delta
            flow = control_flow(word, pc)
            if flow:
                kind, target = flow
                entry = {"pc": pc, "rom_offset": offset, "kind": kind, "target": target}
                if kind in ("call", "branch-call"):
                    calls.append(entry)
                    if target is not None and section_at(target):
                        roots[target].add("direct-call-target")
                elif kind.startswith("indirect"):
                    indirect.append(entry)
                if target is not None:
                    transfers.append(entry)
                    if "branch" in kind and kind != "branch-call":
                        branch_targets.add(target)
            if word >> 26 == 16:
                cop0.append({"pc": pc, "rom_offset": offset, "reason": "COP0 requires runtime analysis"})
            if word >> 26 == 0 and word & 63 in (12, 13):
                breakpoints.append({"pc": pc, "rom_offset": offset,
                                    "kind": "break" if word & 63 == 13 else "syscall"})
    pointer_candidates: dict[int, set[str]] = defaultdict(set)
    for section in data:
        for offset in range(section["start"], section["end"], 4):
            target = struct.unpack_from(">I", rom, offset)[0]
            if section_at(target):
                pointer_candidates[target].add(f"data-pointer:{section['name']}")
    # Local register-constant analysis finds callback/address constructions. It
    # deliberately drops state at transfers, and is only evidence, not proof.
    for section in code:
        regs: dict[int, int] = {}
        for offset in range(section["start"], section["end"], 4):
            word = struct.unpack_from(">I", rom, offset)[0]
            op, rs, rt, rd = word >> 26, (word >> 21) & 31, (word >> 16) & 31, (word >> 11) & 31
            if op == 15:
                regs[rt] = (word & 0xffff) << 16
            elif op in (9, 13) and rs in regs:
                value = ((regs[rs] + signed16(word & 0xffff)) if op == 9 else
                         (regs[rs] | (word & 0xffff))) & 0xffffffff
                regs[rt] = value
                if section_at(value):
                    pointer_candidates[value].add("constructed-code-address")
            else:
                if op == 0:
                    regs.pop(rd, None)
                elif op not in (2, 3, 4, 5, 6, 7, 40, 41, 42, 43, 46, 57, 61):
                    regs.pop(rt, None)
            if control_flow(word, offset + delta):
                regs.clear()
            regs.pop(0, None)
    for target, evidence in pointer_candidates.items():
        if is_prologue(target):
            roots[target].update(evidence)
            roots[target].add("stack-prologue-candidate")
    function_rows = []
    for section in code:
        starts = sorted(a for a in roots if section_at(a) is section)
        for index, address in enumerate(starts):
            end = starts[index+1] if index+1 < len(starts) else section["end"] + delta
            name = ("glover_bootstrap" if address == profile["load_vram"] else
                    "glover_game_init" if address == profile["callable_entrypoint"] else f"func_{address:08X}")
            function_rows.append({"name": name, "vram": address, "rom_offset": address-delta,
                                  "size": end-address, "section": section["name"],
                                  "evidence": sorted(roots[address]),
                                  "extent_status": "candidate-next-entry-boundary"})
    function_rows.sort(key=lambda e: e["vram"])
    # A binary-search owner lookup avoids an O(functions * instructions) pass.
    from bisect import bisect_right
    starts = [f["vram"] for f in function_rows]
    def owner(pc: int) -> dict[str, Any] | None:
        pos = bisect_right(starts, pc)-1
        if pos < 0:
            return None
        f = function_rows[pos]
        return f if f["vram"] <= pc < f["vram"]+f["size"] else None
    cross, unmapped = [], []
    for transfer in transfers:
        target = transfer["target"]
        target_owner, source_owner = owner(target), owner(transfer["pc"])
        if target_owner is None:
            unmapped.append(transfer)
        elif (transfer["kind"] not in ("call", "branch-call") and source_owner is not target_owner
              and target != target_owner["vram"]):
            cross.append({**transfer, "source_function": source_owner["name"] if source_owner else None,
                          "target_function": target_owner["name"]})
    pointer_rows = [{"vram": target, "evidence": sorted(evidence),
                     "included_in_candidate_elf": target in roots}
                    for target, evidence in sorted(pointer_candidates.items())]
    return {
        "schema_version": 1,
        "status": "analysis-only; function extents and runtime hooks remain unverified",
        "native_runtime_ready": False,
        "function_candidates": function_rows,
        "direct_calls": calls,
        "unmapped_direct_transfers": unmapped,
        "cross_candidate_interior_transfers": cross,
        "indirect_transfers": indirect,
        "cop0_sites": cop0,
        "break_and_syscall_sites": breakpoints,
        "code_pointer_candidates": pointer_rows,
        "summary": {"function_candidates": len(function_rows), "direct_calls": len(calls),
                    "unmapped_direct_transfers": len(unmapped),
                    "cross_candidate_interior_transfers": len(cross),
                    "indirect_transfers": len(indirect), "cop0_sites": len(cop0),
                    "break_and_syscall_sites": len(breakpoints),
                    "code_pointer_candidates": len(pointer_rows)},
        "limitations": [
            "A direct call proves an entry target, not the complete extent of that function.",
            "Pointer/prologue recognition is heuristic; no inferred name is used as a host service replacement.",
            "Indirect jump tables, callbacks, shared epilogues and possible overlays need review.",
            "COP0 and cartridge I/O are inventoried, not stubbed or silently bypassed.",
            "The region beyond the upstream .rodata end has not been declared data-only."
        ]
    }


