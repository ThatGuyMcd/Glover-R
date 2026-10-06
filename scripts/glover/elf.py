"""ELF32 big-endian writer and independent structural/payload validator.

The output preserves the original mapped bytes. Its candidate symbol extents
are experimental metadata, not a completed matching decompilation.
"""
from __future__ import annotations
import hashlib
import struct
from typing import Any

class ElfError(ValueError):
    pass


def aligned(value: int, alignment: int = 16) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def make_analysis_elf(rom: bytes, profile: dict[str, Any], functions: list[dict[str, Any]], *, verified_aliases: list[dict] | None = None) -> bytes:
    sections = profile["sections"]
    start, end = sections[0]["start"], sections[-1]["end"]
    delta = profile["load_vram"] - profile["load_rom_offset"]
    if start < 0x100 or end > len(rom):
        raise ElfError("Invalid mapped ROM range.")
    for left, right in zip(sections, sections[1:]):
        if left["end"] != right["start"]:
            raise ElfError("Initial mapped sections must be contiguous.")
    if end + delta != profile["bss_start"]:
        raise ElfError("Mapped data must end at the verified bootstrap BSS start.")
    names = [s["name"] for s in sections] + [".bss", ".symtab", ".strtab", ".shstrtab"]
    if len(names) != len(set(names)):
        raise ElfError("Duplicate ELF section names.")
    indexes = {name: i+1 for i, name in enumerate(names)}
    shstrings = bytearray(b"\0")
    shname = {}
    for name in names:
        shname[name] = len(shstrings)
        shstrings.extend(name.encode("ascii") + b"\0")
    strings = bytearray(b"\0")
    def add_name(name: str) -> int:
        if not name or not all(c.isalnum() or c in "_.$" for c in name) or not name.isascii():
            raise ElfError(f"Invalid symbol name: {name!r}")
        offset = len(strings)
        strings.extend(name.encode("ascii") + b"\0")
        return offset
    symbol_bytes = bytearray(bytes(16))
    for section in sections + [{"name": ".bss", "start": profile["bss_start"]-delta}]:
        # STB_LOCAL | STT_SECTION.
        symbol_bytes.extend(struct.pack(">IIIBBH", 0, section["start"]+delta, 0, 3, 0, indexes[section["name"]]))
    first_global = len(symbol_bytes) // 16
    # Default analysis remains strict. Native preparation can additionally
    # supply a ROM-verified ignored-SDK alias group; arbitrary duplicates fail.
    from .sdk_aliases import validate_elf_aliases, SdkAliasError
    try:
        validate_elf_aliases(functions, rom, profile, verified_aliases)
    except SdkAliasError as error:
        raise ElfError(str(error)) from error
    for f in functions:
        section = next((s for s in sections if s["name"] == f["section"] and s["kind"] == "code"), None)
        if section is None or f["size"] <= 0 or f["vram"] % 4 or f["size"] % 4:
            raise ElfError(f"Invalid function candidate {f['name']}.")
        if not section["start"]+delta <= f["vram"] < f["vram"]+f["size"] <= section["end"]+delta:
            raise ElfError(f"Function candidate outside its section: {f['name']}.")
        symbol_bytes.extend(struct.pack(">IIIBBH", add_name(f["name"]), f["vram"], f["size"], 0x12, 0, indexes[f["section"]]))
    for name, value in (("__glover_bss_start", profile["bss_start"]),
                        ("__glover_bss_end", profile["bss_end"]),
                        ("__glover_initial_stack", profile["initial_stack"])):
        symbol_bytes.extend(struct.pack(">IIIBBH", add_name(name), value, 0, 0x10, 0, 0xfff1))
    output = bytearray(end)
    output[start:end] = rom[start:end]
    section_headers = [(0,)*10]
    for s in sections:
        flags = 6 if s["kind"] == "code" else 3 if s["kind"] == "data" else 2
        section_headers.append((shname[s["name"]], 1, flags, s["start"]+delta, s["start"], s["end"]-s["start"], 0, 0, 16, 0))
    section_headers.append((shname[".bss"], 8, 3, profile["bss_start"], end,
                            profile["bss_end"]-profile["bss_start"], 0, 0, 16, 0))
    def append(blob: bytes | bytearray, alignment: int) -> int:
        offset = aligned(len(output), alignment)
        output.extend(bytes(offset-len(output)))
        output.extend(blob)
        return offset
    symoff = append(symbol_bytes, 4)
    stroff = append(strings, 1)
    shstroff = append(shstrings, 1)
    section_headers.extend([
        (shname[".symtab"], 2, 0, 0, symoff, len(symbol_bytes), indexes[".strtab"], first_global, 4, 16),
        (shname[".strtab"], 3, 0, 0, stroff, len(strings), 0, 0, 1, 0),
        (shname[".shstrtab"], 3, 0, 0, shstroff, len(shstrings), 0, 0, 1, 0),
    ])
    shoff = append(b"".join(struct.pack(">10I", *s) for s in section_headers), 4)
    ident = b"\x7fELF\x01\x02\x01" + bytes(9)
    output[:52] = ident + struct.pack(">HHIIIIIHHHHHH", 2, 8, 1, profile["load_vram"], 52, shoff,
                                      0x20001001, 52, 32, 1, 40, len(section_headers), indexes[".shstrtab"])
    output[52:84] = struct.pack(">8I", 1, start, start+delta, start,
                                 end-start, profile["bss_end"]-(start+delta), 7, 16)
    return bytes(output)


