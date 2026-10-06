#!/usr/bin/env python3
"""Collect text build/session logs; never includes ROMs, game code, saves or keys."""
from datetime import datetime,timezone
import os
from pathlib import Path
from glover.rom import atomic_bytes
from glover.diagnostics import diagnostic_zip
from native_build import copy_logs

ROOT=Path(__file__).resolve().parents[1]

def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    copy_logs(ROOT,ROOT/'build/native-src',stamp)
    config=Path(os.environ.get('APPDATA',str(Path.home()/'.config')))/('Glover-R' if os.name=='nt' else 'glover-r')
    # Only .log files, never saves or mod/profile data. Local paths may be in logs.
    if config.is_dir() and not config.is_symlink():
        for path in sorted(config.rglob('*.log')):
            if path.is_symlink() or not path.resolve().is_relative_to(config.resolve()): continue
            if path.stat().st_size>8*1024*1024: continue
            data=path.read_bytes();text=data.decode('utf-8-sig',errors='replace')
            name='session-'+str(path.relative_to(config)).replace('\\','_').replace('/','_')
            atomic_bytes(ROOT/'build/logs'/name,text.encode())
    out=ROOT/'dist'/f'Glover-R-native-diagnostics-{stamp}.zip'
    report=diagnostic_zip(ROOT,out)
    print('Diagnostic ZIP: '+report['archive']);print('Review local paths in the logs before sharing.');return 0
if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as e: print('DIAGNOSTIC COLLECTION FAILED: '+str(e));raise SystemExit(1)
