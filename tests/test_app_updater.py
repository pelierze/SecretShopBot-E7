import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from src.app_updater import extract_verified, release_assets, prepare_update, MANAGED
from src.release_checker import ReleaseInfo, fetch_latest_release
from updater_main import apply_update, schedule_cleanup, main as updater_main, icacls, start_app
from src.app_identity import resolve_app_executable, resolve_updater_executable


class PackageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / 'SecretShopBot-E7-v1.4.4.zip'
        self.checksum = self.root / (self.archive.name + '.sha256.txt')

    def package(self, extra=None, renamed=False):
        entries = {'SecretShopBot-E7.exe': b'new', 'SecretShopBot-Updater.exe': b'helper',
                   '_internal/python312.dll': b'python', '_internal/new.txt': b'new'}
        entries.update(extra or {})
        if renamed:
            entries['EAB.exe'] = entries.pop('SecretShopBot-E7.exe')
            entries['EAB-Updater.exe'] = entries.pop('SecretShopBot-Updater.exe')
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

    def test_new_package_names_and_executables(self):
        self.archive = self.root / 'EAB-v1.4.4.zip'
        self.checksum = self.root / (self.archive.name + '.sha256.txt')
        self.package(renamed=True)
        p = extract_verified(self.archive, self.checksum, self.root / 'output')
        self.assertEqual(resolve_app_executable(p).name, 'EAB.exe')
        self.assertEqual(resolve_updater_executable(p).name, 'EAB-Updater.exe')
        self.assertEqual(release_assets(self.release())[0], self.archive.name)

    def test_assets_prefer_legacy_pair_and_never_mix_checksums(self):
        release = self.release()
        new_assets = tuple({'name': a['name'].replace('SecretShopBot-E7', 'EAB'),
                            'browser_download_url': a['browser_download_url'].replace('SecretShopBot-E7-v', 'EAB-v')}
                           for a in release.assets)
        release.assets += new_assets
        self.assertEqual(release_assets(release)[0], self.archive.name)
        release.assets = (release.assets[0], *new_assets)
        self.assertEqual(release_assets(release)[0], 'EAB-v1.4.4.zip')
        release.assets = (release.assets[0], new_assets[1])
        with self.assertRaises(ValueError):
            release_assets(release)

    def test_new_assets_keep_official_url_and_duplicate_checks(self):
        self.archive = self.root / 'EAB-v1.4.4.zip'
        self.checksum = self.root / (self.archive.name + '.sha256.txt')
        release = self.release()
        release.assets += (release.assets[0],)
        with self.assertRaises(ValueError):
            release_assets(release)
        release = self.release()
        release.assets[0]['browser_download_url'] = 'https://evil.test/' + self.archive.name
        with self.assertRaises(ValueError):
            release_assets(release)

    def test_prepare_uses_installed_helper_for_both_names(self):
        self.package(renamed=True)
        for app, helper in (('SecretShopBot-E7.exe', 'SecretShopBot-Updater.exe'),
                            ('EAB.exe', 'EAB-Updater.exe')):
            with self.subTest(app=app):
                target = self.root / app
                target.mkdir()
                (target / app).write_bytes(b'installed')
                (target / helper).write_bytes(b'trusted')
                def fake_download(url, destination, *args):
                    shutil.copy2(self.checksum if url.endswith('.sha256.txt') else self.archive, destination)
                with patch('src.app_updater.download', side_effect=fake_download), \
                        patch('src.app_updater.shutil.disk_usage', return_value=Mock(free=3 * 1024**3)):
                    plan = prepare_update(self.release(), target)
                self.assertEqual((plan.parent / 'updater.exe').read_bytes(), b'trusted')
                self.assertEqual((target / app).read_bytes(), b'installed')

    def test_executable_directories_are_not_accepted(self):
        (self.root / 'EAB.exe').mkdir()
        (self.root / 'EAB-Updater.exe').mkdir()
        with self.assertRaises(ValueError):
            resolve_app_executable(self.root)
        with self.assertRaises(ValueError):
            resolve_updater_executable(self.root)

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

    def rename_package(self):
        (self.package / 'SecretShopBot-E7.exe').rename(self.package / 'EAB.exe')
        (self.package / 'SecretShopBot-Updater.exe').rename(self.package / 'EAB-Updater.exe')

    def test_legacy_to_new_names_and_subsequent_update(self):
        self.rename_package()
        for attempt in range(2):
            if attempt:
                self.package.mkdir(exist_ok=True)
                (self.package / 'EAB.exe').write_text('next')
                (self.package / 'EAB-Updater.exe').write_text('next')
                (self.package / '_internal').mkdir()
                self.work = self.root / 'next-work'
                self.work.mkdir()
            apply_update(self.target, self.package, self.work, self.launcher, Mock())
            self.assertEqual(resolve_app_executable(self.target).name, 'EAB.exe')
            self.assertEqual(resolve_updater_executable(self.target).name, 'EAB-Updater.exe')
            self.assertFalse((self.target / 'SecretShopBot-E7.exe').exists())
            self.assertFalse((self.target / 'SecretShopBot-Updater.exe').exists())
            self.assertEqual((self.target / 'settings.json').read_text(), 'user')
            self.assertEqual((self.target / '_internal/logs/old.log').read_text(), 'historic')

    def test_renamed_package_startup_failure_restores_legacy_names(self):
        self.rename_package()
        with self.assertRaisesRegex(RuntimeError, '복구'):
            apply_update(self.target, self.package, self.work, self.launcher, Mock(side_effect=RuntimeError('crash')))
        self.verify_old()
        self.assertFalse((self.target / 'EAB.exe').exists())
        self.assertFalse((self.target / 'EAB-Updater.exe').exists())
        self.assertEqual(resolve_updater_executable(self.target).name, 'SecretShopBot-Updater.exe')

    def test_renamed_package_partial_failure_restores_legacy_names(self):
        self.rename_package()
        original = Path.rename
        def rename(path, target):
            if path == self.package / '_internal':
                raise PermissionError('locked')
            return original(path, target)
        with patch.object(Path, 'rename', rename):
            with self.assertRaisesRegex(RuntimeError, '복구'):
                apply_update(self.target, self.package, self.work, self.launcher, Mock())
        self.verify_old()
        self.assertFalse((self.target / 'EAB.exe').exists())
        self.assertFalse((self.target / 'EAB-Updater.exe').exists())

    def test_new_installation_startup_failure_restores_new_names(self):
        self.rename_package()
        (self.target / 'SecretShopBot-E7.exe').rename(self.target / 'EAB.exe')
        (self.target / 'SecretShopBot-Updater.exe').rename(self.target / 'EAB-Updater.exe')
        with self.assertRaisesRegex(RuntimeError, '복구'):
            apply_update(self.target, self.package, self.work, self.launcher, Mock(side_effect=RuntimeError('crash')))
        self.assertEqual((self.target / 'EAB.exe').read_text(), 'old')
        self.assertEqual((self.target / 'EAB-Updater.exe').read_text(), 'old')
        self.assertFalse((self.target / 'SecretShopBot-E7.exe').exists())
        self.assertEqual((self.target / 'settings.json').read_text(), 'user')

    def test_start_app_resolves_installed_filename(self):
        for renamed in (False, True):
            if renamed:
                (self.target / 'SecretShopBot-E7.exe').rename(self.target / 'EAB.exe')
            with patch('updater_main.subprocess.Popen') as launch:
                start_app(self.target, self.work / 'ready')
            self.assertEqual(launch.call_args.args[0],
                             [str(resolve_app_executable(self.target)), '--update-ready', str(self.work / 'ready')])

    def test_incomplete_package_does_not_touch_installation(self):
        (self.package / 'SecretShopBot-Updater.exe').unlink()
        with self.assertRaises(ValueError):
            apply_update(self.target, self.package, self.work, self.launcher, Mock())
        self.verify_old()
        self.launcher.assert_not_called()
        self.assertFalse((self.work / 'backup').exists())

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

    def test_permission_repair_failure_restores_previous_installation(self):
        with patch('updater_main.inherit_install_permissions', side_effect=PermissionError('ACL denied')):
            with self.assertRaisesRegex(RuntimeError, 'ACL denied'):
                apply_update(self.target, self.package, self.work, self.launcher, Mock())
        self.verify_old()
        # Only the restored app may be launched, never the partially repaired one.
        self.assertEqual(self.launcher.call_count, 1)

    @unittest.skipUnless(os.name == 'nt', 'Windows NTFS permissions integration')
    def test_moved_update_files_inherit_installation_access(self):
        # Staging was created beneath mkdtemp and lacks this installation ACE.
        result = icacls(self.target, '/grant', '*S-1-5-32-545:(OI)(CI)(RX)')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        def acl_sddl(path):
            saved = self.root / 'saved-acl.txt'
            result = icacls(path, '/save', saved, '/Q')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return saved.read_text(encoding='utf-16-le')
        # BU is the language-independent SDDL alias for Builtin Users.
        self.assertNotIn(';;;BU)', acl_sddl(self.package / 'SecretShopBot-E7.exe'))
        apply_update(self.target, self.package, self.work, self.launcher, Mock())
        for name in ('SecretShopBot-E7.exe', 'SecretShopBot-Updater.exe', '_internal/new.png'):
            self.assertIn(';;;BU)', acl_sddl(self.target / name), name)


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.target = self.root / 'installed'
        self.target.mkdir()
        self.work = self.root / ".e7-update-test's [folder]"
        self.work.mkdir()
        (self.work / 'result.json').write_text(json.dumps({'ok': True}))
        (self.work / 'backup').mkdir()
        (self.work / 'backup/old.exe').write_bytes(b'old')
        (self.target / 'settings.json').write_text('user')

    def test_failed_updates_and_unrelated_paths_are_never_deleted(self):
        (self.work / 'result.json').write_text(json.dumps({'ok': False}))
        with patch('updater_main.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):
                schedule_cleanup(self.work, self.target)
            with self.assertRaises(ValueError):
                schedule_cleanup(self.target, self.target)
            launch.assert_not_called()
        self.assertTrue((self.work / 'backup/old.exe').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows cleanup integration')
    def test_cleanup_waits_for_worker_then_removes_only_staging(self):
        worker = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            with patch('updater_main.os.getpid', return_value=worker.pid):
                cleanup = schedule_cleanup(self.work, self.target)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    cleanup.wait(timeout=2)
                self.assertTrue((self.work / 'backup/old.exe').exists())
                worker.terminate()
                worker.wait(timeout=10)
                self.assertEqual(cleanup.wait(timeout=15), 0)
                self.assertFalse(self.work.exists())
                self.assertEqual((self.target / 'settings.json').read_text(), 'user')
            finally:
                if cleanup.poll() is None:
                    cleanup.terminate()
                    cleanup.wait(timeout=10)
        finally:
            if worker.poll() is None:
                worker.terminate()
                worker.wait(timeout=10)

    def test_cleanup_dispatch_failure_keeps_update_successful(self):
        (self.target / 'SecretShopBot-E7.exe').write_bytes(b'new')
        plan = self.work / 'plan.json'
        plan.write_text(json.dumps({'target': str(self.target),
                                   'package': str(self.work / 'payload/package'),
                                   'parent_pid': 123}))
        with patch.object(sys, 'argv', ['updater', str(plan)]), \
                patch('updater_main.wait_parent'), \
                patch('updater_main.apply_update', return_value=456), \
                patch('updater_main.schedule_cleanup', side_effect=OSError('unavailable')):
            self.assertEqual(updater_main(), 0)
        result = json.loads((self.work / 'result.json').read_text())
        self.assertTrue(result['ok'])
        self.assertIn('cleanup_error', result)
        self.assertTrue((self.work / 'backup/old.exe').exists())


if __name__ == '__main__': unittest.main()
