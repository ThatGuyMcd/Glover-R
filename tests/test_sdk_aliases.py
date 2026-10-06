"""SDK alias regression tests; synthetic ROM plus real captured scan metadata."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from fixtures import fixture
from glover.sdk_aliases import checked_alias_group, SdkAliasError
from glover.native_inputs import parse_symbols, select_symbols, NativeInputError
from glover.elf import make_analysis_elf, inspect_elf, ElfError


def setup_alias():
    image, profile = fixture()
    image = bytearray(image)
    # Synthetic leaf: jr ra; nop; nop. Not extracted game instructions.
    body = bytes.fromhex("03e000080000000000000000")
    addresses = [0x8010C920, 0x8010C960]
    delta = profile["load_vram"] - profile["load_rom_offset"]
    for a in addresses:
        image[a - delta:a - delta + len(body)] = body
    image = bytes(image)
    profile["sha1"] = hashlib.sha1(image).hexdigest()
    profile["sha256"] = hashlib.sha256(image).hexdigest()
    policy = {"schema_version": 1, "rom_sha1": profile["sha1"], "groups": [{
        "name": "__osGetSR", "handling": "upstream-ignored", "size": len(body),
        "body_sha256": hashlib.sha256(body).hexdigest(), "addresses": addresses}]}
    records = [{"name": "__osGetSR", "vram": addresses[0], "size": 12, "evidence": "signature"},
               {"name": "__osGetSR", "vram": addresses[1], "size": 0, "evidence": "signature-relocation"}]
    return image, profile, policy, records


class SdkAliasTests(unittest.TestCase):
    def checked(self):
        image, profile, policy, records = setup_alias()
        return image, profile, records, checked_alias_group(
            "__osGetSR", records, profile, image, policy, {"__osGetSR"})

    def test_both_addresses_and_sdk_name_are_retained(self):
        image, profile, policy, records = setup_alias()
        selected, rejected = select_symbols(records, profile, {"__osGetSR"},
            check_anchors=False, rom=image, alias_policy=policy, ignored_only={"__osGetSR"})
        self.assertEqual(sorted(selected), sorted(r["vram"] for r in records))
        self.assertEqual([r["name"] for r in selected.values()], ["__osGetSR", "__osGetSR"])
        self.assertEqual([r["size"] for r in selected.values()], [12, 12])
        self.assertEqual(rejected, [])

    def test_same_report_without_policy_still_fails(self):
        image, profile, policy, records = setup_alias()
        with self.assertRaisesRegex(NativeInputError, "Multiple executable copies"):
            select_symbols(records, profile, {"__osGetSR"}, check_anchors=False)

    def test_unknown_duplicate_still_fails(self):
        image, profile, policy, records = setup_alias()
        for r in records: r["name"] = "unknown"
        with self.assertRaisesRegex(NativeInputError, "No unique"):
            select_symbols(records, profile, {"unknown"}, check_anchors=False,
                rom=image, alias_policy=policy, ignored_only={"unknown"})

    def test_changed_complete_rom_is_refused(self):
        image, profile, policy, records = setup_alias()
        image = image[:-1] + bytes([image[-1] ^ 1])
        with self.assertRaisesRegex(SdkAliasError, "complete USA ROM"):
            checked_alias_group("__osGetSR", records, profile, image, policy, {"__osGetSR"})

    def test_changed_body_is_refused_even_with_updated_whole_rom_hash(self):
        image, profile, policy, records = setup_alias()
        image = bytearray(image)
        delta = profile["load_vram"] - profile["load_rom_offset"]
        image[records[1]["vram"] - delta] ^= 1
        image = bytes(image)
        profile["sha1"] = policy["rom_sha1"] = hashlib.sha1(image).hexdigest()
        with self.assertRaisesRegex(SdkAliasError, "instruction hash"):
            checked_alias_group("__osGetSR", records, profile, image, policy, {"__osGetSR"})

    def test_third_copy_is_not_accepted(self):
        image, profile, policy, records = setup_alias()
        records.append({**records[0], "vram": records[0]["vram"] + 0x80})
        with self.assertRaisesRegex(SdkAliasError, "address set"):
            checked_alias_group("__osGetSR", records, profile, image, policy, {"__osGetSR"})

    def test_missing_copy_is_not_accepted(self):
        image, profile, policy, records = setup_alias()
        with self.assertRaisesRegex(SdkAliasError, "address set"):
            checked_alias_group("__osGetSR", records[:1], profile, image, policy, {"__osGetSR"})

    def test_changed_full_signature_size_is_refused(self):
        image, profile, policy, records = setup_alias()
        records[0]["size"] = 16
        with self.assertRaisesRegex(SdkAliasError, "signature size"):
            checked_alias_group("__osGetSR", records, profile, image, policy, {"__osGetSR"})

    def test_reimplemented_or_unknown_helper_not_treated_as_ignored(self):
        image, profile, policy, records = setup_alias()
        with self.assertRaisesRegex(SdkAliasError, "ignored-only"):
            checked_alias_group("__osGetSR", records, profile, image, policy, set())

    def test_elf_roundtrip_retains_the_two_function_addresses(self):
        image, profile, records, group = self.checked()
        delta = profile["load_vram"] - profile["load_rom_offset"]
        functions = [{**r, "size": 12, "section": ".text.0", "rom_offset": r["vram"] - delta}
                     for r in records]
        data = make_analysis_elf(image, profile, functions, verified_aliases=[group])
        functions_out = inspect_elf(data)["functions"]
        self.assertEqual([(r["name"], r["vram"]) for r in functions_out],
                         [(r["name"], r["vram"]) for r in records])
        with self.assertRaisesRegex(ElfError, "Duplicate"):
            make_analysis_elf(image, profile, functions)

    def test_elf_rechecks_alias_body_instead_of_trusting_annotation(self):
        image, profile, records, group = self.checked()
        functions = [{**r, "size": 12, "section": ".text.0"} for r in records]
        group["body_sha256"] = "0" * 64
        with self.assertRaises(ElfError):
            make_analysis_elf(image, profile, functions, verified_aliases=[group])

    def test_unmodified_uploaded_scan_reproduces_old_stop(self):
        profile = json.loads((ROOT / "config/glover.us.json").read_text())
        for key in ("load_vram", "load_rom_offset"):
            self.assertIsInstance(profile[key], int)
        groups = json.loads((ROOT / "tests/data/n64recomp-sdk-sets-81213c1.json").read_text())
        allowed = set(groups["reimplemented_funcs"]) | set(groups["ignored_funcs"])
        report = (ROOT / "tests/data/glover-sdk-symbols-20260930.txt").read_bytes()
        self.assertEqual(hashlib.sha256(report).hexdigest(),
                         "82a0abcfa32b808e0caffe241c4100028b3cae9507685c62dcf57ca0d66553d1")
        with self.assertRaisesRegex(NativeInputError, "__osGetSR.*0x8010D9B4, 0x801C7320"):
            select_symbols(parse_symbols(report.decode()), profile, allowed)

    def test_project_policy_has_only_the_reviewed_duplicate(self):
        policy = json.loads((ROOT / "config/sdk-aliases.json").read_text())
        self.assertEqual([g["name"] for g in policy["groups"]], ["__osGetSR"])
        self.assertEqual(policy["groups"][0]["addresses"], ["0x8010D9B4", "0x801C7320"])
        self.assertEqual(policy["groups"][0]["handling"], "upstream-ignored")

if __name__ == "__main__":
    unittest.main()
