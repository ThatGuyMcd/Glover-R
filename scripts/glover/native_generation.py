"""Run real N64Recomp/RSPRecomp processes; never repair emitted game source."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Callable
from .generated_guard import fingerprint_tree, assert_unchanged
from .rom import atomic_json

class GenerationError(RuntimeError):
    pass


def run_logged(command: list[str], cwd: Path, log: Path, callback: Callable[[str],None]=print) -> int:
    from .process_log import run_streamed
    return run_streamed(command, cwd, log, callback)


def clean_output(root: Path, relative: str) -> Path:
    if relative not in ('runtime-recomp/RecompiledFuncs','runtime-recomp/RecompiledRSP'):
        raise GenerationError('Refusing to clean an unrecognised generator output directory.')
    path=root/relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise GenerationError('Generator output resolves outside its workspace.')
    if path.exists():
        if any(p.is_symlink() for p in path.rglob('*')): raise GenerationError('Generator output contains a symlink.')
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def generate(root: Path, n64recomp: Path, rsprecomp: Path,
             runner: Callable = run_logged, callback: Callable[[str],None]=print) -> dict:
    root=root.resolve()
    for exe in (n64recomp,rsprecomp):
        if not exe.is_file(): raise GenerationError('Missing generator executable: '+str(exe))
    cpu_config=root/'build/generated/glover.us.toml'
    rsp_config=root/'build/generated/glover.rsp.toml'
    for path in (cpu_config,rsp_config,root/'generated/bootstrap.generated.hpp',root/'generated/rom_identity.generated.hpp'):
        if not path.is_file(): raise GenerationError('Missing Glover input: '+str(path))
    if not (root/'GLOVER-NATIVE-SOURCE.json').is_file(): raise GenerationError('Workspace is not an assembled Glover native tree.')
    work=cpu_config.parent;logs=root/'build/logs'
    status_path=root/'generated/glover-codegen.json'
    report={'schema_version':1,'timestamp_utc':datetime.now(timezone.utc).isoformat(),
            'context':'NOT_RUN','cpu_generation':'NOT_RUN','rsp_generation':'NOT_RUN',
            'native_compilation':'NOT_RUN','game_booted':False,
            'input_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (cpu_config,rsp_config)},
            'generator_sha256':{label:hashlib.sha256(p.read_bytes()).hexdigest()
                                for label,p in (('N64Recomp',n64recomp),('RSPRecomp',rsprecomp))}}
    atomic_json(status_path,report)
    try:
        for name in ('dump.toml','data_dump.toml'): (work/name).unlink(missing_ok=True)
        code=runner([str(n64recomp.resolve()),str(cpu_config),'--dump-context'],work,logs/'glover-context.log',callback)
        if code:
            report['context']='FAILED';raise GenerationError(f'N64Recomp context validation failed (exit {code}). See build/logs/glover-context.log.')
        if not (work/'dump.toml').is_file():
            report['context']='EMPTY';raise GenerationError('N64Recomp returned success without dump.toml.')
        report['context']='PASS';atomic_json(status_path,report)
        cpu=clean_output(root,'runtime-recomp/RecompiledFuncs')
        code=runner([str(n64recomp.resolve()),str(cpu_config)],work,logs/'glover-cpu-generation.log',callback)
        if code:
            report['cpu_generation']='FAILED';raise GenerationError(f'CPU generation failed (exit {code}). Generated C was NOT patched. See glover-cpu-generation.log.')
        if not (cpu/'recomp_overlays.inl').is_file() or not list(cpu.glob('*.c'))+list(cpu.glob('*.cpp')):
            report['cpu_generation']='EMPTY';raise GenerationError('CPU generator returned success without required game sources.')
        from .overlay_validation import verify_overlay_identifiers
        try:
            report['overlay_identifiers'] = verify_overlay_identifiers(cpu/'recomp_overlays.inl')
        except ValueError:
            report['cpu_generation'] = 'INVALID_OVERLAY_IDENTIFIERS'
            raise
        report['cpu_generation']='PASS';report['cpu_files']=fingerprint_tree(cpu)
        atomic_json(status_path,report)
        rsp=clean_output(root,'runtime-recomp/RecompiledRSP')
        code=runner([str(rsprecomp.resolve()),str(rsp_config)],work,logs/'glover-rsp-generation.log',callback)
        if code:
            report['rsp_generation']='FAILED';raise GenerationError(f'RSP audio generation failed (exit {code}). See glover-rsp-generation.log.')
        if not list(rsp.glob('*.cpp')):
            report['rsp_generation']='EMPTY';raise GenerationError('RSP generator returned success without C++ output.')
        report['rsp_generation']='PASS';report['rsp_files']=fingerprint_tree(rsp)
        assert_unchanged(cpu,report['cpu_files'])
        atomic_json(status_path,report)
        callback('Glover CPU and audio RSP generation passed. Native compilation and game boot are separate milestones.')
        return report
    except BaseException as error:
        report['error']=str(error);atomic_json(status_path,report);raise
