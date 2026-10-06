"""Shared native-source record contract for the writer and every reader.

The family and schema describe the file format, not a release number. VERSION
is separate provenance. This module is copied byte-for-byte to the assembled
workspace; neither verifier has a private GLOVER-BOOT-N compatibility string.
All checks are read-only. The legacy path is only for migration by the outer
assembler, never for executing an old workspace's native builder.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

SCHEMA_VERSION = 1
ADAPTER_FAMILY = 'GLOVER-NATIVE'
BASE_COMMIT = '133070e264350f17257a520ae0de4da98ce445b0'
RECORD_NAME = 'GLOVER-NATIVE-SOURCE.json'
LEGACY_ADAPTERS = frozenset({'GLOVER-BOOT-1', 'GLOVER-BOOT-2', 'GLOVER-BOOT-3'})
CONTRACT_PATH = 'scripts/glover/native_contract.py'
REQUIRED_CURRENT_FILES = frozenset({
    'VERSION', 'scripts/glover/__init__.py', CONTRACT_PATH,
    'scripts/verify_native_tree.py',
})
_VERSION = re.compile(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z._-]+)?')
_DIGEST = re.compile(r'[0-9a-f]{64}')


def native_metadata(version: str) -> dict:
    """Return release-independent format identity with exact version provenance."""
    if not isinstance(version, str) or _VERSION.fullmatch(version) is None:
        raise ValueError('Invalid native project VERSION: ' + repr(version))
    return {'schema_version': SCHEMA_VERSION, 'source_adapter': ADAPTER_FAMILY,
            'source_version': version, 'base_commit': BASE_COMMIT}


def _unique_json_object(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate native ownership record key: ' + repr(key))
        result[key] = value
    return result


def read_record(root: Path) -> dict:
    path = root / RECORD_NAME
    if path.is_symlink():
        raise ValueError('Native ownership record is a symlink.')
    record = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_json_object)
    if not isinstance(record, dict):
        raise ValueError('Native ownership record must be an object.')
    return record


def verify_native_workspace(root: Path, *, allow_legacy: bool = False) -> dict:
    """Verify all owned source bytes; optionally permit old records for migration.

    allow_legacy is used only before the assembler upgrades an intact existing
    workspace. It does not permit an unknown family, baseline or schema, and
    does not skip the old file hashes. The CLI always uses the current contract.
    """
    if root.is_symlink():
        raise ValueError('Native workspace root is a symlink.')
    root = root.resolve()
    record = read_record(root)
    schema = record.get('schema_version')
    if type(schema) is not int or schema != SCHEMA_VERSION:
        raise ValueError(f'Unsupported native source schema {schema!r}; expected {SCHEMA_VERSION}.')
    family = record.get('source_adapter')
    legacy = isinstance(family, str) and family in LEGACY_ADAPTERS
    if family != ADAPTER_FAMILY and not (allow_legacy and legacy):
        raise ValueError(f'Unsupported native source family {family!r}; expected {ADAPTER_FAMILY!r}. '
                         'Run the outer ONE-CLICK-BUILD.cmd to reassemble maintained source.')
    if record.get('base_commit') != BASE_COMMIT:
        raise ValueError('Native source has the wrong Rocket-R baseline: ' + repr(record.get('base_commit')))
    inventory = record.get('files')
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError('Native source inventory must be a nonempty object.')
    required = {'VERSION'} if legacy else REQUIRED_CURRENT_FILES
    missing = sorted(required - inventory.keys())
    if missing:
        raise ValueError('Native source inventory omits required files: ' + ', '.join(missing))
    aliases = set()
    for name, digest in inventory.items():
        if not isinstance(name, str) or not name:
            raise ValueError('Invalid native source manifest path.')
        rel = PurePosixPath(name)
        if (rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name
                or name != rel.as_posix() or any(part.endswith((' ', '.')) for part in rel.parts)
                or any(ord(c) < 32 for c in name)):
            raise ValueError('Unsafe native source manifest path: ' + repr(name))
        alias = name.casefold()
        if alias in aliases:
            raise ValueError('Duplicate case-insensitive native source path: ' + name)
        aliases.add(alias)
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
            raise ValueError('Invalid native source SHA-256 for: ' + name)
        path = root.joinpath(*rel.parts)
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Native source escapes its workspace: ' + name)
        if not path.is_file():
            raise ValueError('Missing native source: ' + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Native maintained source has local changes: ' + name +
                             '. Save those changes in the outer source before reassembling.')
    version = (root/'VERSION').read_text(encoding='utf-8').strip()
    native_metadata(version)  # Validate the actual file, not only JSON provenance.
    if not legacy and record.get('source_version') != version:
        raise ValueError(f'Native source version mismatch: record {record.get("source_version")!r}, '
                         f'VERSION file {version!r}.')
    return {'status': 'PASS', 'source_files': len(inventory), 'schema_version': schema,
            'source_adapter': family, 'source_version': version,
            'legacy_migration': legacy, 'game_boot_verified': False}
