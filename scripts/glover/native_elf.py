"""Native-recompiler ELF with a real ROM-origin section.

N64Recomp normalises allocated-section ROM addresses by the lowest load
address. The foundation ELF starts at ROM 0x1000. Without an allocated
ROM-origin section its code and data are shifted down by 0x1000 in the
recompiler. A separately stored, non-executable 64-byte cartridge header
anchors the native input at ROM offset zero without overwriting ELF metadata.
"""
from __future__ import annotations
import hashlib
import re
import struct
from .elf import make_analysis_elf, inspect_elf, verify_against_rom, ElfError, aligned
from .sdk_aliases import validate_elf_aliases


def native_layout(profile: dict) -> tuple[dict, dict[str, str]]:
    """Give native code sections identifier-safe names before N64Recomp runs.

    The pinned overlay emitter strips LEADING dots only. '.text.0' therefore
    becomes the invalid C++ token 'section_3_text.0_funcs'. Keep the historical
    analysis profile intact and rename its native code-section metadata only.
    No ROM bytes, section indexes, addresses or function extents are changed.
    """
    sections = []
    mapping = {}
    for section in profile['sections']:
        name = section['name']
        if section['kind'] == 'code':
            if not isinstance(name, str) or not re.fullmatch(r'\.*[A-Za-z_][A-Za-z0-9_.]*', name):
                raise ElfError('Unsupported native code section name: ' + repr(name))
            # Retain the ordinary ELF leading dot; do not allow punctuation in
            # the part N64Recomp interpolates into its C/C++ array identifiers.
            new_name = ('.' if name.startswith('.') else '') + name.lstrip('.').replace('.', '_')
        else:
            new_name = name
        if name in mapping:
            raise ElfError('Duplicate source section name: ' + name)
        mapping[name] = new_name
        sections.append({**section, 'name': new_name})
    names = [s['name'] for s in sections] + ['.bss', '.symtab', '.strtab', '.shstrtab', '.rom_header']
    if len(names) != len(set(names)):
        raise ElfError('Native section-name normalization would create a collision.')
    return {**profile, 'sections': sections}, mapping


def validate_native_identifiers(parsed: dict) -> None:
    """Fail on unsafe input symbols before a full native dependency build."""
    for section in parsed['sections']:
        if section['flags'] & 4:
            identifier = f"section_{section['index']}_{section['name'].lstrip('.')}_funcs"
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', identifier):
                raise ElfError('Unsafe N64Recomp overlay identifier: ' + identifier)
    for function in parsed['functions']:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', function['name']):
            raise ElfError('Unsafe native function identifier: ' + function['name'])


def make_native_elf(rom: bytes, profile: dict, functions: list[dict], *,
                    verified_aliases: list[dict] | None = None) -> bytes:
    profile, names = native_layout(profile)
    functions = [{**function, 'section': names[function['section']]} for function in functions]
    output = bytearray(make_analysis_elf(rom, profile, functions,
                                        verified_aliases=verified_aliases))
    header = list(struct.unpack_from(">HHIIIIIHHHHHH", output, 16))
    if header[9] != 1 or header[4] + 2 * 32 > profile["load_rom_offset"]:
        raise ElfError("Unexpected foundation ELF program-header layout.")
    sections = [list(struct.unpack_from(">10I", output, header[5] + i * 40))
                for i in range(header[11])]
    strings_section = sections[header[12]]
    strings = bytes(output[strings_section[4]:strings_section[4] + strings_section[5]])
    name_offset = len(strings)
    strings += b".rom_header\0"

    def append(blob: bytes, alignment: int) -> int:
        offset = aligned(len(output), alignment)
        output.extend(bytes(offset - len(output)))
        output.extend(blob)
        return offset

    cartridge_header = append(rom[:0x40], 16)
    strings_offset = append(strings, 1)
    strings_section[4] = strings_offset
    strings_section[5] = len(strings)
    # SHF_ALLOC | SHT_PROGBITS, read-only and non-executable, guest VMA 0.
    sections.append([name_offset, 1, 2, 0, cartridge_header, 0x40, 0, 0, 16, 0])
    section_offset = append(b"".join(struct.pack(">10I", *s) for s in sections), 4)
    header[5] = section_offset
    header[9] = 2
    header[11] = len(sections)
    struct.pack_into(">HHIIIIIHHHHHH", output, 16, *header)
    # PT_LOAD with cartridge LMA zero. It is not guest executable startup.
    struct.pack_into(">8I", output, header[4] + 32,
                     1, cartridge_header, 0, 0, 0x40, 0x40, 4, 16)
    validate_native_identifiers(inspect_elf(bytes(output)))
    return bytes(output)


