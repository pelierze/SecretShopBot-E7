import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from src.app_updater import extract_verified, release_assets, prepare_update, MANAGED
from src.release_checker import ReleaseInfo, fetch_latest_release
from updater_main import apply_update


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / 'SecretShopBot-E7-v1.4.4.zip'
        self.checksum = self.root / (self.archive.name + '.sha256.txt')

    def package(self, extra=None):
        entries = {'SecretShopBot-E7.exe': b'new', 'SecretShopBot-Updater.exe': b'helper',
                   '_internal/python312.dll': b'python', '_internal/new.txt': b'new'}
        entries.update(extra or {})
        with zipfile.ZipFile(self.archive, 'w') as z:
            for name, data in entries.items():
                info = zipfile.ZipInfo()
                info.filename = self.archive.stem + '/' + name
                z.writestr(info, data)
        self.checksum.write_text(hashlib.sha256(self.archive.read_bytes()).hexdigest() + '  ' + self.archive.name, encoding='ascii')

    def release(self):
        names = (self.archive.name, self.checksum.name)
        return ReleaseInfo('v1.4.4', 'https://github.com/pelierze/SecretShopBot-E7/releases/tag/v1.4.4', 'new',
            assets=tuple({'name': n, 'browser_download_url': 'https://github.com/pelierze/SecretShopBot-E7/releases/download/v1.4.4/' + n} for n in names))

    def test_valid_package_and_assets(self):
        self.package()
        p = extract_verified(self.archive, self.checksum, self.root / 'output')
        self.assertEqual((p / 'SecretShopBot-E7.exe').read_bytes(), b'new')
        self.assertEqual(release_assets(self.release())[0], self.archive.name)

    def test_checksum_mismatch_never_extracts(self):
        self.package()
        self.archive.write_bytes(self.archive.read_bytes() + b'tampered')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            extract_verified(self.archive, self.checksum, self.root / 'output')
        self.assertFalse((self.root / 'output').exists())

    def test_unsafe_and_user_data_paths_rejected(self):
        for bad in ('../escape', 'logs/user.log', '_internal/../../escape', '_internal/C:evil', '_internal/NUL', '_internal/file. ', '_internal\\..\\..\\escape'):
            with self.subTest(bad=bad):
                self.package({bad: b'bad'})
                with self.assertRaises(ValueError):
                    extract_verified(self.archive, self.checksum, self.root / 'output')
                self.assertFalse((self.root / 'output').exists())

    def test_duplicate_case_and_symlink_rejected(self):
        for name in ('_internal/NEW.txt', '_internal/link'):
            self.package()
            with zipfile.ZipFile(self.archive, 'a') as z:
                info = zipfile.ZipInfo(self.archive.stem + '/' + name)
                if name.endswith('link'):
                    info.external_attr = 0o120777 << 16
                z.writestr(info, b'bad')
            self.checksum.write_text(hashlib.sha256(self.archive.read_bytes()).hexdigest() + '  ' + self.archive.name)
            with self.assertRaises(ValueError):
                extract_verified(self.archive, self.checksum, self.root / 'output')

    def test_missing_external_or_wrong_version_assets_rejected(self):
        r = self.release()
        for url in ('https://evil.test/file.zip', r.assets[0]['browser_download_url'].replace('/v1.4.4/', '/v1.4.3/')):
            r.assets[0]['browser_download_url'] = url
            with self.assertRaises(ValueError): release_assets(r)
        with self.assertRaises(ValueError): release_assets(ReleaseInfo('v1.4.4', '', ''))
        r = self.release(); r.version = 'v1.4.4-rc.1'
        with self.assertRaises(ValueError): release_assets(r)

    def test_download_failure_does_not_change_install_and_cleans_staging(self):
        target = self.root / 'app'; target.mkdir()
        (target / 'SecretShopBot-E7.exe').write_bytes(b'old')
        with patch('src.app_updater.download', side_effect=OSError('offline')):
            with self.assertRaises(OSError): prepare_update(self.release(), target)
        self.assertEqual((target / 'SecretShopBot-E7.exe').read_bytes(), b'old')
        self.assertFalse(list(self.root.glob('.e7-update-*')))

    def test_fetch_preserves_download_assets(self):
        response = Mock(); response.status = 200
        response.read.return_value = json.dumps({'tag_name': 'v1.4.4', 'assets': self.release().assets}).encode()
        response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        with patch('urllib.request.urlopen', return_value=response):
            self.assertEqual(release_assets(fetch_latest_release())[0], self.archive.name)


class TransactionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'installed'; self.package = self.root / 'package'; self.work = self.root / 'work'
        for directory in (self.target, self.package, self.work): directory.mkdir()
        for name in ('SecretShopBot-E7.exe', 'SecretShopBot-Updater.exe'):
            (self.target / name).write_text('old'); (self.package / name).write_text('new')
        (self.target / '_internal/logs').mkdir(parents=True)
        (self.target / '_internal/logs/old.log').write_text('historic')
        (self.target / '_internal/unused.png').write_text('unused')
        (self.package / '_internal').mkdir()
        (self.package / '_internal/new.png').write_text('new')
        for name in ('settings.json', 'logs/user.log', 'updates/cache.json'):
            p = self.target / name; p.parent.mkdir(exist_ok=True); p.write_text('user')
        self.launcher = Mock(return_value=Mock(poll=Mock(return_value=None)))

    def verify_old(self):
        self.assertEqual((self.target / 'SecretShopBot-E7.exe').read_text(), 'old')
        self.assertTrue((self.target / '_internal/unused.png').exists())
        self.assertFalse((self.target / '_internal/new.png').exists())
        self.assertEqual((self.target / 'settings.json').read_text(), 'user')

    def test_success_preserves_settings_and_logs_removes_obsolete_assets(self):
        apply_update(self.target, self.package, self.work, self.launcher, Mock())
        self.assertEqual((self.target / 'SecretShopBot-E7.exe').read_text(), 'new')
        for name in ('settings.json', 'logs/user.log', 'updates/cache.json'):
            self.assertEqual((self.target / name).read_text(), 'user')
        self.assertEqual((self.target / '_internal/logs/old.log').read_text(), 'historic')
        self.assertFalse((self.target / '_internal/unused.png').exists())
        self.assertTrue((self.work / 'backup/_internal/unused.png').exists())

    def test_startup_failure_stops_new_app_and_restores_old_app(self):
        with self.assertRaisesRegex(RuntimeError, '복구'):
            apply_update(self.target, self.package, self.work, self.launcher, Mock(side_effect=RuntimeError('crash')))
        self.verify_old()
        self.launcher.return_value.terminate.assert_called_once()
        self.assertEqual(self.launcher.call_count, 2)

    def test_partial_copy_failure_rolls_back_only_changed_files(self):
        original = Path.rename
        def rename(path, target):
            if path == self.package / '_internal': raise PermissionError('locked')
            return original(path, target)
        with patch.object(Path, 'rename', rename):
            with self.assertRaisesRegex(RuntimeError, '복구'):
                apply_update(self.target, self.package, self.work, self.launcher, Mock())
        self.verify_old()

    def test_locked_existing_files_keep_old_install(self):
        original = Path.rename
        def rename(path, target):
            if path == self.target / 'SecretShopBot-E7.exe': raise PermissionError('locked')
            return original(path, target)
        with patch.object(Path, 'rename', rename):
            with self.assertRaisesRegex(RuntimeError, '복구'):
                apply_update(self.target, self.package, self.work, self.launcher, Mock())
        self.verify_old()


if __name__ == '__main__': unittest.main()
