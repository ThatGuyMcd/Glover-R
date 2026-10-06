"""Read-only syntax guard for names emitted into recomp_overlays.inl.

This is deliberately not a C++ compiler or a generated-source repair. The
native builder separately compiles register_overlays.cpp before the full game.
"""
from pathlib import Path
import re


def verify_overlay_identifiers(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ValueError('Missing or symlinked generated overlay table.')
    text = path.read_text(encoding='utf-8-sig')
    arrays = re.findall(r'^\s*static\s+(?:FuncEntry|RelocEntry)\s+([^\s\[]+)\s*\[\s*\]', text, re.M)
    if not arrays:
        raise ValueError('Generated overlay table has no function/relocation arrays.')
    invalid = [name for name in arrays if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name)]
    if invalid:
        raise ValueError('Invalid generated overlay identifier(s): ' + ', '.join(invalid) +
                         '. Correct the ELF input names and regenerate; do not edit generated C/C++.')
    if len(arrays) != len(set(arrays)):
        raise ValueError('Duplicate generated overlay array names.')
    return {'status': 'PASS', 'arrays': len(arrays), 'generated_source_edited': False}
