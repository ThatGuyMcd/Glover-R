"""Strict, read-only ROM identification with explicit private-copy output."""
from __future__ import annotations
import hashlib
import json
import os
import struct
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAGICS = {
    bytes.fromhex("80371240"): "big-endian",
    bytes.fromhex("37804012"): "byte-swapped-16",
    bytes.fromhex("40123780"): "little-endian-32",
}

class RomError(ValueError):
    pass

@dataclass(frozen=True)
class RomIdentity:
    source_name: str
    source_byte_order: str
    size: int
    source_sha256: str
    canonical_sha1: str
    canonical_sha256: str
    internal_name: str
    game_code: str
    revision: int
    header_entrypoint: int
    header_crc1: str
    header_crc2: str


def load_profile(path: Path) -> dict[str, Any]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    if profile.get("schema_version") != 1:
        raise RomError("Unsupported game-profile schema.")
    import re
    for name, length in (("sha1", 40), ("sha256", 64)):
        if not isinstance(profile.get(name), str) or not re.fullmatch(f"[0-9a-f]{{{length}}}", profile[name]):
            raise RomError(f"Invalid profile {name}.")
    integers = ("size", "revision", "load_rom_offset", "load_vram", "callable_entrypoint",
                "initial_stack", "bss_start", "bss_end")
    if any(type(profile.get(key)) is not int or not 0 <= profile[key] <= 0xFFFFFFFF for key in integers):
        raise RomError("Invalid integer in game profile.")
    if profile["size"] < 0x1040 or profile["size"] % 4:
        raise RomError("Invalid ROM size in game profile.")
    if not isinstance(profile.get("game_code"), str) or len(profile["game_code"]) != 4:
        raise RomError("Invalid game code in profile.")
    sections = profile.get("sections")
    if not isinstance(sections, list) or not sections:
        raise RomError("Profile has no initial memory map.")
    previous = profile["load_rom_offset"]
    names = set()
    for section in sections:
        if (section.get("kind") not in ("code", "data", "rodata") or
                type(section.get("start")) is not int or type(section.get("end")) is not int or
                section["start"] != previous or section["end"] <= previous or
                section["end"] > profile["size"] or section["start"] % 4 or section["end"] % 4):
            raise RomError("Invalid or non-contiguous initial section map.")
        if section.get("name") in names or not isinstance(section.get("name"), str):
            raise RomError("Duplicate/missing section name.")
        names.add(section["name"]); previous = section["end"]
    delta = profile["load_vram"] - profile["load_rom_offset"]
    if (previous + delta != profile["bss_start"] or
            not 0x80000000 <= profile["load_vram"] < profile["bss_start"] < profile["bss_end"] <= 0x80800000):
        raise RomError("Invalid load/BSS placement in profile.")
    return profile


def canonicalize(data: bytes) -> tuple[bytes, str]:
    """Determine actual byte order from the header, never from the extension."""
    if len(data) < 64 or len(data) % 4:
        raise RomError("ROM is too short or its length is not a multiple of four.")
    order = MAGICS.get(data[:4])
    if order is None:
        if not any(data[:min(len(data), 4096)]):
            raise RomError("Unrecognised ROM header: the beginning is zero-filled. "
                           "The damaged supplied .z64 is not usable; select the valid USA copy.")
        raise RomError("Unrecognised N64 byte-order header. No guessed conversion was performed.")
    if order == "big-endian":
        return bytes(data), order
    result = bytearray(len(data))
    if order == "byte-swapped-16":
        result[0::2], result[1::2] = data[1::2], data[0::2]
    else:
        for index in range(4):
            result[index::4] = data[3-index::4]
    return bytes(result), order


def inspect_bytes(data: bytes, profile: dict[str, Any], source_name: str = "ROM") -> tuple[bytes, RomIdentity]:
    if len(data) != profile["size"]:
        raise RomError(f"Unsupported size: {len(data):,} bytes; this target requires {profile['size']:,}. "
                       "Do not trim, pad or patch the ROM to bypass validation.")
    canonical, order = canonicalize(data)
    sha1 = hashlib.sha1(canonical).hexdigest()
    sha256 = hashlib.sha256(canonical).hexdigest()
    if sha1 != profile["sha1"] or sha256 != profile["sha256"]:
        raise RomError(f"Unsupported or modified ROM after byte-order normalization. "
                       f"SHA-1 {sha1}; expected {profile['sha1']}.")
    code = canonical[0x3b:0x3f].decode("ascii", errors="strict")
    revision = canonical[0x3f]
    if code != profile["game_code"] or revision != profile["revision"]:
        raise RomError("Header identity disagrees with the pinned game profile.")
    identity = RomIdentity(
        source_name=source_name,
        source_byte_order=order,
        size=len(canonical),
        source_sha256=hashlib.sha256(data).hexdigest(),
        canonical_sha1=sha1,
        canonical_sha256=sha256,
        internal_name=canonical[0x20:0x34].decode("ascii").rstrip(" \x00"),
        game_code=code,
        revision=revision,
        header_entrypoint=struct.unpack_from(">I", canonical, 8)[0],
        header_crc1=f"{struct.unpack_from('>I', canonical, 16)[0]:08X}",
        header_crc2=f"{struct.unpack_from('>I', canonical, 20)[0]:08X}",
    )
    return canonical, identity


def inspect_file(path: Path, profile: dict[str, Any]) -> tuple[bytes, RomIdentity]:
    if not path.is_file():
        raise RomError(f"ROM is not a readable regular file: {path}")
    if path.stat().st_size != profile["size"]:
        raise RomError(f"Wrong ROM size: {path.stat().st_size:,}; expected {profile['size']:,} bytes.")
    return inspect_bytes(path.read_bytes(), profile, path.name)


def atomic_bytes(path: Path, data: bytes) -> None:
    """Replace only a regular output; never follow a destination symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RomError(f"Refusing to write through a symlink: {path}")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path: Path, data: Any) -> None:
    atomic_bytes(path, (json.dumps(data, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))


def write_private_copy(source: Path, destination: Path, canonical: bytes) -> None:
    if source.resolve() == destination.resolve():
        # A previously generated private copy can be reused without touching it.
        if source.read_bytes() != canonical:
            raise RomError("Refusing to normalize a ROM in place. Choose a separate private destination.")
        return
    if destination.exists() and os.path.samefile(source, destination):
        raise RomError("Input and output refer to the same file.")
    atomic_bytes(destination, canonical)


def identity_dict(identity: RomIdentity) -> dict[str, Any]:
    return asdict(identity)
