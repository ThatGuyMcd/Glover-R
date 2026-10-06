#!/usr/bin/env python3
"""Assemble and run the pinned Rocket-R-derived native Glover build workflow.

A successful build is not a verified game boot. Failure logs and milestone
records are collected automatically; no missing game routine is replaced by
an empty function to force a link.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from glover.rom import atomic_json, atomic_bytes
from glover.lock import build_lock
from glover.platforms import select
from glover.upstream import fetch_reference
from glover.native_source import assemble
from glover.native_generation import run_logged
from glover.process_log import run_streamed, decode_log_bytes, child_environment
from glover.generated_guard import assert_unchanged
from glover.diagnostics import diagnostic_zip

ROOT=Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def validate_workspace(native: Path) -> None:
    owned=native.resolve()
    for name in ('build','dist','extern','generated','runtime-recomp',
                 'build/private','build/windows','build/tools','build/logs',
                 'extern/rt64','extern/n64-modern-runtime','extern/n64-modern-runtime/N64Recomp',
                 'extern/sdl2','extern/n64sym'):
        path=native/name
        if path.is_symlink() or not path.resolve().is_relative_to(owned):
            raise RuntimeError('Native workspace path escapes ownership: '+name)


def verify_assembled_source(native: Path, log: Path) -> int:
    # Execute the same file called by inner Windows stage 1 and the Linux
    # helper. Do not substitute a mock/independent manifest reader here.
    return run_logged([sys.executable, '-B', str(native/'scripts/verify_native_tree.py'),
                       '--root', str(native)], native, log)


def copy_logs(root: Path, native: Path, stamp: str) -> None:
    logdir=root/'build/logs';logdir.mkdir(parents=True,exist_ok=True)
    source=native/'build/logs'
    if source.is_dir() and source.resolve().is_relative_to(native.resolve()):
        for path in source.glob('*.log'):
            if path.is_symlink() or not path.is_file(): continue
            # Capture tail on unusually large compiler logs; diagnostic ZIPs
            # stay text-only and usable. Preserve complete logs in native-src.
            text=decode_log_bytes(path.read_bytes())
            if len(text)>4*1024*1024:
                text='[Earlier log omitted; full log remains in build/native-src/build/logs]\n'+text[-4*1024*1024:]
            text=text.replace('\r\n','\n').replace('\r','\n')
            atomic_bytes(logdir/('native-'+path.name),text.encode('utf-8'))
    for source_name,dest_name in (
        ('generated/glover-codegen.json','native-codegen.json'),
        ('build/generated/glover-inputs-report.json','native-inputs.json'),
        ('generated/glover-native-build.json','native-compilation.json')):
        path=native/source_name
        if path.is_file() and not path.is_symlink():
            atomic_json(root/'build/reports'/dest_name,json.loads(path.read_text(encoding='utf-8')))
    # A code-generation snapshot cannot know what the later compiler did.
    # Point the collected copy to the separate per-stage native record instead
    # of leaving its old NOT_RUN value as a misleading final build status.
    stage_file = native/'generated/glover-native-build.json'
    codegen_file = root/'build/reports/native-codegen.json'
    if stage_file.is_file() and not stage_file.is_symlink() and codegen_file.is_file():
        stage_data = json.loads(stage_file.read_text(encoding='utf-8'))
        if stage_data.get('stages'):
            codegen = json.loads(codegen_file.read_text(encoding='utf-8'))
            codegen['native_compilation'] = 'SEE_NATIVE_COMPILATION_REPORT'
            codegen['native_compilation_report'] = 'native-compilation.json'
            codegen['native_build_stages'] = stage_data['stages']
            atomic_json(codegen_file, codegen)
    symbols=native/'build/private/glover.sdk-symbols.txt'
    if symbols.is_file() and not symbols.is_symlink():
        # Symbol names/addresses are diagnostic metadata, not game bytes.
        data=symbols.read_bytes()
        if len(data)<=4*1024*1024:
            data.decode('utf-8');atomic_bytes(root/'build/reports/native-sdk-symbols.txt',data)


def expected_packages(version: str, targets: list[str], no_package: bool) -> list[str]:
    result=[]
    if 'Windows-x64' in targets and not no_package: result.append(f'Glover-R-{version}-Windows-x64.zip')
    if 'Linux-x86_64' in targets: result.append(f'Glover-R-{version}-Linux-x86_64.AppImage')
    if 'Linux-aarch64' in targets: result.append(f'Glover-R-{version}-Linux-aarch64.AppImage')
    if 'Android-arm64' in targets: result.append(f'Glover-R-{version}-Android-arm64-v8a.apk')
    return result


def collect_packages(root: Path,native: Path,targets: list[str],no_package: bool) -> dict:
    version=(root/'VERSION').read_text().strip();destination=root/'dist';destination.mkdir(exist_ok=True)
    dist=native/'dist'
    for name in expected_packages(version,targets,no_package):
        p=dist/name
        if not p.is_file() or p.is_symlink() or p.stat().st_size==0: raise RuntimeError('Expected native package was not produced: '+name)
    if 'Windows-x64' in targets:
        exes=list((native/'build/windows').rglob('Glover-R.exe'))
        if not exes: raise RuntimeError('Windows builder returned success without Glover-R.exe.')
    outputs=[]
    for p in sorted(dist.glob('Glover-R-'+version+'-*')):
        if not p.is_file() or p.is_symlink(): continue
        if p.suffix.lower() not in {'.zip','.gz','.appimage','.apk'}: continue
        out=destination/p.name
        if out.is_symlink(): raise RuntimeError('Package output is a symlink: '+str(out))
        shutil.copy2(p,out)
        outputs.append({'file':out.name,'bytes':out.stat().st_size,'sha256':sha256(out)})
    if not outputs and not no_package: raise RuntimeError('No native packages were collected.')
    info={'schema_version':1,'version':version,'source_base':'133070e264350f17257a520ae0de4da98ce445b0',
          'native_build':'PASS','gameplay_verified':False,'artifacts':outputs}
    atomic_json(destination/f'Glover-R-{version}-build-info.json',info)
    atomic_bytes(destination/f'Glover-R-{version}-SHA256SUMS.txt',
        ''.join(o['sha256']+'  '+o['file']+'\n' for o in outputs).encode())
    return info


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--rom',type=Path)
    p.add_argument('--platforms',default='1,2')
    p.add_argument('--prepare-only',action='store_true',help='Fetch/assemble source only; do not claim a game build.')
    p.add_argument('--no-package',action='store_true')
    p.add_argument('--no-launch',action='store_true')
    p.add_argument('--repair-dependencies',action='store_true')
    args=p.parse_args()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    root=ROOT;native=root/'build/native-src'
    if any((root/n).is_symlink() for n in ('build','dist')):
        print('Refusing symlinked build/dist folders.');return 1
    report={'schema_version':1,'timestamp_utc':stamp,'preflight':'NOT_RUN','source_assembly':'NOT_RUN',
            'source_verification':'NOT_RUN','native_build':'NOT_RUN',
            'game_booted':False,'selected_platforms':[]}
    code=1
    prepare_path=root/'build/logs'/f'native-prepare-{stamp}.log'
    prepare_path.parent.mkdir(parents=True,exist_ok=True)
    prepare_log=prepare_path.open('w',encoding='utf-8')
    def log_prepare(message):
        print(message,flush=True);prepare_log.write(message+'\n');prepare_log.flush()
    try:
        targets=select(args.platforms);report['selected_platforms']=targets
        # Preflight acquires its own lock. The native lock is held only after it
        # returns; the two commands never deadlock on a nested lock acquisition.
        command=[sys.executable,'-B',str(root/'scripts/preflight.py'),'--platforms',','.join(targets)]
        if args.rom: command+=['--rom',str(args.rom)]
        report['preflight']='RUNNING'
        code=run_logged(command,root,root/'build/logs'/f'native-preflight-{stamp}.log')
        report['preflight_exit_code']=code
        if code:
            report['preflight']='FAILED'
            raise RuntimeError(f'Pre-native preflight checks failed (exit {code}).')
        report['preflight']='PASS'
        with build_lock(root/'build/.build.lock'):
            lock=json.loads((root/'config/upstreams.lock.json').read_text())
            print('Fetching the pinned Rocket-R source into this Glover project only.',flush=True)
            upstream=fetch_reference(root,lock['rocket_base'],log_prepare)
            atomic_json(root/'build/reports/upstream-audit.json',{'rocket_base':upstream})
            reference=root/lock['rocket_base']['destination']
            report['source_assembly']='RUNNING'
            log_prepare('Assembling the checked Rocket-R source into the Glover native workspace.')
            result=assemble(root,reference,native)
            atomic_json(root/'build/reports/native-source.json',result)
            report['source_assembly']='PASS'
            validate_workspace(native)
            report['source_verification']='RUNNING'
            verification_log=root/'build/logs'/f'native-source-check-{stamp}.log'
            verification_exit=verify_assembled_source(native, verification_log)
            report['source_verification_exit_code']=verification_exit
            if verification_exit:
                report['source_verification']='FAILED'
                raise RuntimeError(f'Assembled native source verification failed (exit {verification_exit}). '
                                   f'See {verification_log}')
            report['source_verification']='PASS'
            log_prepare('Native source assembly PASS. Assembled verifier PASS.')
            if args.prepare_only:
                report['native_build']='NOT_REQUESTED';code=0
                print('Native source prepared. No generator, native compiler or game was executed.')
            else:
                powershell=shutil.which('powershell.exe')
                if os.name!='nt' or not powershell:
                    raise RuntimeError('The full one-click workflow runs in Windows PowerShell 5.1. '
                                       'Use ONE-CLICK-BUILD.cmd on Windows; --prepare-only is available on other hosts.')
                # Move aside old outputs so they cannot be mistaken for results
                # from this run. Do not remove caches, saves or signing keys.
                old_dist=native/'dist'
                if old_dist.is_symlink(): raise RuntimeError('Native dist is a symlink.')
                if old_dist.exists() and any(old_dist.iterdir()):
                    previous=native/'build/previous-packages'/stamp
                    previous.parent.mkdir(parents=True,exist_ok=True)
                    old_dist.rename(previous)
                old_dist.mkdir(exist_ok=True)
                env=child_environment()
                env['GLOVER_PROJECT_ROOT']=str(root)
                env['GLOVER_CANONICAL_ROM']=str(root/'build/private/glover.us.z64')
                command=[powershell,'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',
                         str(native/'scripts/OneClickBuild.ps1'),'-Platforms',','.join(targets)]
                if args.no_launch: command.append('-NoLaunch')
                if args.no_package: command.append('-NoPackage')
                if args.repair_dependencies: command.append('-RepairDependencies')
                print('Starting Glover OS scan, CPU/RSP generation and selected native builds.',flush=True)
                report['native_started']=True
                report['native_build']='RUNNING'
                atomic_json(native/'generated/glover-codegen.json', {'schema_version':1, 'attempt':stamp,
                    'context':'NOT_RUN', 'cpu_generation':'NOT_RUN', 'rsp_generation':'NOT_RUN', 'game_booted':False})
                (native/'build/generated/glover-inputs-report.json').unlink(missing_ok=True)
                for old in ('native-inputs.json','native-codegen.json','native-sdk-symbols.txt'):
                    (root/'build/reports'/old).unlink(missing_ok=True)
                outer_log=root/'build/logs'/f'native-build-{stamp}.log'
                # One streaming supervisor for the whole inner build. Python
                # output is unbuffered at every nesting level, not just here.
                atomic_json(native/'generated/glover-native-build.json',
                    {'schema_version':1, 'attempt':stamp, 'game_booted':False, 'stages':{}})
                code=run_streamed(command,native,outer_log,env=env,label='Glover native builder')
                report['native_exit_code']=code
                if code:
                    report['native_build']='ACTION_REQUIRED' if code==20 else 'FAILED'
                    raise RuntimeError(f'Native builder stopped with exit {code}. See build/logs and the diagnostic ZIP.')
                fingerprint=json.loads((native/'generated/glover-codegen.json').read_text())
                if fingerprint.get('cpu_generation')!='PASS' or fingerprint.get('rsp_generation')!='PASS':
                    raise RuntimeError('Native build returned without successful CPU/RSP generation records.')
                for relative,key in (('RecompiledFuncs','cpu_files'),('RecompiledRSP','rsp_files')):
                    assert_unchanged(native/'runtime-recomp'/relative,fingerprint[key])
                report['artifacts']=collect_packages(root,native,targets,args.no_package)
                report['native_build']='PASS';report['generated_sources_unchanged']=True
                code=0
                print('Native build completed. Game boot and gameplay still require testing.',flush=True)
    except KeyboardInterrupt:
        if report['preflight']=='RUNNING': report['preflight']='INTERRUPTED'
        if report['source_assembly']=='RUNNING': report['source_assembly']='INTERRUPTED'
        if report['source_verification']=='RUNNING': report['source_verification']='INTERRUPTED'
        if report['native_build']=='RUNNING': report['native_build']='INTERRUPTED'
        code=130;report['error']='Interrupted by user.';print(report['error'])
    except Exception as e:
        if report['preflight']=='RUNNING': report['preflight']='FAILED'
        if report['source_assembly']=='RUNNING': report['source_assembly']='FAILED'
        if report['source_verification']=='RUNNING': report['source_verification']='FAILED'
        if report['native_build']=='RUNNING': report['native_build']='FAILED'
        if code==0: code=1
        report['error']=f'{type(e).__name__}: {e}'
        log_prepare('GLOVER BUILD STOPPED: '+report['error'])
    finally:
        prepare_log.close()
        report['exit_code']=code
        try:
            if report.get('native_started'): copy_logs(root,native,stamp)
            atomic_json(root/'build/reports/native-run-status.json',report)
            bundle=diagnostic_zip(root,root/'dist'/f'Glover-R-native-diagnostics-{stamp}.zip')
            print('Diagnostic ZIP: '+bundle['archive'],flush=True)
        except Exception as e:
            print('Diagnostic collection failed: '+str(e),file=sys.stderr)
            if code==0: code=1
    return code

if __name__=='__main__': raise SystemExit(main())
