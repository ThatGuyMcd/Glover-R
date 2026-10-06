"""ROM-checked inputs for the first native Glover build.

This never edits N64Recomp output. SDK names come from the pinned n64sym
signature/relocation scan, with conflicts retained and startup anchors checked.
Game-function extents remain experimental until N64Recomp and gameplay testing.
"""
from __future__ import annotations
from bisect import bisect_right
from collections import defaultdict, deque
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any
from .analysis import inventory, control_flow, signed16
from .bootstrap import decode_bootstrap
from .rom import atomic_bytes, atomic_json, inspect_file, load_profile
from .sdk_aliases import checked_alias_group, alias_groups_from_symbols, SdkAliasError
from .native_elf import make_native_elf, verify_native_elf
from .policy_bindings import validate_policy_bindings
from .runtime_functions import classify_functions, RuntimeFunctionError

class NativeInputError(ValueError):
    pass

# These anchors are independently inspected startup calls. Signature results
# must agree; a guessed or shifted symbol file must never silently pass.
ANCHORS = {
    'osCreateMesgQueue': 0x801C6520,
    'osCreateThread': 0x801C6550,
    'osInitialize': 0x801C7110,
}
AUDIO_START = 0xBF9E0
AUDIO_SIZE = 0xE20
AUDIO_DATA = 0xF4E00
AUDIO_TABLE = (0x1118, 0x1470, 0x11DC, 0x1B38, 0x1214, 0x187C,
               0x1254, 0x12D0, 0x12EC, 0x1328, 0x140C, 0x1294,
               0x1E24, 0x138C, 0x170C, 0x144C)


def parse_symbols(text: str) -> list[dict[str, Any]]:
    """Read the patched scanner's address/name/size records, without guessing."""
    result = []
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'(?:0x)?([0-9A-Fa-f]{8})\s+([A-Za-z_][A-Za-z_0-9.$]*)\s+(?:0x)?([0-9A-Fa-f]{8})', line)
        if not match:
            raise NativeInputError(f'Malformed symbol record on line {number}; the checked n64sym patch is required.')
        address, name, size = int(match[1], 16), match[2], int(match[3], 16)
        if address % 4 or size % 4:
            # Data objects and strings are not CPU function entries.
            continue
        result.append({'vram': address, 'name': name, 'size': size,
                       'evidence': 'signature' if size else 'signature-relocation'})
    if not result:
        raise NativeInputError('The symbol scanner produced no usable records.')
    return result


def runtime_symbol_sets(source: str) -> tuple[set[str], set[str]]:
    groups = []
    for tag in ('reimplemented_funcs', 'ignored_funcs'):
        m = re.search(r'\b' + tag + r'\s*\{(.*?)\};', source, re.S)
        if not m:
            raise NativeInputError('Pinned N64Recomp symbol-list format changed: ' + tag)
        groups.append(set(re.findall(r'"([A-Za-z_][A-Za-z_0-9]*)"', m[1])))
    if not set(ANCHORS) <= groups[0]:
        raise NativeInputError('Recompiler does not supply the required startup services.')
    return groups[0], groups[1]


