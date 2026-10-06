"""Explicit, ROM-checked SDK aliases; never infer a winner from scan order.

Both addresses retain the known SDK name at the scanner-validation boundary.
The separate checked runtime classification can assign unique ELF names to
emit their original bodies. No generated C or fabricated hardware result is used.
"""
from __future__ import annotations
import hashlib
from collections import defaultdict
from typing import Any


class SdkAliasError(ValueError):
    pass


def _integer(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SdkAliasError("Alias address/size is not an integer.")
    try:
        result = int(value, 0) if isinstance(value, str) else value
    except ValueError as error:
        raise SdkAliasError("Malformed SDK alias integer.") from error
    if not 0 <= result <= 0xFFFFFFFF:
        raise SdkAliasError("SDK alias integer is outside the 32-bit range.")
    return result


def checked_alias_group(name: str, records: list[dict], profile: dict,
                        rom: bytes, policy: dict, ignored_only: set[str]) -> dict:
    """Return a checked evidence record, or refuse the entire group."""
    if policy.get("schema_version") != 1 or not isinstance(policy.get("groups"), list):
        raise SdkAliasError("Unsupported SDK alias policy.")
    expected_rom = policy.get("rom_sha1")
    if (not expected_rom or expected_rom != profile.get("sha1") or
            hashlib.sha1(rom).hexdigest() != expected_rom):
        raise SdkAliasError("SDK alias policy does not match the complete USA ROM.")
    groups = [group for group in policy["groups"] if group.get("name") == name]
    if len(groups) != 1:
        raise SdkAliasError(f"No unique reviewed SDK alias policy for {name}.")
    group = groups[0]
    if group.get("handling") != "upstream-ignored" or name not in ignored_only:
        raise SdkAliasError(f"SDK alias {name} is not an upstream ignored-only helper.")
    addresses = [_integer(value) for value in group.get("addresses", [])]
    actual_addresses = [row["vram"] for row in records]
    if (len(addresses) < 2 or len(set(addresses)) != len(addresses) or
            sorted(actual_addresses) != sorted(addresses)):
        raise SdkAliasError(f"SDK alias address set changed for {name}.")
    size = _integer(group.get("size"))
    if not size or size % 4 or any(address % 4 for address in addresses):
        raise SdkAliasError("SDK alias size/addresses must be nonzero and word aligned.")
    digest = group.get("body_sha256", "")
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise SdkAliasError("SDK alias has no valid reviewed SHA-256.")
    delta = profile["load_vram"] - profile["load_rom_offset"]
    bodies = []
    for row in records:
        if row["name"] != name or row["size"] not in (0, size):
            raise SdkAliasError(f"SDK alias signature size changed for {name}.")
        offset = row["vram"] - delta
        if (offset < 0 or offset + size > len(rom) or not any(
                s["kind"] == "code" and s["start"] <= offset and
                offset + size <= s["end"] for s in profile["sections"])):
            raise SdkAliasError(f"SDK alias leaves mapped executable memory: {name}.")
        body = rom[offset:offset + size]
        if hashlib.sha256(body).hexdigest() != digest:
            raise SdkAliasError(f"SDK alias instruction hash differs at 0x{row['vram']:08X}.")
        bodies.append(body)
    if any(body != bodies[0] for body in bodies[1:]):
        raise SdkAliasError("SDK alias bodies are not byte-identical.")
    return {"name": name, "addresses": sorted(addresses), "size": size,
            "body_sha256": digest, "handling": "upstream-ignored",
            "rom_sha1": expected_rom, "status": "ROM_VERIFIED"}


def alias_groups_from_symbols(symbols: dict[int, dict]) -> list[dict]:
    groups = {}
    for row in symbols.values():
        record = row.get("verified_sdk_alias")
        if record:
            previous = groups.setdefault(record["name"], record)
            if previous != record:
                raise SdkAliasError("Inconsistent SDK alias evidence records.")
    return [groups[name] for name in sorted(groups)]


def validate_elf_aliases(functions: list[dict], rom: bytes, profile: dict,
                        verified_aliases: list[dict] | None = None) -> None:
    """Allow duplicate ELF names only for the exact verified ignored SDK group."""
    by_name = defaultdict(list)
    for row in functions:
        by_name[row["name"]].append(row)
    approved = {}
    for group in verified_aliases or []:
        if group["name"] in approved:
            raise SdkAliasError("Duplicate SDK alias approval.")
        approved[group["name"]] = group
    for name, rows in by_name.items():
        if len(rows) == 1 and name not in approved:
            continue
        group = approved.get(name)
        if group is None:
            raise SdkAliasError(f"Duplicate function symbol: {name}.")
        if group.get("status") != "ROM_VERIFIED":
            raise SdkAliasError("SDK alias evidence was not verified.")
        checked = checked_alias_group(name, rows, profile, rom,
            {"schema_version": 1, "rom_sha1": group.get("rom_sha1"),
             "groups": [group]}, {name})
        if checked != group:
            raise SdkAliasError("SDK alias evidence does not describe the emitted ELF.")
    if set(approved) - set(by_name):
        raise SdkAliasError("An approved SDK alias group is absent from the ELF.")
