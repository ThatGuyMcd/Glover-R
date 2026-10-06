"""Use the same SDK CLI shipped in the assembled native source and SDK ZIP."""
from pathlib import Path
import runpy
import sys

root=Path(__file__).resolve().parents[1]
script=root/'build/native-src/scripts/rocket_sdk.py'
if not script.is_file():
    raise SystemExit('Run ONE-CLICK-BUILD.cmd first to assemble the Glover SDK tools.')
sys.path.insert(0,str(script.parent))
runpy.run_path(str(script),run_name='__main__')
