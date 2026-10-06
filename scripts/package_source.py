#!/usr/bin/env python3
"""Package maintained source and approved UI assets, excluding private outputs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from self_check import check, source_files

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN={'.z64','.n64','.v64','.rom','.elf','.o','.obj','.a','.lib','.exe','.dll',
           '.so','.apk','.appimage','.jks','.keystore','.pem','.key','.ttf','.otf','.woff','.woff2'}
MAGICS=(bytes.fromhex('80371240'),bytes.fromhex('37804012'),bytes.fromhex('40123780'),b'\x7fELF')

# These are the supplied launcher artwork and independently licensed fonts,
# not extracted game assets. Other binary source files remain rejected.
UI_ASSETS={
    'native/src/UI/Glover-R-green-full-resolution.png': b'\x89PNG\r\n\x1a\n',
    'native/src/UI/Glover-R-green-512x512.png': b'\x89PNG\r\n\x1a\n',
    'native/src/UI/Glover-R-green.ico': b'\x00\x00\x01\x00',
    'native/src/UI/fonts/Bungee-Regular.ttf': b'\x00\x01\x00\x00',
    'native/src/UI/fonts/Selawik-Regular.ttf': b'\x00\x01\x00\x00',
    'native/src/UI/fonts/Selawik-Semibold.ttf': b'\x00\x01\x00\x00',
}

def package(root:Path,output:Path)->dict:
    check(root)
    manifest=root/'SOURCE-MANIFEST.json'
    if not manifest.is_file():raise ValueError('Create SOURCE-MANIFEST.json with self_check.py --write-manifest first.')
    files=list(source_files(root))+[manifest]
    entries=[]
    for path in files:
        relative=path.relative_to(root)
        name=relative.as_posix()
        if path.suffix.lower() in FORBIDDEN and name not in UI_ASSETS:
            raise ValueError(f'Forbidden source-package file: {relative}')
        data=path.read_bytes()
        if data.startswith(MAGICS):raise ValueError(f'Game/ELF binary found in source: {relative}')
        if name in UI_ASSETS:
            if not data.startswith(UI_ASSETS[name]):
                raise ValueError(f'Unexpected branding/font format: {relative}')
        else:
            data.decode('utf-8')
        entries.append((path,relative,data))
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.is_symlink():raise ValueError('Archive output must not be a symlink.')
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path,relative,data in entries:
            info=zipfile.ZipInfo('Glover-R/'+relative.as_posix(),date_time=(2026,9,30,0,0,0))
            info.create_system=3
            info.external_attr=((0o100755 if path.suffix=='.sh' else 0o100644)<<16)
            info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,data)
    # Verify every archive member against the actual source, not only ZIP CRCs.
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:raise ValueError('ZIP CRC validation failed.')
        for _,relative,data in entries:
            if archive.read('Glover-R/'+relative.as_posix())!=data:
                raise ValueError('Packaged source differs from verified input.')
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n',encoding='utf-8')
    return {'archive':str(output),'files':len(entries),'bytes':output.stat().st_size,'sha256':digest,
            'native_build_route_implemented':True,'game_boot_verified':False,'rom_or_game_assets_included':False,
            'branding_and_fonts_included':sorted(p.relative_to(root).as_posix() for p,_,_ in entries
                                                 if p.relative_to(root).as_posix() in UI_ASSETS)}

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    version=(ROOT/'VERSION').read_text().strip()
    output=args.output or ROOT/'dist'/f'Glover-R-{version}-source.zip'
    print(json.dumps(package(ROOT,output),indent=2));return 0
if __name__=='__main__':raise SystemExit(main())
