"""Best-effort reports for automation failures; never replace the original error."""
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

from .version import APP_VERSION

logger = logging.getLogger(__name__)


def save_failure_report(log_root, log_file, result, bot, session, mode, controller=None):
    """Save the last observed screen and a bounded tail of the application log."""
    try:
        name = re.sub(r'[^\w.-]', '_', str(session))[:60] or 'session'
        folder = Path(log_root) / 'report' / (
            datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '_' + name + '_' + uuid4().hex[:8])
        folder.mkdir(parents=True)
        metadata = dict(version=APP_VERSION, session=str(session), mode=mode,
                        created_at=datetime.now().astimezone().isoformat(), result=result,
                        screenshot_source=None, screenshot_errors=[])
        saved = False
        active = getattr(bot, 'active', bot)
        # Prefer the frame used by the failing operation, rather than a later UI state.
        candidates = [active, getattr(active, 'observer', None)]
        for candidate in candidates:
            frame = getattr(candidate, 'last_screen', None)
            if isinstance(frame, np.ndarray) and frame.size:
                try:
                    ok, encoded = cv2.imencode('.png', frame)
                    if not ok:
                        raise OSError('PNG 인코딩 실패')
                    (folder / 'screen.png').write_bytes(encoded.tobytes())
                    metadata['screenshot_source'] = 'last_observed_frame'
                    saved = True
                    break
                except Exception as exc:
                    metadata['screenshot_errors'].append(str(exc))
            for attribute in ('screen_path', 'screenshot_path'):
                source = getattr(candidate, attribute, None)
                if not isinstance(source, (str, Path)) or not Path(source).is_file():
                    continue
                try:
                    shutil.copyfile(source, folder / 'screen.png')
                    metadata['screenshot_source'] = str(source)
                    metadata['screenshot_modified_at'] = datetime.fromtimestamp(
                        Path(source).stat().st_mtime).astimezone().isoformat()
                    saved = True
                    break
                except Exception as exc:
                    metadata['screenshot_errors'].append(str(exc))
            if saved:
                break
        if not saved and controller is not None:
            try:
                saved = bool(controller.screenshot(str(folder / 'screen.png')))
                saved = saved and (folder / 'screen.png').is_file()
                if saved:
                    metadata['screenshot_source'] = 'capture_after_failure'
                else:
                    metadata['screenshot_errors'].append('종료 후 화면 캡처 실패')
            except Exception as exc:
                metadata['screenshot_errors'].append(str(exc))
        metadata['screenshot_saved'] = saved
        runtime_dir = getattr(active, 'runtime_dir', None)
        if isinstance(runtime_dir, (str, Path)):
            for filename in ('failure.json', 'recognition_timeout.json'):
                source = Path(runtime_dir) / filename
                try:
                    if source.is_file():
                        shutil.copyfile(source, folder / filename)
                except Exception as exc:
                    metadata.setdefault('diagnostic_errors', []).append(str(exc))
        if not saved:
            logger.warning('비정상 종료 보고서의 스크린샷을 확보하지 못했습니다: %s',
                           '; '.join(metadata['screenshot_errors']) or '마지막 화면 없음')
        logger.warning('비정상 종료 보고서 저장 위치: %s — 문제 신고 시 이 폴더의 파일을 함께 첨부해 주세요.',
                       folder.resolve())
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception as exc:
                metadata.setdefault('log_flush_errors', []).append(str(exc))
        try:
            with Path(log_file).open('rb') as stream:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size - 256 * 1024))
                tail = stream.read().decode('utf-8', errors='replace')
            if size > 256 * 1024:
                tail = tail.partition('\n')[2]
            tail = '\n'.join(tail.splitlines()[-1000:])
        except Exception as exc:
            metadata['log_error'] = str(exc)
            tail = f'최근 로그를 읽지 못했습니다: {exc}'
            logger.warning('보고서의 최근 로그를 읽지 못했습니다: %s', exc)
        header = f'비정상 종료 보고서\n세션: {session}\n모드: {mode}\n종료 정보: {result}\n\n'
        (folder / 'recent.log').write_text(header + tail + '\n', encoding='utf-8')
        (folder / 'report.json').write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        return folder
    except Exception:
        logger.exception('비정상 종료 보고서 저장 실패. 기존 실행 오류는 bot.log에서 확인해 주세요.')
        return None
