"""Standalone stdlib-only updater; copied outside the installation before launch."""
import ctypes
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from src.app_identity import APP_EXECUTABLE, UPDATER_EXECUTABLE
from src.runtime_diagnostics import diagnostic_logger, diagnostic_path

MANAGED = (APP_EXECUTABLE, UPDATER_EXECUTABLE, '_internal',
           'README.md', 'DEPLOY.md', 'SECURITY.md', 'RELEASE_NOTES.md')


def wait_parent(pid, ready, timeout=180):
    if os.name != 'nt':
        raise RuntimeError('Windows 전용 업데이트입니다.')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        raise RuntimeError('기존 앱 프로세스를 확인할 수 없습니다.')
    try:
        ready.write_text('ready', encoding='ascii')
        if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
            raise RuntimeError('기존 앱이 종료되지 않아 업데이트를 취소했습니다.')
    finally:
        kernel.CloseHandle(handle)


def start_app(target, ready=None):
    args = [str(target / APP_EXECUTABLE)]
    if ready is not None:
        args += ['--update-ready', str(ready)]
    logger = diagnostic_logger('updater')
    logger.info('Starting application: %s; cwd=%s', args, target)
    try:
        return subprocess.Popen(args, cwd=str(target), env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'})
    except OSError:
        logger.exception('Application launch failed')
        log_permissions(target, logger)
        raise


def icacls(*args):
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/icacls.exe'
    return subprocess.run([str(executable), *map(str, args)], capture_output=True,
                          text=True, errors='replace', timeout=180,
                          creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))


def log_permissions(target, logger):
    if os.name != 'nt':
        return
    for path in (Path(target), Path(target) / APP_EXECUTABLE, Path(target) / '_internal'):
        try:
            result = icacls(path)
            logger.info('Permissions %s (exit=%s): %s %s', path, result.returncode,
                        result.stdout.strip(), result.stderr.strip())
        except Exception:
            logger.exception('Could not inspect permissions: %s', path)


def inherit_install_permissions(path):
    """Remove staging ACLs after a same-volume move; inherit installation ACLs."""
    if os.name != 'nt':
        return
    result = icacls(path, '/reset', '/T', '/Q')
    diagnostic_logger('updater').info('Reset permissions: %s; exit=%s; %s %s',
                                    path, result.returncode, result.stdout.strip(),
                                    result.stderr.strip())
    if result.returncode:
        raise RuntimeError(f'설치 파일 접근 권한 설정 실패: {path}; {result.stdout} {result.stderr}')


def move_file(source, destination):
    # Antivirus and process teardown can briefly retain Windows file handles.
    deadline = time.monotonic() + 15
    while True:
        try:
            return source.rename(destination)
        except OSError as exc:
            if getattr(exc, 'winerror', None) not in (5, 32, 33) or time.monotonic() >= deadline:
                raise
            time.sleep(.3)


