"""Download verified release packages without changing the running installation."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from urllib.parse import urlparse
import zipfile

from .app_identity import (UPDATE_PACKAGE_NAME, SUPPORTED_RELEASE_REPOSITORIES,
                           SUPPORTED_PACKAGE_NAMES, UPDATE_MANAGED_FILES,
                           resolve_app_executable, resolve_updater_executable)
from .runtime_diagnostics import diagnostic_logger

APP = UPDATE_PACKAGE_NAME
MANAGED = UPDATE_MANAGED_FILES
MAX_DOWNLOAD = 600 * 1024**2
MAX_EXPANDED = 2 * 1024**3


def release_assets(release):
    if not re.fullmatch(r'v?\d+\.\d+\.\d+', release.version):
        raise ValueError('자동 업데이트는 정식 버전만 지원합니다.')
    version = release.version.lstrip('v')
    # Prefer the legacy pair while both are published. Never mix checksums
    # between package names or silently accept duplicate release assets.
    candidates = []
    for package_name in SUPPORTED_PACKAGE_NAMES:
        candidate = f'{package_name}-v{version}.zip'
        pair = [[a for a in release.assets if a.get('name') == expected]
                for expected in (candidate, candidate + '.sha256.txt')]
        if any(len(matches) > 1 for matches in pair):
            raise ValueError('중복된 업데이트 배포 파일이 있습니다.')
        if all(pair):
            candidates.append(candidate)
    if not candidates:
        raise ValueError('릴리즈 ZIP 또는 SHA256 파일이 없습니다. 다운로드 페이지를 이용해 주세요.')
    name = candidates[0]
    result = []
    repositories = []
    for expected in (name, name + '.sha256.txt'):
        matches = [a for a in release.assets if a.get('name') == expected]
        if len(matches) != 1:
            raise ValueError('릴리즈 ZIP 또는 SHA256 파일이 없습니다. 다운로드 페이지를 이용해 주세요.')
        url = matches[0].get('browser_download_url', '')
        parsed = urlparse(url)
        repository = next((repo for repo in SUPPORTED_RELEASE_REPOSITORIES
                           if parsed.path == f'/{repo}/releases/download/{release.version}/{expected}'), None)
        if parsed.scheme != 'https' or parsed.netloc != 'github.com' or repository is None or parsed.query or parsed.fragment:
            raise ValueError('공식 저장소의 배포 파일 주소가 아닙니다.')
        repositories.append(repository)
        result.append(url)
    if len(set(repositories)) != 1:
        raise ValueError('ZIP과 SHA256 파일의 저장소가 일치하지 않습니다.')
    return name, *result


def download(url, destination, limit, progress=lambda text: None):
    request = urllib.request.Request(url, headers={'User-Agent': APP + '-Updater'})
    size = 0
    with urllib.request.urlopen(request, timeout=30) as response, destination.open('xb') as out:
        total = int(response.headers.get('Content-Length') or 0)
        if total > limit:
            raise ValueError('업데이트 파일 크기 제한을 초과했습니다.')
        last_percent = -1
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise ValueError('업데이트 파일 크기 제한을 초과했습니다.')
            out.write(chunk)
            percent = int(size * 100 / total) if total else 0
            if percent != last_percent:
                progress(f'다운로드 중 {percent}%' if total else '다운로드 중...')
                last_percent = percent
        if total and size != total:
            raise ValueError('업데이트 다운로드가 완료되지 않았습니다.')


def extract_verified(archive, checksum, destination):
    fields = checksum.read_text(encoding='utf-8-sig').strip().split()
    if len(fields) != 2 or fields[1] != archive.name or not re.fullmatch('[0-9a-fA-F]{64}', fields[0]):
        raise ValueError('SHA256 파일 형식이 올바르지 않습니다.')
    with archive.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if digest.lower() != fields[0].lower():
        raise ValueError('업데이트 파일 검증 실패: SHA256 불일치')
    with zipfile.ZipFile(archive) as z:
        files = z.infolist()
        if len(files) > 20000 or sum(f.file_size for f in files) > MAX_EXPANDED:
            raise ValueError('압축 해제 크기 제한을 초과했습니다.')
        roots, seen = set(), set()
        for info in files:
            name = info.filename
            parts = PurePosixPath(name).parts
            if not parts or '\\' in name or name.startswith('/') or any(p in ('.', '..') or ':' in p or p.endswith((' ', '.')) or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?', p) for p in parts):
                raise ValueError('안전하지 않은 ZIP 경로입니다.')
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('ZIP 링크는 허용하지 않습니다.')
            if name.casefold() in seen:
                raise ValueError('중복 ZIP 경로입니다.')
            seen.add(name.casefold())
            roots.add(parts[0])
            if len(parts) > 1 and parts[1] not in MANAGED:
                raise ValueError('허용되지 않은 배포 파일입니다: ' + parts[1])
        if roots != {archive.stem}:
            raise ValueError('배포 폴더 이름이 버전과 일치하지 않습니다.')
        z.extractall(destination)
    package = destination / archive.stem
    resolve_app_executable(package)
    resolve_updater_executable(package)
    if not (package / '_internal').is_dir() or not any(p.is_file() for p in (package / '_internal').glob('python3*.dll')):
        raise ValueError('필수 실행 파일 또는 업데이트 프로그램이 없습니다.')
    return package


def prepare_update(release, target, progress=lambda text: None):
    logger = diagnostic_logger('updater')
    logger.info('Preparing update: version=%s; target=%s', release.version, target)
    name, zip_url, checksum_url = release_assets(release)
    target = Path(target).resolve()
    # Same volume staging permits directory renames and tests write access early.
    workspace = Path(tempfile.mkdtemp(prefix='.e7-update-', dir=target.parent))
    try:
        archive = workspace / name
        checksum = workspace / (name + '.sha256.txt')
        download(checksum_url, checksum, 4096)
        download(zip_url, archive, MAX_DOWNLOAD, progress)
        progress('다운로드 검증 및 압축 해제 중...')
        required_space = MAX_EXPANDED
        if shutil.disk_usage(workspace).free < required_space:
            raise ValueError('업데이트를 위해 디스크 여유 공간 2GB가 필요합니다.')
        package = extract_verified(archive, checksum, workspace / 'payload')
        # Run the CURRENT trusted updater, never a helper from the downloaded ZIP.
        helper = workspace / 'updater.exe'
        shutil.copy2(resolve_updater_executable(target), helper)
        plan = {'target': str(target), 'package': str(package), 'parent_pid': os.getpid()}
        path = workspace / 'plan.json'
        path.write_text(json.dumps(plan), encoding='utf-8')
        return path
    except Exception:
        logger.exception('Update preparation failed')
        shutil.rmtree(workspace, ignore_errors=True)
        raise


def launch_update(plan):
    plan = Path(plan)
    logger = diagnostic_logger('updater')
    logger.info('Launching update worker: plan=%s', plan)
    try:
        return subprocess.Popen([str(plan.parent / 'updater.exe'), str(plan)],
                            cwd=str(plan.parent), env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'},
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError:
        logger.exception('Update worker launch failed')
        raise
