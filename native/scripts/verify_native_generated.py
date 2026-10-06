#!/usr/bin/env python3
"""Read-only verification of the exact CPU/RSP output from successful generators."""
from __future__ import annotations
import argparse
import hashlib
import json
from glover.overlay_validation import verify_overlay_identifiers
from pathlib import Path


def snapshot(folder: Path) -> dict[str,str]:
    if folder.is_symlink() or not folder.is_dir(): raise ValueError('Invalid generated source directory.')
    result={}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink(): raise ValueError('Generated output contains a symlink.')
        if path.is_file(): result[path.relative_to(folder).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def verify(root: Path) -> dict:
    record=json.loads((root/'generated/glover-codegen.json').read_text(encoding='utf-8'))
    if record.get('schema_version')!=1 or record.get('cpu_generation')!='PASS' or record.get('rsp_generation')!='PASS':
        raise ValueError('Missing successful CPU/RSP generation record. Run the outer builder.')
    for label,relative in (('cpu_files','runtime-recomp/RecompiledFuncs'),('rsp_files','runtime-recomp/RecompiledRSP')):
        expected=record[label];actual=snapshot(root/relative)
        if not expected or actual!=expected:
            changed=sorted(k for k in actual.keys()|expected.keys() if actual.get(k)!=expected.get(k))
            raise ValueError('Generated '+label+' changed: '+', '.join(changed[:20]))
    verify_overlay_identifiers(root/'runtime-recomp/RecompiledFuncs/recomp_overlays.inl')
    return {'generated_source':'PASS','cpu_files':len(record['cpu_files']),
            'rsp_files':len(record['rsp_files']),'gameplay_verified':False}


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True,type=Path)
    args=p.parse_args();print(json.dumps(verify(args.root),indent=2));return 0
if __name__=='__main__':
    try: raise SystemExit(main())
    except (OSError,ValueError,KeyError) as e: print('GENERATED SOURCE CHECK FAILED: '+str(e));raise SystemExit(1)
