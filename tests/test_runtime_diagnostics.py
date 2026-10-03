import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.runtime_diagnostics import diagnostic_logger, diagnostic_path


class DiagnosticsTest(unittest.TestCase):
    def test_failure_evidence_survives_staging_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'LOCALAPPDATA': directory}):
                logger = diagnostic_logger('test-persistent')
            try:
                with tempfile.TemporaryDirectory(dir=directory) as staging:
                    try:
                        raise PermissionError(13, 'execution denied', str(Path(staging) / 'app.exe'))
                    except PermissionError:
                        logger.exception('Update launch failed')
                evidence = Path(diagnostic_path(logger)).read_text(encoding='utf-8')
                self.assertIn('PermissionError', evidence)
                self.assertIn('execution denied', evidence)
                self.assertIn('Traceback', evidence)
                self.assertEqual(Path(diagnostic_path(logger)).parent,
                                 Path(directory) / 'SecretShopBot-E7/logs')
            finally:
                for handler in logger.handlers[:]:
                    handler.close()
                    logger.removeHandler(handler)

    def test_unwritable_log_locations_do_not_prevent_execution(self):
        with patch('src.runtime_diagnostics.Path.mkdir', side_effect=PermissionError('denied')):
            logger = diagnostic_logger('test-unwritable')
        try:
            self.assertIsInstance(logger.handlers[0], logging.NullHandler)
            logger.info('Application may still start')
        finally:
            logger.handlers.clear()