def recompiler_rom_mapping(data: bytes) -> dict[str, int]:
    """Replay the pinned reader's load-address normalisation, read-only.

    This validates input layout, not execution of N64Recomp itself.
    Source: N64Recomp 81213c1 src/elf.cpp read_sections.
    """
    parsed = inspect_elf(data)
    loads = [p for p in parsed["programs"] if p["type"] == 1]
    addresses = {}
    for section in parsed["sections"]:
        if section["type"] == 8 or not section["flags"] & 2 or not section["size"]:
            continue
        matches = [p for p in loads if
                   p["offset"] <= section["offset"] and
                   section["offset"] + section["size"] <= p["offset"] + p["file_size"]]
        if len(matches) != 1:
            raise ElfError("Allocated section does not have exactly one containing segment.")
        segment = matches[0]
        addresses[section["name"]] = segment["rom_offset"] + section["offset"] - segment["offset"]
    if not addresses:
        raise ElfError("ELF contains no mapped ROM sections.")
    minimum = min(addresses.values())
    return {name: address - minimum for name, address in addresses.items()}


def verify_native_elf(data: bytes, rom: bytes, profile: dict, *,
                      verified_aliases: list[dict] | None = None) -> dict:
    profile, names = native_layout(profile)
    parsed = inspect_elf(data)
    validate_native_identifiers(parsed)
    if len(parsed["programs"]) != 2 or any(p["type"] != 1 for p in parsed["programs"]):
        raise ElfError("Native ELF must contain the game and ROM-header load segments.")
    headers = [s for s in parsed["sections"] if s["name"] == ".rom_header"]
    if len(headers) != 1:
        raise ElfError("Native ELF ROM-origin header is absent or duplicated.")
    section = headers[0]
    load = parsed["programs"][1]
    if (section["type"], section["flags"], section["vram"], section["size"]) != (1, 2, 0, 0x40):
        raise ElfError("ROM-origin section must be read-only non-executable data at ROM zero.")
    if (load["offset"], load["vram"], load["rom_offset"],
            load["file_size"], load["memory_size"], load["flags"]) != (
            section["offset"], 0, 0, 0x40, 0x40, 4):
        raise ElfError("Invalid native ROM-origin load segment.")
    if section["offset"] < profile["sections"][-1]["end"]:
        raise ElfError("ROM-origin storage overlaps the original mapped game bytes.")
    if data[section["offset"]:section["offset"] + 0x40] != rom[:0x40]:
        raise ElfError("Native ROM-origin bytes differ from the supplied ROM.")

    # Reuse the independent foundation payload/BSS checks on a read-only
    # inspection view exposing its original first segment. The actual ELF and
    # its verified second segment are never changed on disk.
    view = bytearray(data)
    struct.pack_into(">H", view, 44, 1)
    report = verify_against_rom(bytes(view), rom, profile)
    validate_elf_aliases(parsed["functions"], rom, profile, verified_aliases)
    mapping = recompiler_rom_mapping(data)
    for expected in profile["sections"]:
        if mapping.get(expected["name"]) != expected["start"]:
            raise ElfError("Recompiler ROM offset differs for " + expected["name"])
    delta = profile["load_vram"] - profile["load_rom_offset"]
    code_sections = {s["name"]: s for s in parsed["sections"]}
    for function in parsed["functions"]:
        s = code_sections[function["section"]]
        offset = mapping[s["name"]] + function["vram"] - s["vram"]
        if offset != function["vram"] - delta:
            raise ElfError("Recompiler function ROM address differs.")
        stored = s["offset"] + function["vram"] - s["vram"]
        if data[stored:stored + function["size"]] != rom[offset:offset + function["size"]]:
            raise ElfError("Recompiler function bytes differ from the selected ROM.")
    report.update({
        "elf_sha256": hashlib.sha256(data).hexdigest(),
        "format": "native-rom-origin-anchored",
        "rom_header_bytes": "IDENTICAL",
        "recompiler_rom_mapping": "PASS",
        "recompiler_rom_origin": 0,
        "mapped_sections": mapping,
        "native_section_names": names,
        "native_c_identifiers": "PASS",
        "actual_n64recomp_executed": False
    })
    return report