def select_symbols(records: list[dict[str, Any]], profile: dict[str, Any],
                   allowed: set[str], check_anchors: bool = True, *,
                   rom: bytes | None = None, alias_policy: dict | None = None,
                   ignored_only: set[str] | None = None) -> tuple[dict[int, dict], list[dict]]:
    delta = profile['load_vram'] - profile['load_rom_offset']
    def is_code(a):
        return any(s['kind'] == 'code' and s['start'] + delta <= a < s['end'] + delta
                   for s in profile['sections'])
    candidates: dict[int, dict[str, dict]] = defaultdict(dict)
    rejected = []
    for r in records:
        if r['name'] not in allowed or not is_code(r['vram']):
            continue
        prior = candidates[r['vram']].get(r['name'])
        if prior is None or (not prior['size'] and r['size']):
            candidates[r['vram']][r['name']] = r
        elif prior['size'] and r['size'] and prior['size'] != r['size']:
            raise NativeInputError('Conflicting matched sizes for '+r['name'])
    chosen = {}
    for address, names in candidates.items():
        full = [r for r in names.values() if r['size']]
        if len(full) == 1:
            chosen[address] = full[0]
            for other in names.values():
                if other['name'] != full[0]['name']:
                    rejected.append({**other, 'reason': 'relocation alias conflicts with a full signature'})
        elif len(names) == 1:
            chosen[address] = next(iter(names.values()))
        else:
            # Do not choose whichever SDK revision the scanner found first.
            raise NativeInputError(f'Ambiguous SDK symbols at 0x{address:08X}: '+', '.join(sorted(names)))
    name_addresses: dict[str, list[int]] = defaultdict(list)
    for address, r in chosen.items(): name_addresses[r['name']].append(address)
    for name, addresses in name_addresses.items():
        if len(addresses) != 1:
            if rom is None or alias_policy is None or ignored_only is None:
                raise NativeInputError(f'Multiple executable copies of {name}; an explicit alias policy is needed: '+
                                       ', '.join(f'0x{a:08X}' for a in addresses))
            try:
                group = checked_alias_group(name, [chosen[a] for a in addresses],
                    profile, rom, alias_policy, ignored_only)
            except SdkAliasError as error:
                raise NativeInputError(str(error)) from error
            for address in addresses:
                # Preserve BOTH guest addresses and the original SDK name.
                # The checked body size also resolves the size-zero relocation.
                chosen[address] = {**chosen[address], 'size': group['size'],
                                   'verified_sdk_alias': group}
    if check_anchors:
        for name, expected in ANCHORS.items():
            if name_addresses.get(name) != [expected]:
                raise NativeInputError(f'Startup symbol check failed: {name} must identify 0x{expected:08X}. '
                                       'The raw scanner report is retained for investigation.')
    return chosen, rejected


def reachable_extent(rom: bytes, start: int, limit: int, delta: int,
                     pointer_targets: set[int]) -> tuple[int, dict[str, Any]]:
    """Trim unreachable padding/data, retaining indirect-target candidates.

    This is a control-flow inventory, not a claim that all indirect edges have
    been proven. Unknown indirect jumps preserve their candidate interval.
    """
    todo = deque([start]); visited: set[int] = set(); unknown = False
    invalid_edges = []; table_seeds = False
    lexical_seeds = 0
    boundary_fallthrough = set()
    while True:
        while todo:
            pc = todo.popleft()
            if pc >= limit:
                boundary_fallthrough.add(pc)
                continue
            if pc in visited or pc < start: continue
            visited.add(pc)
            word = struct.unpack_from('>I', rom, pc-delta)[0]
            flow = control_flow(word, pc)
            if flow is None:
                # BREAK/SYSCALL is a trap; code following a conditional divide check
                # can still be reached through its separate branch successor.
                if word >> 26 == 0 and word & 63 in (12, 13): continue
                todo.append(pc+4); continue
            kind, target = flow
            if pc+4 < limit: visited.add(pc+4)  # branch delay slot
            else: boundary_fallthrough.add(pc+4)
            if kind in ('call', 'branch-call', 'indirect-call'):
                todo.append(pc+8)
            elif kind == 'return':
                pass
            elif kind == 'indirect-jump':
                seeds = sorted(t for t in pointer_targets if start <= t < limit)
                if seeds:
                    todo.extend(seeds); table_seeds = True
                else:
                    unknown = True
            elif kind == 'jump':
                if target is not None and start <= target < limit: todo.append(target)
                elif target is not None: invalid_edges.append({'pc': pc, 'target': target, 'kind': kind})
            else:
                if target is not None and start <= target < limit: todo.append(target)
                elif target is not None: invalid_edges.append({'pc': pc, 'target': target, 'kind': kind})
                # BEQ zero,zero / BGEZ zero are unconditional pseudo-branches.
                unconditional = ((word >> 26 == 4 and (word >> 21) & 31 == (word >> 16) & 31) or
                                 (word >> 26 == 1 and (word >> 21) & 31 == 0 and (word >> 16) & 31 == 1))
                if not unconditional: todo.append(pc+8)
        # N64Recomp emits ALL words inside a function, including dead branches
        # before an infinite loop. Their epilogue labels must remain in range.
        # Reachability-only trimming left six original epilogues out in Boot.5.
        lexical_end = limit if unknown else max(visited, default=start) + 4
        targets = set()
        for pc in range(start, lexical_end, 4):
            flow = control_flow(struct.unpack_from('>I', rom, pc-delta)[0], pc)
            if flow and flow[0] in ('branch', 'fp-branch', 'jump'):
                target = flow[1]
                if target is not None and start <= target < limit and target not in visited:
                    targets.add(target)
        if not targets:
            break
        lexical_seeds += len(targets)
        todo.extend(sorted(targets))
    end = limit if unknown else max(visited, default=start) + 4
    return end, {'reachable_words': len(visited), 'unresolved_indirect': unknown,
                 'pointer_table_seeds_used': table_seeds, 'external_edges': invalid_edges,
                 'lexical_branch_targets_added': lexical_seeds,
                 'boundary_fallthrough': sorted(boundary_fallthrough)}