def inspect_elf(data: bytes) -> dict[str, Any]:
    if len(data) < 84 or data[:7] != b"\x7fELF\x01\x02\x01":
        raise ElfError("Expected a big-endian ELF32 file.")
    h = struct.unpack_from(">HHIIIIIHHHHHH", data, 16)
    e_type, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstrndx = h
    if (e_type, machine, version, ehsize, phsize, shsize) != (2, 8, 1, 52, 32, 40):
        raise ElfError("Unexpected ELF machine, type, version or table sizes.")
    if phoff+phsize*phnum > len(data) or shoff+shsize*shnum > len(data) or not 0 < shstrndx < shnum:
        raise ElfError("ELF tables are out of bounds.")
    raw = [struct.unpack_from(">10I", data, shoff+i*shsize) for i in range(shnum)]
    for s in raw:
        if s[1] != 8 and s[4]+s[5] > len(data):
            raise ElfError("ELF section payload is out of bounds.")
    name_section = raw[shstrndx]
    if name_section[1] != 3:
        raise ElfError("Bad section-name string table.")
    def string_at(section: tuple[int, ...], offset: int) -> str:
        if not 0 <= offset < section[5]:
            raise ElfError("String offset is out of bounds.")
        start = section[4] + offset
        stop = data.find(b"\0", start, section[4]+section[5])
        if stop < 0:
            raise ElfError("Unterminated ELF string.")
        return data[start:stop].decode("ascii")
    sections = [{"name": string_at(name_section, s[0]), "type": s[1], "flags": s[2],
                 "vram": s[3], "offset": s[4], "size": s[5], "index": i}
                for i, s in enumerate(raw)]
    symbols = []
    for s in raw:
        if s[1] != 2:
            continue
        if s[9] != 16 or s[5] % 16 or not 0 < s[6] < shnum or raw[s[6]][1] != 3:
            raise ElfError("Malformed symbol table.")
        for pos in range(s[4]+16, s[4]+s[5], 16):
            name, value, size, info, other, section_index = struct.unpack_from(">IIIBBH", data, pos)
            if info & 15 != 2:
                continue
            if not 0 < section_index < shnum or size == 0 or value % 4 or size % 4:
                raise ElfError("Malformed function symbol.")
            target = sections[section_index]
            if not target["flags"] & 4 or not target["vram"] <= value < value+size <= target["vram"]+target["size"]:
                raise ElfError("Function symbol lies outside executable section.")
            symbols.append({"name": string_at(raw[s[6]], name), "vram": value, "size": size,
                            "section": target["name"]})
    by_address = sorted(symbols, key=lambda f: f["vram"])
    for a, b in zip(by_address, by_address[1:]):
        if a["section"] == b["section"] and a["vram"]+a["size"] > b["vram"]:
            raise ElfError("Overlapping candidate function symbols.")
    programs = []
    for i in range(phnum):
        p = struct.unpack_from(">8I", data, phoff+i*phsize)
        if p[4] > p[5] or p[1]+p[4] > len(data):
            raise ElfError("Invalid ELF program header.")
        programs.append({"type": p[0], "offset": p[1], "vram": p[2], "rom_offset": p[3],
                         "file_size": p[4], "memory_size": p[5], "flags": p[6]})
    return {"entrypoint": entry, "flags": flags, "sections": sections, "functions": symbols,
            "programs": programs, "sha256": hashlib.sha256(data).hexdigest()}


def verify_against_rom(elf_data: bytes, rom: bytes, profile: dict[str, Any]) -> dict[str, Any]:
    parsed = inspect_elf(elf_data)
    if parsed["entrypoint"] != profile["load_vram"]:
        raise ElfError("ELF retail entrypoint differs from the profile.")
    delta = profile["load_vram"] - profile["load_rom_offset"]
    for expected in profile["sections"]:
        matches = [s for s in parsed["sections"] if s["name"] == expected["name"]]
        if len(matches) != 1:
            raise ElfError("Mapped ELF section is absent or duplicated.")
        actual = matches[0]
        flags = 6 if expected["kind"] == "code" else 3 if expected["kind"] == "data" else 2
        if (actual["type"] != 1 or actual["flags"] != flags or
                actual["offset"] != expected["start"] or actual["vram"] != expected["start"]+delta or
                actual["size"] != expected["end"]-expected["start"]):
            raise ElfError(f"Mapped ELF section layout differs: {expected['name']}.")
    loads = [p for p in parsed["programs"] if p["type"] == 1]
    if len(loads) != 1:
        raise ElfError("This initial map expects exactly one load segment.")
    segment = loads[0]
    expected_size = profile["sections"][-1]["end"]-profile["load_rom_offset"]
    if (segment["vram"] != profile["load_vram"] or segment["rom_offset"] != profile["load_rom_offset"]
            or segment["file_size"] != expected_size
            or segment["vram"]+segment["memory_size"] != profile["bss_end"]):
        raise ElfError("Load layout differs from the game profile.")
    a, b, size = segment["offset"], segment["rom_offset"], segment["file_size"]
    if elf_data[a:a+size] != rom[b:b+size]:
        raise ElfError("ELF load payload does not exactly match the supplied ROM.")
    bss = [s for s in parsed["sections"] if s["name"] == ".bss"]
    if (len(bss) != 1 or bss[0]["type"] != 8 or bss[0]["vram"] != profile["bss_start"] or
            bss[0]["size"] != profile["bss_end"]-profile["bss_start"] or bss[0]["flags"] != 3):
        raise ElfError("Invalid BSS section.")
    return {"structural_validation": "PASS", "mapped_rom_bytes": "IDENTICAL", "mapped_bytes": size,
            "function_count": len(parsed["functions"]), "elf_sha256": parsed["sha256"],
            "function_semantics_verified": False, "native_runtime_ready": False}
