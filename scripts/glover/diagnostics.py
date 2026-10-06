"""Allowlisted diagnostic archive: never includes ROMs, ELF, game C or keys."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import zipfile

FORBIDDEN = {'.z64', '.n64', '.v64', '.rom', '.elf', '.o', '.obj', '.a', '.lib',
             '.exe', '.dll', '.so', '.apk', '.appimage', '.jks', '.keystore', '.pem', '.key'}
MAGICS = (b'\x80\x37\x12\x40', b'\x37\x80\x40\x12', b'\x40\x12\x37\x80')
REPORT_NAMES = {'rom-identity.json', 'bootstrap.json',
                'upstream-audit.json', 'preflight-status.json',
                
                'environment.json', 'source-check.json',
                'native-inputs.json','native-source.json','native-codegen.json','native-run-status.json',
                'native-sdk-symbols.txt', 'native-cpu-boundary.json', 'native-compilation.json'}

def diagnostic_zip(root: Path, output: Path) -> dict:
    build = root / 'build'
    candidates = []
    for name in sorted(REPORT_NAMES):
        path = build / 'reports' / name
        if path.is_file(): candidates.append(path)
    if (build / 'logs').is_dir():
        candidates.extend(sorted((build / 'logs').glob('*.log')))
    for path in (root / 'VERSION', root / 'config/glover.us.json'):
        if path.is_file(): candidates.append(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink(): raise RuntimeError('Diagnostic archive must not be a symlink.')
    inventory = []
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=8) as archive:
        for path in candidates:
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise RuntimeError(f'Refusing diagnostic symlink/outside file: {path}')
            if path.suffix.lower() in FORBIDDEN or path.stat().st_size > 10*1024*1024:
                raise RuntimeError(f'Refusing disallowed or oversized diagnostic file: {path.name}')
            data = path.read_bytes()
            if data.startswith(MAGICS) or data.startswith(b'\x7fELF'):
                raise RuntimeError('Binary game/ELF content detected in diagnostic allowlist.')
            try: data.decode('utf-8')
            except UnicodeDecodeError as error: raise RuntimeError('Non-text diagnostic file.') from error
            name = path.relative_to(root).as_posix()
            archive.writestr(name, data)
            inventory.append({'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        archive.writestr('DIAGNOSTIC-CONTENTS.json', json.dumps(inventory, indent=2)+'\n')
        archive.writestr('READ-ME.txt', 'Glover-R build diagnostics. Consult the per-run status records; build success is not gameplay verification.\n'
                        'Logs can contain your local folder paths and ROM filename; review before sharing.\n')
    return {'archive': str(output), 'file_count': len(inventory),
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
