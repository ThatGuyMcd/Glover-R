"""Fetch pinned references into this project's build tree. Never modifies Rocket-R.

No upstream build scripts are executed, and no patches are applied here. Critical
blob IDs and every ordered dependency-patch hash are audited after checkout.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from typing import Callable

class UpstreamError(RuntimeError):
    pass

def git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()

def safe_relative(root: Path, name: str) -> Path:
    rel = PurePosixPath(name)
    if rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name:
        raise UpstreamError(f"Unsafe repository path: {name!r}")
    target = root.joinpath(*rel.parts)
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise UpstreamError(f"Repository path escapes checkout: {name!r}")
    return target

def audit_reference(root: Path, spec: dict) -> dict:
    checked = {}
    for name, expected in spec['critical_blobs'].items():
        data = safe_relative(root, name).read_bytes()
        actual = git_blob_id(data)
        if actual != expected and b'\r\n' in data:
            # Honour a checkout's declared CRLF working-tree conversion.
            actual = git_blob_id(data.replace(b'\r\n', b'\n'))
        if actual != expected:
            raise UpstreamError(f"Pinned source differs: {name}; expected {expected}, got {actual}.")
        checked[name] = actual
    patch_rows = []
    manifest_path = root / 'patches/manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest.get('schemaVersion') != 1:
            raise UpstreamError('Unsupported upstream patch manifest.')
        seen = set()
        for dep in manifest['dependencies']:
            for index, patch in enumerate(dep['patches']):
                if patch['path'] in seen:
                    raise UpstreamError('Duplicate dependency patch path.')
                seen.add(patch['path'])
                actual = hashlib.sha256(safe_relative(root, patch['path']).read_bytes()).hexdigest()
                if actual != patch['sha256']:
                    raise UpstreamError(f"Dependency patch hash mismatch: {patch['path']}")
                patch_rows.append({'dependency': dep['name'], 'order': index,
                                   'path': patch['path'], 'sha256': actual})
    return {'critical_blobs': checked, 'ordered_patches': patch_rows,
            'patches_applied': False, 'upstream_build_invoked': False}

def fetch_reference(project: Path, spec: dict, log: Callable[[str], None]) -> dict:
    git = shutil.which('git')
    if git is None:
        raise UpstreamError('Git is required for --fetch-upstreams. The local ROM analysis does not need Git.')
    if not re.fullmatch('[0-9a-f]{40}', spec['commit']):
        raise UpstreamError('Upstream must be locked to a full commit SHA.')
    if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git', spec['repository']):
        raise UpstreamError('Only explicit HTTPS GitHub repository URLs are supported.')
    path = safe_relative(project, spec['destination'])
    owned_parent = (project / 'build/upstream').resolve()
    if not path.resolve().is_relative_to(owned_parent):
        raise UpstreamError('Reference destination is not inside build/upstream.')
    def run(*args: str) -> str:
        command = [git, '-c', 'core.autocrlf=false', '-c', 'core.hooksPath=/dev/null', *args]
        if args and args[0] in ('fetch', 'checkout'):
            from .process_log import run_streamed
            code = run_streamed(command, path, None, log, label='Git reference '+args[0], timeout=240)
            if code:
                raise UpstreamError(f"Git exited {code}: {' '.join(args[:3])}")
            return ''
        proc = subprocess.run(command, cwd=str(path), text=True, encoding='utf-8', errors='replace',
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240)
        if proc.stdout.strip(): log(proc.stdout.strip())
        if proc.returncode:
            raise UpstreamError(f"Git exited {proc.returncode}: {' '.join(args[:3])}")
        return proc.stdout.strip()
    new = not path.exists()
    if new:
        path.mkdir(parents=True)
        run('init')
        run('remote', 'add', 'origin', spec['repository'])
    elif (path / '.git').is_symlink() or not (path / '.git').is_dir():
        raise UpstreamError(f"Refusing to use an existing non-checkout directory: {path}")
    origin = run('remote', 'get-url', 'origin')
    if origin != spec['repository']:
        raise UpstreamError('Existing reference checkout has a different origin; nothing was reset.')
    status = run('status', '--porcelain', '--untracked-files=all')
    if status:
        raise UpstreamError('Existing reference checkout has edits or untracked files; nothing was overwritten.')
    # A failed initial fetch leaves a valid empty repo, so an absent HEAD is
    # recoverable. Never reset or clean a populated user-edited reference.
    head = subprocess.run([git, '-C', str(path), 'rev-parse', '--verify', 'HEAD'],
                          capture_output=True, text=True, timeout=20)
    if head.returncode != 0 or head.stdout.strip() != spec['commit']:
        run('fetch', '--no-tags', '--depth=1', 'origin', spec['commit'])
        run('checkout', '--detach', spec['commit'])
    resolved = run('rev-parse', 'HEAD')
    if resolved != spec['commit']:
        raise UpstreamError('Resolved upstream commit does not match the lock.')
    result = audit_reference(path, spec)
    return {'repository': spec['repository'], 'commit': resolved,
            'destination': spec['destination'], **result}
