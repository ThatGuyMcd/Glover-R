"""ROM-checked distinctions between native game code and hardware handlers.

This operates BEFORE N64Recomp, on symbols and maintained policy only. It never
writes generated C. Unknown hardware instructions, new direct callers into a
removed handler, or drift in an approved range fail closed.
"""
from __future__ import annotations
from bisect import bisect_right
from collections import Counter
import hashlib
import re
import struct
from .analysis import control_flow


class RuntimeFunctionError(ValueError):
    def __init__(self, message: str, *, audit: dict | None = None):
        super().__init__(message)
        self.audit = audit


def integer(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise RuntimeFunctionError('Classification integer is invalid.')
    try:
        value = int(value, 0) if isinstance(value, str) else value
    except ValueError as error:
        raise RuntimeFunctionError('Malformed classification integer.') from error
    if not 0 <= value <= 0xFFFFFFFF:
        raise RuntimeFunctionError('Classification integer is outside the 32-bit range.')
    return value


def _digest(data: bytes, expected, label: str) -> None:
    if (not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)
            or hashlib.sha256(data).hexdigest() != expected):
        raise RuntimeFunctionError('ROM instruction hash differs: ' + label)


def checked_additional_entries(rom: bytes, profile: dict, entries: list[dict]) -> list[dict]:
    """ROM-checked input boundaries, never synthesized function bodies."""
    if not isinstance(entries, list):
        raise RuntimeFunctionError('Invalid additional-entry list.')
    delta = profile['load_vram'] - profile['load_rom_offset']
    checked = []; seen = set()
    for entry in entries:
        address, size = integer(entry['vram']), integer(entry['size'])
        off = address - delta
        if address in seen or address % 4 or not size or size % 4 or off < 0 or off+size > len(rom):
            raise RuntimeFunctionError('Invalid/duplicate reviewed entry extent.')
        seen.add(address)
        section = next((s for s in profile['sections'] if s['kind']=='code' and
                        s['start'] <= off and off+size <= s['end']), None)
        if not section or not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*', entry['name']):
            raise RuntimeFunctionError('Reviewed entry is outside mapped code or has an invalid name.')
        _digest(rom[off:off+size], entry['body_sha256'], entry['name'])
        checked.append({'name': entry['name'], 'vram': address, 'rom_offset': off,
                        'section': section['name'], 'evidence': ['ROM-checked-callback-boundary'],
                        'reviewed_size': size})
    return checked


