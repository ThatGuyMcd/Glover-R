#!/usr/bin/env python3
"""Generate native game source from checked Glover inputs, without post-processing."""
from pathlib import Path
import argparse
from glover.native_generation import generate

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime-root',type=Path,required=True)
    p.add_argument('--n64recomp',type=Path,required=True)
    p.add_argument('--rsprecomp',type=Path,required=True)
    a=p.parse_args();generate(a.runtime_root,a.n64recomp,a.rsprecomp);return 0
if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as e: print('GLOVER GENERATION STOPPED: '+str(e));raise SystemExit(1)
