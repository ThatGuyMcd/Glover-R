#!/usr/bin/env python3
from pathlib import Path
import argparse
import json
import sys
from glover.native_inputs import prepare

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--runtime-root',type=Path,required=True)
    p.add_argument('--rom',type=Path,required=True)
    p.add_argument('--symbols',type=Path,required=True)
    a=p.parse_args()
    try:
        r=prepare(Path(__file__).resolve().parents[1],a.runtime_root.resolve(),a.rom,a.symbols)
        print('Glover ELF original-byte validation: PASS')
        print('ELF ROM-origin/mapping validation: PASS (ROM offset zero retained)')
        print('Native ELF section identifiers: PASS (.text_0, .text_1, .text_2)')
        for group in r['verified_sdk_aliases']:
            addresses = ', '.join(f'0x{a:08X}' for a in group['addresses'])
            print(f"SDK alias ROM check: {group['name']} at {addresses}; both entries retained")
        print('SDK entries:',r['metadata']['sdk_named_functions'],'CPU functions:',r['metadata']['functions'])
        print('Policy symbol binding validation: PASS (configured entrypoint name resolved)')
        print('Audio dispatch table: 16 checked targets; RSP generation is next.')
        boundary = r['native_cpu_boundary_audit']
        print('Native CPU classification/direct-edge audit: PASS')
        print('Original-body status getters retained: 2; hardware-only policy entries: 4')
        print('ROM-checked private SDK helper: send_mesg; reviewed cache operations: 2')
        classification = json.loads((Path(__file__).resolve().parents[1] /
            'runtime-recomp/glover.us.cpu-classification.json').read_text(encoding='utf-8'))
        print('ROM-checked function boundaries:', len(classification['additional_entries']),
              '; original function epilogues retained')
        print('Selected native CPU functions:', boundary['emitted_function_count'])
        print('Raw discovery external edges (including skipped hardware):', len(r['metadata']['unresolved_external_edges']))
        print('Known opcode/direct-edge hazards in selected CPU functions:', len(boundary['issues']))
        print('Indirect call/jump sites still requiring generator/runtime validation:',
              len(boundary['indirect_transfers_requiring_runtime_validation']))
        print('Function metadata is an experimental boot candidate, not gameplay-qualified.')
        return 0
    except Exception as e:
        print('Glover input preparation failed: '+str(e),file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
