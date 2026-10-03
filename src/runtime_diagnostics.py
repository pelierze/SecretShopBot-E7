"""Small, stdlib-only diagnostics available before GUI imports and updates."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import tempfile


def diagnostic_logger(kind):
    logger = logging.getLogger('e7.diagnostics.' + kind)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Keep evidence outside both the installation and disposable update staging.
    bases = [Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local'),
             Path(tempfile.gettempdir())]
    for base in bases:
        try:
            directory = base / 'SecretShopBot-E7' / 'logs'
            directory.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(directory / (kind + '.log'),
                                          maxBytes=2 * 1024**2, backupCount=3,
                                          encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
            logger.addHandler(handler)
            break
        except OSError:
            continue
    else:
        logger.addHandler(logging.NullHandler())
    return logger


def diagnostic_path(logger):
    return next((handler.baseFilename for handler in logger.handlers
                 if isinstance(handler, RotatingFileHandler)), '로그 파일을 만들 수 없습니다.')
