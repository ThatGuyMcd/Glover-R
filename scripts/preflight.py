#!/usr/bin/env python3
"""Check maintained source, regression tests and the supported ROM before building."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import platform
import sys
from glover.bootstrap import decode_bootstrap
from glover.diagnostics import diagnostic_zip
from glover.lock import build_lock
from glover.platforms import select
from glover.process_log import run_streamed
from glover.rom import (atomic_json, identity_dict, inspect_file, load_profile,
                        write_private_copy)
from self_check import check

ROOT = Path(__file__).resolve().parents[1]


def owned_directory(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise RuntimeError('Preflight output escapes the project: ' + relative)
    return path


def prepare_rom(root: Path, source: Path, profile: dict) -> dict:
    private = owned_directory(root, 'build/private')
    reports = owned_directory(root, 'build/reports')
    canonical, identity = inspect_file(source, profile)
    bootstrap = decode_bootstrap(canonical, profile)
    write_private_copy(source, private / 'glover.us.z64', canonical)
    if hashlib.sha256(source.read_bytes()).hexdigest() != identity.source_sha256:
        raise RuntimeError('The selected ROM changed during preflight.')
    record = identity_dict(identity)
    atomic_json(private / 'glover.us.identity.json', record)
    atomic_json(reports / 'rom-identity.json', record)
    atomic_json(reports / 'bootstrap.json', bootstrap)
    return {'rom_source_unchanged': True,
            'source_byte_order': identity.source_byte_order,
            'canonical_sha256': identity.canonical_sha256,
            'bootstrap_checked': True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rom', type=Path)
    parser.add_argument('--platforms', default='1,2')
    args = parser.parse_args()
    root = ROOT
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    record = {'schema_version': 1, 'timestamp_utc': stamp, 'preflight': 'FAILED',
              'game_booted': False}
    code = 1
    try:
        build = owned_directory(root, 'build')
        owned_directory(root, 'dist')
        reports = owned_directory(root, 'build/reports')
        with build_lock(build / '.build.lock'):
            if reports.exists() and any(reports.iterdir()):
                history = owned_directory(root, 'build/history')
                previous = owned_directory(root, 'build/history/reports-before-' + stamp)
                history.mkdir(parents=True, exist_ok=True)
                reports.rename(previous)
            reports.mkdir(parents=True, exist_ok=True)
            record['selected_platforms'] = select(args.platforms)
            atomic_json(reports / 'source-check.json', check(root))
            atomic_json(reports / 'environment.json',
                        {'python': sys.version, 'os': platform.system(),
                         'machine': platform.machine(),
                         'selected_platforms': record['selected_platforms']})
            print('Checking source and ROM-free regression tests.', flush=True)
            suite_code = run_streamed(
                [sys.executable, '-B', '-m', 'unittest', 'discover',
                 '-s', str(root / 'tests'), '-p', 'test_*.py'], root,
                root / 'build/logs' / ('preflight-tests-' + stamp + '.log'))
            if suite_code:
                code = suite_code
                raise RuntimeError(f'Preflight regression tests failed (exit {code}).')
            profile = load_profile(root / 'config/glover.us.json')
            source = args.rom or (Path(os.environ['GLOVER_ROM'])
                                if os.environ.get('GLOVER_ROM')
                                else root / 'build/private/glover.us.z64')
            record.update(prepare_rom(root, source, profile))
            record['preflight'] = 'PASS'
            code = 0
            print('Source, tests, USA ROM and startup checks passed.', flush=True)
    except KeyboardInterrupt:
        record['preflight'] = 'INTERRUPTED'
        record['error'] = 'Interrupted by user.'
        code = 130
    except Exception as error:
        record['error'] = f'{type(error).__name__}: {error}'
        print('PREFLIGHT STOPPED: ' + record['error'], flush=True)
    finally:
        record['exit_code'] = code
        try:
            reports = owned_directory(root, 'build/reports')
            owned_directory(root, 'dist')
            atomic_json(reports / 'preflight-status.json', record)
            bundle = diagnostic_zip(root, root / 'dist' /
                                    ('Glover-R-preflight-diagnostics-' + stamp + '.zip'))
            print('Diagnostic ZIP: ' + bundle['archive'], flush=True)
        except Exception as error:
            print('Diagnostic collection failed: ' + str(error), file=sys.stderr)
            if code == 0:
                code = 1
    return code


if __name__ == '__main__':
    raise SystemExit(main())