def compile_metadata(rom: bytes, profile: dict[str, Any], sdk: dict[int, dict], *,
                     additional_entries: list[dict] | None = None) -> tuple[list[dict], dict]:
    analysis = inventory(rom, profile)
    delta = profile['load_vram'] - profile['load_rom_offset']
    candidates = {r['vram']: dict(r) for r in analysis['function_candidates']}
    # A verified callable entry and every SDK entry take precedence over
    # heuristic next-call boundaries; SDK private routines can be leaf functions.
    for address, r in sdk.items():
        section = next(s for s in profile['sections'] if s['kind'] == 'code' and
                       s['start'] + delta <= address < s['end'] + delta)
        candidates[address] = {'name': r['name'], 'vram': address, 'rom_offset': address-delta,
                               'section': section['name'], 'evidence': [r['evidence']]}
    # Reviewed callback entries are installed before interval/CFG discovery. They
    # keep following callbacks and inline data out of a prior jump-table owner.
    from .runtime_functions import checked_additional_entries
    for entry in checked_additional_entries(rom, profile, additional_entries or []):
        address = entry['vram']
        if address in sdk or (address in candidates and candidates[address]['name'] != entry['name']):
            raise NativeInputError('Reviewed callback entry collides with another function.')
        candidates[address] = entry
    # Capture address-taken leaf callbacks only when an actual return precedes
    # the entry, not every data word which happens to resemble a code address.
    for r in analysis['code_pointer_candidates']:
        a = r['vram']; off = a-delta
        if a not in candidates and off >= 8 and struct.unpack_from('>I', rom, off-8)[0] == 0x03E00008:
            section = next(s for s in profile['sections'] if s['kind'] == 'code' and s['start'] <= off < s['end'])
            candidates[a] = {'name': f'func_{a:08X}', 'vram': a, 'rom_offset': off,
                             'section': section['name'], 'evidence': ['address-taken-leaf-after-return']}
    pointers = {r['vram'] for r in analysis['code_pointer_candidates']}
    functions = []; details = []; trimmed = 0
    for s in profile['sections']:
        if s['kind'] != 'code': continue
        starts = sorted(a for a,r in candidates.items() if r['section'] == s['name'])
        for n, a in enumerate(starts):
            limit = starts[n+1] if n+1 < len(starts) else s['end']+delta
            end, audit = reachable_extent(rom, a, limit, delta, pointers)
            # Whole-signature lengths are stronger evidence than local CFG
            # trimming. Refuse overlap rather than truncating matched bytes.
            match_size = sdk.get(a, {}).get('size', 0)
            if match_size:
                if a+match_size > limit:
                    raise NativeInputError(f'Matched SDK function {sdk[a]["name"]} overlaps another entry. '
                                           'Review the recorded symbol aliases before generating code.')
                end = a+match_size
            row = dict(candidates[a]); row['size'] = end-a
            row['boundary_fallthrough'] = audit['boundary_fallthrough']
            row['extent_status'] = 'signature-size' if match_size else 'cfg-reviewed-candidate'
            if row['size'] <= 0: raise NativeInputError('Empty function extent.')
            functions.append(row)
            trimmed += limit-end
            details.append({'name': row['name'], 'vram': a, 'size': row['size'], **audit})
    starts = {f['vram'] for f in functions}
    invalid = []
    for r in details:
        for e in r['external_edges']:
            if e['target'] not in starts:
                invalid.append({'function':r['name'], **e})
    return functions, {'status': 'experimental-native-inputs', 'functions': len(functions),
                       'sdk_named_functions': len(sdk), 'trimmed_padding_bytes': trimmed,
                       'unresolved_external_edges': invalid,
                       'unresolved_indirect_functions': [r['name'] for r in details if r['unresolved_indirect']],
                       'function_audit': details, 'gameplay_verified': False}