def classify_functions(rom: bytes, profile: dict, functions: list[dict],
                       classification: dict, policy: dict,
                       reimplemented: set[str], upstream_ignored: set[str]) -> tuple[list[dict], dict]:
    """Validate all reviewed ranges and return a new symbol list, not new bytes."""
    if classification.get('schema_version') != 1:
        raise RuntimeFunctionError('Unsupported CPU-classification schema.')
    if (classification.get('rom_sha1') != profile.get('sha1') or
            hashlib.sha1(rom).hexdigest() != profile.get('sha1') or
            classification.get('rom_sha256') != profile.get('sha256') or
            hashlib.sha256(rom).hexdigest() != profile.get('sha256')):
        raise RuntimeFunctionError('CPU classification does not match the complete ROM.')
    if policy.get('romSha1') != profile['sha1']:
        raise RuntimeFunctionError('CPU classification and recomp policy target different ROMs.')
    if policy.get('stubs') or policy.get('renamed'):
        raise RuntimeFunctionError('The checked runtime classification does not permit stubs or policy renames.')
    rules = classification.get('rules')
    if not isinstance(rules, list) or not rules:
        raise RuntimeFunctionError('Missing CPU classification rules.')
    by_address = {f['vram']: f for f in functions}
    if len(by_address) != len(functions):
        raise RuntimeFunctionError('Overlapping/duplicate native entry addresses.')
    for entry in checked_additional_entries(rom, profile, classification.get('additional_entries', [])):
        f = by_address.get(entry['vram'])
        if not f or f['name'] != entry['name'] or f['size'] != entry['reviewed_size']:
            raise RuntimeFunctionError('Reviewed callback entry is missing or its computed size changed.')
    delta = profile['load_vram'] - profile['load_rom_offset']
    changed = {a: dict(f) for a, f in by_address.items()}
    reviewed = []; seen = set(); policy_ignored = []; regions = []
    for rule in rules:
        address, size, end = (integer(rule[k]) for k in ('vram', 'size', 'region_end'))
        if address in seen or address % 4 or not size or size % 4 or end % 4 or end < address + size:
            raise RuntimeFunctionError('Duplicate, unaligned or invalid classified extent.')
        seen.add(address)
        offset = address - delta
        if offset < 0 or end - delta > len(rom) or not any(
                s['kind'] == 'code' and s['start'] <= offset and end - delta <= s['end']
                for s in profile['sections']):
            raise RuntimeFunctionError('Classified range leaves a mapped code section.')
        f = by_address.get(address)
        if not f or f['name'] != rule['elf_name'] or f['size'] != size:
            raise RuntimeFunctionError(f'Classified symbol/extent differs at 0x{address:08X}.')
        if any(address < a < end for a in by_address):
            raise RuntimeFunctionError(f'Unreviewed entry inside classified range 0x{address:08X}.')
        _digest(rom[offset:offset + size], rule['body_sha256'], rule['elf_name'])
        _digest(rom[offset:end - delta], rule['region_sha256'], rule['elf_name'] + ' complete region')
        action = rule['action']
        if action == 'hardware-only':
            if rule.get('native_name') or f['name'] in reimplemented | upstream_ignored:
                raise RuntimeFunctionError('Hardware-only policy must target its exact non-SDK symbol.')
            policy_ignored.append(f['name'])
            regions.append((address, end, f['name']))
        elif action in ('compile-original', 'upstream-ignored'):
            name = rule.get('native_name', '')
            if not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*', name):
                raise RuntimeFunctionError('Invalid native symbol override.')
            if action == 'compile-original':
                if f['name'] not in upstream_ignored - reimplemented or name in reimplemented | upstream_ignored:
                    raise RuntimeFunctionError('Original-body override must rescue an ignored-only SDK helper.')
            elif name not in upstream_ignored - reimplemented:
                raise RuntimeFunctionError('Private SDK helper is not upstream ignored-only.')
            changed[address]['name'] = name
            changed[address]['original_elf_name'] = f['name']
        elif action == 'cache-loop':
            if rule.get('native_name') or f['name'] in reimplemented | upstream_ignored:
                raise RuntimeFunctionError('Cache-loop rule must retain its original native function.')
        else:
            raise RuntimeFunctionError('Unknown classification action: ' + str(action))
        changed[address]['runtime_classification'] = action
        reviewed.append({'original_name': f['name'], 'native_name': changed[address]['name'],
                         'vram': address, 'size': size, 'region_end': end,
                         'body_sha256': rule['body_sha256'], 'region_sha256': rule['region_sha256'],
                         'action': action, 'status': 'ROM_VERIFIED'})
    if (not isinstance(policy.get('ignored'), list) or
            Counter(policy['ignored']) != Counter(policy_ignored)):
        raise RuntimeFunctionError('The policy ignored list differs from the reviewed hardware-only entries.')
    native = [changed[f['vram']] for f in functions]
    names = [f['name'] for f in native]
    if len(set(names)) != len(names):
        raise RuntimeFunctionError('Native symbol overrides are not unique.')
    # Restrict raw CACHE rewrites to the exact two separately reviewed loops.
    cache_rules = [r for r in rules if r['action'] == 'cache-loop']
    expected_patches = classification.get('cache_patches', [])
    if not isinstance(expected_patches, list) or len(cache_rules) != len(expected_patches):
        raise RuntimeFunctionError('Missing or duplicated reviewed cache-loop policy.')
    guarded_cache = set()
    for expected in expected_patches:
        pc = integer(expected['vram']); before = integer(expected['expectedInstruction'])
        if pc in guarded_cache or before >> 26 != 47 or integer(expected['value']) != 0:
            raise RuntimeFunctionError('Invalid reviewed cache operation.')
        guarded_cache.add(pc)
        owners = [r for r in cache_rules if r['elf_name'] == expected['function'] and
                  integer(r['vram']) <= pc < integer(r['vram']) + integer(r['size'])]
        matching = [p for p in policy.get('instructionPatches', []) if integer(p['vram']) == pc]
        if len(owners) != 1 or len(matching) != 1 or any(
                matching[0].get(k) != v for k, v in expected.items()):
            raise RuntimeFunctionError('Reviewed cache operation is absent from the maintained policy.')
        if matching[0].get('elfFunction') != expected['function']:
            raise RuntimeFunctionError('Reviewed cache operation changed its ELF binding.')
    audit = audit_native_functions(rom, profile, native, policy, reimplemented,
                                  upstream_ignored, regions=regions)
    audit.update({'reviewed_rules': reviewed, 'reviewed_cache_operations': sorted(guarded_cache),
                  'original_bytes_preserved': True, 'generated_source_modified': False,
                  'n64recomp_executed': False})
    if audit['issues']:
        summary = '; '.join(x['reason'] + f" in {x['function']} at 0x{x['pc']:08X}"
                            for x in audit['issues'][:12])
        raise RuntimeFunctionError(f'Native CPU boundary audit found {len(audit["issues"])} issue(s): ' + summary, audit=audit)
    return native, audit


