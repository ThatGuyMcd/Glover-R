#!/usr/bin/env python3
"""Source/package integrity, not a statement of game readiness."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'build', 'dist', 'extern', '.git', '__pycache__', 'generated',
            'RecompiledFuncs', 'RecompiledPatches', 'RecompiledRSP',
            '.vs', '.vscode', '.idea', 'glover-r-data', 'logs', 'verification', 'reports'}
FORBIDDEN = {'.z64', '.n64', '.v64', '.rom', '.elf', '.jks', '.keystore', '.pyc'}

def source_files(root: Path):
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if any(part in EXCLUDED for part in relative.parts): continue
        # Local logs and historical verification data stay outside Git and the
        # public source manifest. They are not build inputs.
        if path.suffix.lower() in {'.log', '.dmp', '.pyc'}: continue
        if path.is_symlink(): raise ValueError(f'Source symlink not allowed: {relative}')
        if path.is_file() and path.name != 'SOURCE-MANIFEST.json': yield path

def check(root: Path, verify_manifest: bool = True) -> dict:
    needed = ['ONE-CLICK-BUILD.cmd', 'scripts/OneClickBuild.ps1', 'scripts/native_build.py', 'scripts/preflight.py', 'native/CMakeLists.txt',
              'config/glover.us.json', 'VERSION', 'native/src/game_registration.cpp',
              'config/sdk-aliases.json', 'scripts/glover/sdk_aliases.py',
              'scripts/glover/native_elf.py', 'scripts/glover/runtime_functions.py',
              'runtime-recomp/glover.us.cpu-classification.json',
              'runtime-recomp/glover.us.recomp-policy.json']
    for name in needed:
        if not (root/name).is_file(): raise ValueError(f'Missing source file: {name}')
    files = list(source_files(root))
    for path in files:
        if path.suffix.lower() in FORBIDDEN: raise ValueError(f'Private/generated file in source: {path.name}')
        if path.suffix == '.py': ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        if path.suffix == '.json': json.loads(path.read_text(encoding='utf-8'))
    manifest_path = root/'SOURCE-MANIFEST.json'
    if verify_manifest and manifest_path.exists():
        expected = json.loads(manifest_path.read_text(encoding='utf-8'))['sha256']
        actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        if actual != expected:
            changed = sorted(k for k in expected.keys() | actual.keys() if expected.get(k) != actual.get(k))
            raise ValueError('Source manifest differs: '+', '.join(changed[:15])+'. For intentional source edits, regenerate the manifest with --write-manifest.')
    return {'source_integrity': 'PASS', 'source_file_count': len(files),
            'manifest_checked': verify_manifest and manifest_path.exists(),
            'version': (root/'VERSION').read_text(encoding='utf-8').strip()}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--write-manifest', action='store_true', help='Developer action after intentional source edits.')
    args = parser.parse_args()
    try:
        if args.write_manifest:
            files = list(source_files(args.root))
            data = {'schema_version': 1, 'sha256': {p.relative_to(args.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
            (args.root/'SOURCE-MANIFEST.json').write_bytes((json.dumps(data, indent=2)+'\n').encode('utf-8'))
        print(json.dumps(check(args.root), indent=2))
        return 0
    except (ValueError, OSError, SyntaxError) as error:
        print(f'Source check failed: {error}', file=sys.stderr); return 1
if __name__ == '__main__': raise SystemExit(main())