def audio_config(rom: bytes, rom_path: Path, output_path: Path) -> tuple[str, dict]:
    table = struct.unpack_from('>16H', rom, AUDIO_DATA+0x10)
    if table != AUDIO_TABLE:
        raise NativeInputError('Glover audio dispatch table does not match the checked USA table.')
    expected = {0x10EC:0x001A0DC2, 0x10F0:0x302100FE, 0x1108:0x84420010, 0x110C:0x00400008}
    for pc,w in expected.items():
        actual = struct.unpack_from('>I', rom, AUDIO_START+pc-0x1080)[0]
        if actual != w: raise NativeInputError(f'Audio dispatcher instruction mismatch at IMEM 0x{pc:04X}.')
    if any(not 0x1080 <= x < 0x1080+AUDIO_SIZE or x%4 for x in table):
        raise NativeInputError('Audio dispatch target falls outside the code image.')
    text = ('# Generated from ROM-checked Glover USA audio evidence.\n'
            f'text_offset = 0x{AUDIO_START:X}\ntext_size = 0x{AUDIO_SIZE:X}\ntext_address = 0x04001080\n'
            f'rom_file_path = {json.dumps(rom_path.resolve().as_posix())}\n'
            f'output_file_path = {json.dumps(output_path.resolve().as_posix())}\n'
            'output_function_name = "rocketAspMain"\n'  # retained internal host ABI, not Rocket microcode
            'extra_indirect_branch_targets = ['+', '.join(f'0x{x:04X}' for x in table)+']\n')
    return text, {'code_rom_offset':AUDIO_START, 'code_size':AUDIO_SIZE, 'imem':0x04001080,
                  'guest_ucode_address':0x801BE9E0, 'guest_data_address':0x801F3E00,
                  'dispatch_targets':list(table), 'code_sha256':hashlib.sha256(rom[AUDIO_START:AUDIO_START+AUDIO_SIZE]).hexdigest(),
                  'table_sha256':hashlib.sha256(rom[AUDIO_DATA+16:AUDIO_DATA+48]).hexdigest(),
                  'dispatch_shape_verified':True, 'rsp_execution_verified':False}


def bootstrap_header(rom: bytes, profile: dict) -> str:
    b = decode_bootstrap(rom, profile)
    fields = {'kRetailLoadAddress':b['retail_load_vram'], 'kCallableEntrypoint':b['callable_entrypoint'],
              'kInitialStackPointer':b['initial_stack'], 'kBootstrapBssStart':b['bss_start'], 'kBootstrapBssEnd':b['bss_end']}
    return ('#pragma once\n#include <cstdint>\nnamespace rocket::generated {\n'+
            ''.join(f'inline constexpr std::uint32_t {k} = 0x{v:08X}U;\n' for k,v in fields.items())+
            'inline constexpr const char* kInternalName = '+json.dumps(rom[0x20:0x34].decode('ascii').rstrip(' \0'))+';\n}\n')