def audit_native_functions(rom: bytes, profile: dict, functions: list[dict], policy: dict,
                           reimplemented: set[str], upstream_ignored: set[str], *,
                           regions: list[tuple[int, int, str]] | None = None) -> dict:
    """Read-only checks for known emitter hazards, NOT an alternative recompiler.

    Scan EXACT emitted extents and apply checked instruction policy in memory.
    Do not scan coarse text-section gaps as instructions. Direct edges into
    unavailable functions are rejected; arbitrary indirect flow still needs
    actual code generation and runtime testing.
    """
    delta = profile['load_vram'] - profile['load_rom_offset']
    by_address = {f['vram']: f for f in functions}
    starts = sorted(by_address)
    skipped_names = reimplemented | upstream_ignored | set(policy.get('ignored', []))
    patches = {}
    for p in policy.get('instructionPatches', []):
        pc, offset, expected, value = (integer(p[k]) for k in ('vram', 'romOffset', 'expectedInstruction', 'value'))
        if pc in patches or pc % 4 or offset != pc-delta or offset+4 > len(rom):
            raise RuntimeFunctionError('Duplicate or mismapped instruction patch in boundary audit.')
        if struct.unpack_from('>I', rom, offset)[0] != expected:
            raise RuntimeFunctionError(f'Instruction patch guard differs at 0x{pc:08X}.')
        patches[pc] = value
    issues = []; emitted = []; skipped = []; status_ops = []; indirect = []
    direct_edges = 0
    for f in functions:
        if f['name'] in skipped_names:
            skipped.append({'name': f['name'], 'vram': f['vram'],
                            'handling': 'host-service' if f['name'] in reimplemented else 'not-emitted'})
            continue
        emitted.append({'name': f['name'], 'vram': f['vram'], 'size': f['size']})
        for pc in f.get('boundary_fallthrough', []):
            issues.append({'function': f['name'], 'pc': pc,
                           'reason': 'CPU control flow or delay slot truncated at function boundary'})
        for pc in range(f['vram'], f['vram'] + f['size'], 4):
            word = patches.get(pc, struct.unpack_from('>I', rom, pc-delta)[0])
            op, rs, rd = word >> 26, (word >> 21) & 31, (word >> 11) & 31
            reason = None
            if op == 16:
                if rs in (0, 4) and rd == 12:
                    status_ops.append({'function': f['name'], 'pc': pc,
                                       'operation': 'read' if rs == 0 else 'write'})
                else:
                    reason = f'unsupported COP0 operation (rs={rs}, register={rd})'
            elif op == 17 and rs in (2, 6) and rd != 31:
                reason = f'unsupported FPU control register {rd}'
            elif op == 47:
                reason = 'unadapted hardware CACHE instruction'
            elif op == 0 and word & 63 == 9 and rd != 31:
                reason = 'JALR uses a nonstandard link register'
            if reason:
                issues.append({'function': f['name'], 'pc': pc, 'reason': reason})
            flow = control_flow(word, pc)
            if not flow:
                continue
            kind, target = flow
            if target is None:
                if kind in ('indirect-call', 'indirect-jump'):
                    indirect.append({'function': f['name'], 'pc': pc, 'kind': kind})
                continue
            direct_edges += 1
            bad_region = next((r for r in regions or [] if r[0] <= target < r[1]), None)
            if bad_region:
                issues.append({'function': f['name'], 'pc': pc, 'target': target,
                               'reason': 'direct transfer into hardware-only range ' + bad_region[2]})
                continue
            if f['vram'] <= target < f['vram'] + f['size']:
                continue
            dest = by_address.get(target)
            if dest:
                if dest['name'] in skipped_names - reimplemented:
                    issues.append({'function': f['name'], 'pc': pc, 'target': target,
                                   'reason': 'direct transfer to ignored-only function ' + dest['name']})
            else:
                # Branching into a different function's interior cannot be
                # assumed to be a supported native tail call.
                pos = bisect_right(starts, target) - 1
                containing = by_address[starts[pos]] if pos >= 0 else None
                label = (containing['name'] if containing and
                         target < containing['vram'] + containing['size'] else 'unmapped entry')
                issues.append({'function': f['name'], 'pc': pc, 'target': target,
                               'reason': 'direct transfer without an exact function entry (' + label + ')'})
    return {'status': 'PASS' if not issues else 'FAILED', 'emitted_function_count': len(emitted),
            'emitted_functions': emitted, 'skipped_function_count': len(skipped),
            'skipped_functions': skipped, 'decoded_direct_transfers': direct_edges,
            'supported_status_operations': status_ops, 'issues': issues,
            'indirect_transfers_requiring_runtime_validation': indirect,
            'scope': 'known-opcode and direct-edge audit only; not full N64Recomp execution or gameplay proof'}