def await_start(process, ready, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('새 버전이 시작 중 종료되었습니다.')
        if ready.is_file():
            return
        time.sleep(.25)
    raise RuntimeError('새 버전 시작 확인 시간이 초과되었습니다.')


def apply_update(target, package, workspace, launcher=start_app, health=await_start):
    target, package, workspace = map(Path, (target, package, workspace))
    backup = workspace / 'backup'
    backup.mkdir()  # Never overwrite a previous recovery directory.
    moved, installed = [], []
    process = None
    logger = diagnostic_logger('updater')
    logger.info('Applying update: target=%s; package=%s; workspace=%s', target, package, workspace)
    log_permissions(target, logger)
    try:
        # Older builds wrote logs inside _internal. Preserve those too.
        for name in ('logs', 'updates'):
            old = target / '_internal' / name
            if old.exists():
                shutil.copytree(old, package / '_internal' / name, dirs_exist_ok=True)
        for name in MANAGED:
            old, new = target / name, package / name
            if old.exists():
                move_file(old, backup / name)
                moved.append(name)
            if new.exists():
                move_file(new, target / name)
                installed.append(name)
                inherit_install_permissions(target / name)
        log_permissions(target, logger)
        process = launcher(target, workspace / 'app-ready')
        health(process, workspace / 'app-ready')
        logger.info('Updated application acknowledged startup')
    except Exception as original:
        logger.exception('Update failed; restoring previous installation')
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        # Keep failed files for diagnosis; only rename this attempt's own files.
        failed = workspace / 'failed'
        failed.mkdir(exist_ok=True)
        try:
            for name in reversed(installed):
                move_file(target / name, failed / name)
            for name in reversed(moved):
                move_file(backup / name, target / name)
        except Exception as rollback_error:
            logger.exception('Rollback failed; backup=%s', backup)
            raise RuntimeError(f'자동 복구 실패. 백업 위치: {backup}; {rollback_error}') from original
        logger.info('Previous installation restored')
        launcher(target)
        raise RuntimeError(f'이전 버전으로 복구했습니다: {original}') from original
    return process.pid


def schedule_cleanup(workspace, target):
    """Delete only this successful staging folder after this worker exits."""
    workspace, target = Path(workspace).resolve(), Path(target).resolve()
    if (not workspace.name.startswith('.e7-update-')
            or workspace.parent != target.parent
            or workspace == target
            or target.is_relative_to(workspace)):
        raise ValueError('Invalid cleanup workspace')
    result = json.loads((workspace / 'result.json').read_text(encoding='utf-8'))
    if result.get('ok') is not True:
        raise ValueError('Only successful updates can be cleaned up')
    # The running updater cannot delete its own EXE on Windows. Use the system
    # PowerShell from outside staging, and wait for the worker before removing it.
    literal = "'" + str(workspace).replace("'", "''") + "'"
    script = f"""
$ErrorActionPreference = 'Stop'
$stagingPath = {literal}
$worker = Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue
if ($worker -and -not $worker.WaitForExit(180000)) {{ exit 1 }}
if (-not (Test-Path -LiteralPath $stagingPath)) {{ exit 0 }}
try {{
    $outcome = Get-Content -LiteralPath (Join-Path $stagingPath 'result.json') -Raw | ConvertFrom-Json
    if ($outcome.ok -ne $true) {{ exit 1 }}
}} catch {{ exit 1 }}
for ($attempt = 0; $attempt -lt 30; $attempt++) {{
    try {{
        Remove-Item -LiteralPath $stagingPath -Recurse -Force
        exit 0
    }} catch {{ Start-Sleep -Seconds 1 }}
}}
exit 1
"""
    encoded = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    return subprocess.Popen(
        [str(powershell), '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
         '-EncodedCommand', encoded], cwd=str(target),
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    logger = diagnostic_logger('updater')
    logger.info('Updater started: executable=%s; arguments=%s', sys.executable, sys.argv[1:])
    result = None
    try:
        plan_path = Path(sys.argv[1]).resolve()
        workspace = plan_path.parent
        result = workspace / 'result.json'
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        target = Path(plan['target']).resolve()
        package = Path(plan['package']).resolve()
        if not workspace.name.startswith('.e7-update-') or workspace.parent != target.parent or not package.is_relative_to(workspace / 'payload') or not (target / APP_EXECUTABLE).is_file():
            raise ValueError('업데이트 작업 경로가 올바르지 않습니다.')
        if target.is_relative_to(workspace) or workspace.is_relative_to(target):
            raise ValueError('설치 및 임시 폴더가 겹칩니다.')
        wait_parent(int(plan['parent_pid']), workspace / 'worker-ready')
        pid = apply_update(target, package, workspace)
        result.write_text(json.dumps({'ok': True, 'pid': pid}), encoding='utf-8')
    except Exception as exc:
        logger.exception('Updater failed')
        if result is not None:
            try:
                result.write_text(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), encoding='utf-8')
            except OSError:
                logger.exception('Could not write update result: %s', result)
        if os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None, str(exc) + '\n\n기록: ' + str(result)
                                           + '\n진단 로그: ' + diagnostic_path(logger), '업데이트 실패', 0x10)
        return 1
    # Cleanup failure must never turn a healthy installation into a failed update.
    try:
        schedule_cleanup(workspace, target)
    except Exception as exc:
        logger.exception('Update staging cleanup could not be started')
        result.write_text(json.dumps({'ok': True, 'pid': pid, 'cleanup_error': str(exc)},
                                     ensure_ascii=False), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