def recomp_config(rom: bytes, elf: Path, rom_path: Path, out: Path, profile: dict,
                  policy: dict | None = None) -> str:
    if policy is None:
        policy = json.loads((Path(__file__).resolve().parents[2]/
                             'runtime-recomp/glover.us.recomp-policy.json').read_text())
    if policy.get('schemaVersion') != 1:
        raise NativeInputError('Unsupported Glover recomp policy schema.')
    if 'sha1' in profile and policy.get('romSha1') != profile['sha1']:
        raise NativeInputError('Recomp policy targets a different ROM profile.')
    delta = profile['load_vram'] - profile['load_rom_offset']
    def number(value):
        if isinstance(value, bool) or not isinstance(value, (int,str)):
            raise NativeInputError('Invalid instruction/address in recomp policy.')
        n=int(value,0) if isinstance(value,str) else value
        if not 0 <= n <= 0xFFFFFFFF: raise NativeInputError('Policy integer is not 32-bit.')
        return n
    blocks=[]
    for collection,tag,address_name in (('instructionPatches','instruction','vram'),
                                       ('functionHooks','hook','beforeVram')):
        seen=set()
        for entry in policy.get(collection,[]):
            pc=number(entry[address_name]);off=number(entry['romOffset'])
            key=(entry['function'],pc)
            if key in seen or pc%4 or pc-delta!=off or off+4>len(rom):
                raise NativeInputError('Duplicate, unaligned or mismapped policy entry.')
            seen.add(key)
            if struct.unpack_from('>I',rom,off)[0]!=number(entry['expectedInstruction']):
                raise NativeInputError(f'Policy instruction differs at 0x{pc:08X}.')
            for guard in ('expectedDelaySlot', 'expectedFollowingInstruction'):
                if guard in entry:
                    if off+8>len(rom) or struct.unpack_from('>I',rom,off+4)[0]!=number(entry[guard]):
                        raise NativeInputError(f'Policy adjacent instruction changed at 0x{pc+4:08X}.')
            table = entry.get('expectedJumpTable')
            if table is not None:
                table_offset = number(table['romOffset'])
                values = table['entries']
                if not isinstance(values, list) or not values or table_offset % 4:
                    raise NativeInputError('Invalid checked jump-table evidence.')
                expected = struct.pack('>' + str(len(values)) + 'I', *(number(v) for v in values))
                if rom[table_offset:table_offset+len(expected)] != expected:
                    raise NativeInputError(f'Policy jump table changed at ROM 0x{table_offset:08X}.')
            block='[[patches.'+tag+']]\nfunc = '+json.dumps(entry['function'])+'\n'
            if tag=='instruction':
                block+=f'vram = 0x{pc:08X}\nvalue = 0x{number(entry["value"]):08X}\n'
            else:
                # A compound statement is legal immediately after a C17 label.
                block+=f'before_vram = 0x{pc:08X}\ntext = '+json.dumps('{ '+entry['text']+' }')+'\n'
            blocks.append(block)
    q=lambda path:json.dumps(path.resolve().as_posix())
    # Explicit lists only. The supplied policy has no empty-function stubs.
    lists=[]
    for key in ('stubs','ignored','renamed'):
        values=policy.get(key,[])
        if not isinstance(values,list) or any(not isinstance(x,str) for x in values):
            raise NativeInputError('Invalid policy function-name list: '+key)
        lists.append(key+' = ['+', '.join(json.dumps(x) for x in values)+']')
    return ('# Maintained Glover policy -> N64Recomp. Never patch generated C.\n'
            '[input]\n'+f'entrypoint = 0x{profile["callable_entrypoint"]:08X}\n'
            'use_mdebug = false\nelf_path = '+q(elf)+'\nrom_file_path = '+q(rom_path)+
            '\noutput_func_path = '+q(out)+'\nfunctions_per_output_file = 50\n\n'
            '[patches]\n'+'\n'.join(lists)+'\n\n'+'\n'.join(blocks))


