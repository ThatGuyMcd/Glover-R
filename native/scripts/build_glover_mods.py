"""Build the real included package and policy-derived hook protection table."""
from pathlib import Path
import argparse, json, re, subprocess, sys

def protection(root):
    policy=json.loads((root/'runtime-recomp/glover.us.recomp-policy.json').read_text())
    names={p['function'] for category in ('functionHooks','instructionPatches') for p in policy.get(category,[])}
    symbols=(root/'build/generated/dump.toml').read_text()
    functions={n:int(v,16) for n,v in re.findall(r'name = "(\w+)", vram = (0x[0-9A-Fa-f]+)',symbols)}
    missing=names-functions.keys()
    if missing: raise ValueError('Protected functions missing from current symbols: '+', '.join(sorted(missing)))
    header='// Generated from the checked Glover policy and current symbol dump.\n#pragma once\n#include <cstdint>\nnamespace rocket::generated {\ninline constexpr std::uint32_t kModProtectedFunctions[] = {\n'
    header+=''.join(f'0x{functions[n]:08X}U, // {n}\n' for n in sorted(names))+'};\n}\n'
    (root/'generated/mod_protection.generated.hpp').write_text(header,encoding='utf-8')

def main():
    p=argparse.ArgumentParser();p.add_argument('--tool',type=Path,required=True);p.add_argument('--wsl',action='store_true');a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    protection(root)
    cmd=[sys.executable,str(root/'scripts/build_mod.py'),str(root/'modding/examples/modern-camera'),
         '--tool',str(a.tool.resolve()),'--symbols',str(root/'build/generated/dump.toml'),
         '--data-symbols',str(root/'build/generated/data_dump.toml'),'--output',str(root/'build/mods')]
    if a.wsl:cmd.append('--wsl')
    subprocess.run(cmd,check=True)
if __name__=='__main__':main()
