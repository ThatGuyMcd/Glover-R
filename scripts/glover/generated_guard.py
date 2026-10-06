"""Read-only inventory and verification for disposable generator output."""
from __future__ import annotations
import hashlib
from pathlib import Path

class GeneratedChangedError(RuntimeError):
    pass

def fingerprint_tree(root: Path) -> dict[str, str]:
    if root.is_symlink():
        raise GeneratedChangedError("Generated-output directory must not be a symlink.")
    if not root.is_dir():
        raise GeneratedChangedError(f"Generated-output directory does not exist: {root}")
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise GeneratedChangedError(f"Symlink in generated output: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def assert_unchanged(root: Path, before: dict[str, str]) -> None:
    after = fingerprint_tree(root)
    if before != after:
        names = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        raise GeneratedChangedError("Generator output changed after generation: " + ', '.join(names[:20]))