def prepare(project: Path, runtime: Path, rom_path: Path, symbols_path: Path) -> dict:
    profile = load_profile(project/'config/glover.us.json')
    rom, _ = inspect_file(rom_path, profile)
    records = parse_symbols(symbols_path.read_text(encoding='utf-8-sig'))
    reimplemented, ignored = runtime_symbol_sets((runtime/'extern/n64-modern-runtime/N64Recomp/src/symbol_lists.cpp').read_text())
    alias_policy = json.loads((project/'config/sdk-aliases.json').read_text(encoding='utf-8'))
    sdk, rejected = select_symbols(records, profile, reimplemented | ignored,
        rom=rom, alias_policy=alias_policy, ignored_only=ignored - reimplemented)
    alias_groups = alias_groups_from_symbols(sdk)
    classification = json.loads((project/'runtime-recomp/glover.us.cpu-classification.json').read_text(encoding='utf-8'))
    functions, audit = compile_metadata(rom, profile, sdk, additional_entries=classification.get('additional_entries', []))
    policy = json.loads((project/'runtime-recomp/glover.us.recomp-policy.json').read_text(encoding='utf-8'))
    # SDK aliases have already been ROM-validated. Give the two status getters
    # distinct symbols so their original MFC0 Status bodies are emitted, rather
    # than relying on a non-existent __osGetSR_recomp host implementation.
    try:
        functions, boundary_audit = classify_functions(rom, profile, functions,
            classification, policy, reimplemented, ignored)
    except RuntimeFunctionError as error:
        atomic_json(project/'build/reports/native-cpu-boundary.json',
                    error.audit or {'status': 'FAILED', 'error': str(error), 'n64recomp_executed': False})
        raise
    atomic_json(project/'build/reports/native-cpu-boundary.json', boundary_audit)
    policy_audit = validate_policy_bindings(functions, profile, policy, reimplemented, ignored)
    private = runtime/'build/private'; private.mkdir(parents=True, exist_ok=True)
    generated = runtime/'generated'; generated.mkdir(parents=True, exist_ok=True)
    work = runtime/'build/generated'; work.mkdir(parents=True, exist_ok=True)
    elf_path = private/'glover.us.elf'
    elf = make_native_elf(rom, profile, functions)
    valid = verify_native_elf(elf, rom, profile)
    atomic_bytes(elf_path,elf)
    atomic_bytes(generated/'bootstrap.generated.hpp',bootstrap_header(rom,profile).encode())
    atomic_bytes(work/'glover.us.toml',recomp_config(rom,elf_path,rom_path,runtime/'runtime-recomp/RecompiledFuncs',profile,policy=policy).encode())
    rsp, rsp_audit = audio_config(rom,rom_path,runtime/'runtime-recomp/RecompiledRSP/glover_aspMain.cpp')
    atomic_bytes(work/'glover.rsp.toml',rsp.encode())
    # Do not write original instruction streams into shareable diagnostics.
    report = {'metadata':audit,'elf':valid,'audio':rsp_audit,'rejected_aliases':rejected,
              'sdk_symbols':[dict(r) for _,r in sorted(sdk.items())],
              'verified_sdk_aliases': alias_groups,
              'policy_symbol_bindings': policy_audit,
              'native_cpu_boundary_audit': boundary_audit,
              'sdk_report_sha256': hashlib.sha256(symbols_path.read_bytes()).hexdigest(),
              'upstream_symbol_sets': {'reimplemented': len(reimplemented), 'ignored': len(ignored)},
              'booted':False,'native_compilation_completed':False}
    atomic_json(project/'build/reports/native-inputs.json',report)
    atomic_json(runtime/'build/generated/glover-inputs-report.json',report)
    return report
