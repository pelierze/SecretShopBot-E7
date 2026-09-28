"""Standalone stdlib-only updater; copied outside the installation before launch."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

MANAGED = ('SecretShopBot-E7.exe', 'SecretShopBot-Updater.exe', '_internal',
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
    args = [str(target / 'SecretShopBot-E7.exe')]
    if ready is not None:
        args += ['--update-ready', str(ready)]
    return subprocess.Popen(args, cwd=str(target), env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'})


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
        process = launcher(target, workspace / 'app-ready')
        health(process, workspace / 'app-ready')
    except Exception as original:
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
            raise RuntimeError(f'자동 복구 실패. 백업 위치: {backup}; {rollback_error}') from original
        launcher(target)
        raise RuntimeError(f'이전 버전으로 복구했습니다: {original}') from original
    return process.pid


def main():
    plan_path = Path(sys.argv[1]).resolve()
    workspace = plan_path.parent
    result = workspace / 'result.json'
    try:
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        target = Path(plan['target']).resolve()
        package = Path(plan['package']).resolve()
        if not workspace.name.startswith('.e7-update-') or workspace.parent != target.parent or not package.is_relative_to(workspace / 'payload') or not (target / 'SecretShopBot-E7.exe').is_file():
            raise ValueError('업데이트 작업 경로가 올바르지 않습니다.')
        if target.is_relative_to(workspace) or workspace.is_relative_to(target):
            raise ValueError('설치 및 임시 폴더가 겹칩니다.')
        wait_parent(int(plan['parent_pid']), workspace / 'worker-ready')
        pid = apply_update(target, package, workspace)
        result.write_text(json.dumps({'ok': True, 'pid': pid}), encoding='utf-8')
        # Backups are retained for recovery; downloads and payload are disposable.
        for entry in workspace.glob('*.zip'):
            entry.unlink()
        shutil.rmtree(workspace / 'payload', ignore_errors=True)
    except Exception as exc:
        result.write_text(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), encoding='utf-8')
        if os.name == 'nt':
            ctypes.windll.user32.MessageBoxW(None, str(exc) + '\n\n기록: ' + str(result), '업데이트 실패', 0x10)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
