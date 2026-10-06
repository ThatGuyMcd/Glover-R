"""Live, UTF-8 build output with elapsed-time heartbeats and real exit codes.

This is process supervision, not a success/progress estimator. A heartbeat
means the child is alive (possibly waiting for input), not that work completed.
No shell command strings, generated-source rewrites or exit-code suppression.
"""
from __future__ import annotations
import codecs
from collections import deque
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, Mapping


def print_console(text: str) -> None:
    """Keep legacy redirected Windows consoles from aborting a real build.

    UTF-8 log files retain the original text. Only characters unavailable in
    the console's encoding are escaped for display.
    """
    encoding = getattr(sys.stdout, 'encoding', None)
    if encoding:
        text = text.encode(encoding, errors='backslashreplace').decode(encoding)
    print(text, flush=True)


def child_environment(overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if overrides is not None:
        env.update(overrides)
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8:backslashreplace'
    return env


def decode_log_bytes(data: bytes) -> str:
    """Read Windows PS5.1 UTF-16 or UTF-8 logs before diagnostic copying.

    Old diagnostic copies incorrectly UTF-8-decoded a UTF-16 file. Their BOM
    became two replacement characters; recognise that *specific* legacy form
    without interpreting arbitrary binary content as text.
    """
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16', errors='replace')
    if data.startswith(b'\xef\xbf\xbd\xef\xbf\xbd'):
        tail = data[6:]
        if len(tail) >= 20 and tail[1:200:2].count(0) > len(tail[1:200:2]) * 0.7:
            return tail.decode('utf-16-le', errors='replace')
    if len(data) >= 20 and data[1:200:2].count(0) > len(data[1:200:2]) * 0.7:
        return data.decode('utf-16-le', errors='replace')
    return data.decode('utf-8-sig', errors='replace')


def _stop_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=15, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name != 'nt':
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.kill()
        proc.wait(timeout=5)


def run_streamed(command: list[str], cwd: Path, log: Path | None,
                 callback: Callable[[str], None] = print, *,
                 env: Mapping[str, str] | None = None, label: str | None = None,
                 heartbeat_seconds: float = 15.0, timeout: float | None = None,
                 echo_metadata: bool = True) -> int:
    """Stream output as it arrives, including partial prompts/carriage returns.

    stdin is inherited, so the existing interactive setup prompts still work.
    The reader thread only drains bytes. Callbacks and file writes happen on
    the calling thread; no PowerShell callback/runspace is used.
    """
    if not command or not all(isinstance(arg, str) for arg in command):
        raise ValueError('Process command must be a nonempty list of strings.')
    if heartbeat_seconds <= 0 or (timeout is not None and timeout <= 0):
        raise ValueError('Process heartbeat and timeout must be positive.')
    label = label or Path(command[0]).name
    stream = None
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        if log.is_symlink():
            raise ValueError('Refusing symlinked process log.')
        stream = log.open('w', encoding='utf-8', newline='\n')
    started = time.monotonic()
    recent_errors: deque[str] = deque(maxlen=6)
    stage = label

    def emit(text: str, *, metadata: bool = False) -> None:
        nonlocal stage
        if stream is not None:
            stream.write(text + '\n')
            stream.flush()
        if not metadata or echo_metadata:
            if callback is print:
                print_console(text)
            else:
                callback(text)
                # The default outer Python may itself have redirected stdout.
                sys.stdout.flush()
        if not metadata:
            stripped = text.strip()
            if (re.match(r'^\d+/\d+\s+-\s+', stripped) or
                stripped.startswith(('[RUN]', '[stage]', '[Windows', '[Linux', '[Android'))):
                stage = stripped[:180]
            if re.search(r'\berror\s*:|\bfatal error\b|^FAILED:|^CMake Error|\bundefined reference\b|\bunresolved external\b', text, re.I):
                if not recent_errors or recent_errors[-1] != text:
                    recent_errors.append(text[:1800])
    proc = None
    reader = None
    try:
        emit('COMMAND: ' + subprocess.list2cmdline(command), metadata=True)
        if log is not None:
            emit('LIVE LOG: ' + str(log), metadata=True)
        proc = subprocess.Popen(command, cwd=str(cwd), env=child_environment(env),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                bufsize=0, start_new_session=(os.name != 'nt'))
        assert proc.stdout is not None
        events: queue.Queue[bytes | BaseException | None] = queue.Queue()

        def drain() -> None:
            try:
                while True:
                    chunk = proc.stdout.read(8192)
                    if not chunk:
                        break
                    events.put(chunk)
            except BaseException as exc:
                events.put(exc)
            finally:
                events.put(None)
        reader = threading.Thread(target=drain, name='glover-build-output', daemon=True)
        reader.start()
        decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
        pending = ''
        last_bytes = started
        last_heartbeat = started
        eof = False
        while not eof or proc.poll() is None:
            now = time.monotonic()
            if timeout is not None and now - started >= timeout:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                event = events.get(timeout=0.1)
            except queue.Empty:
                event = b''
            if event is None:
                pending += decoder.decode(b'', final=True)
                eof = True
            elif isinstance(event, BaseException):
                raise event
            elif event:
                last_bytes = time.monotonic()
                pending += decoder.decode(event)
            # Handle LF and CR progress; CRLF may be split between reads. Empty
            # fragments are harmless and not duplicated in the console/log.
            while '\n' in pending or '\r' in pending:
                end = min(i for i in (pending.find('\n'), pending.find('\r')) if i >= 0)
                line, pending = pending[:end], pending[end + 1:]
                if line:
                    emit(line)
            if pending and (eof or time.monotonic() - last_bytes >= 0.2 or len(pending) >= 16384):
                emit(pending)
                pending = ''
            now = time.monotonic()
            if proc.poll() is None and now - last_heartbeat >= heartbeat_seconds:
                # Only print when the child has been quiet. Live Ninja/Git lines
                # already tell the user what is happening without extra noise.
                if now - last_bytes >= heartbeat_seconds:
                    emit(f'[RUNNING] {stage} | elapsed {now-started:.0f}s | '
                         f'no new output for {now-last_bytes:.0f}s | PID {proc.pid} '
                         '(may be working or waiting for input)', metadata=True)
                last_heartbeat = now
        if pending:
            emit(pending)
        code = proc.wait()
        if code and recent_errors:
            emit('[FAILURE SUMMARY] Compiler/tool diagnostics from this command:', metadata=True)
            for error in recent_errors:
                emit(error, metadata=True)
        emit(f'[EXIT] {label}: code {code}; elapsed {time.monotonic()-started:.1f}s', metadata=True)
        return code
    except BaseException:
        if proc is not None:
            _stop_process(proc)
        raise
    finally:
        if reader is not None:
            reader.join(timeout=2)
        if proc is not None and proc.stdout is not None:
            proc.stdout.close()
        if stream is not None:
            stream.close()
