"""Decode Glover's retail startup. This does not emulate or run the game."""
from __future__ import annotations
import hashlib
import struct
from typing import Any

class BootstrapError(ValueError):
    pass


def signed16(value: int) -> int:
    return value - 0x10000 if value & 0x8000 else value


def signed32(value: int) -> int:
    return value - 0x100000000 if value & 0x80000000 else value


def decode_bootstrap(rom: bytes, profile: dict[str, Any]) -> dict[str, Any]:
    base = profile["load_rom_offset"]
    if base < 0 or base + 64 > len(rom):
        raise BootstrapError("Bootstrap lies outside the ROM.")
    words = struct.unpack_from(">16I", rom, base)
    vram = profile["load_vram"]
    # Strict instruction-shape checks; low immediates are derived, not copied from Rocket.
    checks = {
        0: (0xffff0000, 0x3c1d0000),  # lui sp
        1: (0xffff0000, 0x27bd0000),  # addiu sp,sp
        2: (0xffff0000, 0x3c080000),  # lui t0
        3: (0xffff0000, 0x25080000),  # addiu t0,t0
        4: (0xffff0000, 0x3c090000),  # lui t1
        5: (0xffff0000, 0x25290000),  # addiu t1,t1
        6: (0xffffffff, 0x11090005),  # beq t0,t1,done
        7: (0xffffffff, 0),
        8: (0xffffffff, 0x25080004),
        9: (0xffffffff, 0x0109082b),
        10: (0xffffffff, 0x1420fffd),
        11: (0xffffffff, 0xad00fffc),
        12: (0xfc000000, 0x0c000000), # jal callable entry
        13: (0xffffffff, 0),
        14: (0xfc00003f, 0x0000000d),# intentional BREAK on return
        15: (0xffffffff, 0),
    }
    for index, (mask, expected) in checks.items():
        if words[index] & mask != expected:
            raise BootstrapError(f"Unsupported bootstrap instruction shape at 0x{vram+index*4:08X}.")
    def address(hi: int, lo: int) -> int:
        return (((words[hi] & 0xffff) << 16) + signed16(words[lo] & 0xffff)) & 0xffffffff
    stack = address(0, 1)
    bss_start = address(2, 3)
    bss_end = address(4, 5)
    callsite = vram + 12 * 4
    entry = ((callsite + 4) & 0xf0000000) | ((words[12] & 0x03ffffff) << 2)
    values = {"initial_stack": stack, "bss_start": bss_start,
              "bss_end": bss_end, "callable_entrypoint": entry}
    for key, actual in values.items():
        if actual != profile[key]:
            raise BootstrapError(f"{key} decoded as 0x{actual:08X}; profile expects 0x{profile[key]:08X}.")
    if not (0x80000000 <= bss_start <= bss_end <= 0x80800000):
        raise BootstrapError("BSS does not fit 8 MiB of RDRAM.")
    if not bss_start <= stack <= bss_end or stack % 8:
        raise BootstrapError("Unexpected caller stack placement/alignment.")
    offset = entry - vram + base
    if not any(s["kind"] == "code" and s["start"] <= offset < s["end"]
               for s in profile["sections"]):
        raise BootstrapError("Callable entrypoint is outside mapped executable sections.")
    return {**values, "retail_load_vram": vram, "load_rom_offset": base,
            "caller_stack_sign_extended": signed32(stack),
            "bss_bytes": bss_end-bss_start,
            "bootstrap_sha256": hashlib.sha256(rom[base:base+64]).hexdigest(),
            "raw_bootstrap_returns_to_break": True,
            "verified_by": "instruction-shape decoding plus pinned whole-ROM hashes"}


