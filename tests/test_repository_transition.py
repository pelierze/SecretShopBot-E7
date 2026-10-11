import unittest
from unittest.mock import patch

from src import auto_update, remote_script, release_checker
from src.app_updater import release_assets
from src.release_checker import ReleaseInfo


class ReleaseAddressTest(unittest.TestCase):
    def fetch_with(self, results):
        def fetch(url):
            result = results[url]
            if isinstance(result, Exception):
                raise result
            return result
        return patch('src.release_checker._fetch_release_at', side_effect=fetch)

    def test_both_addresses_checked_and_latest_selected(self):
        urls = release_checker.RELEASE_API_URLS
        for versions in (('v1.5.14', 'v1.5.15'), ('v1.5.16', 'v1.5.15')):
            with self.subTest(versions=versions):
                results = {url: ReleaseInfo(version, url, version)
                           for url, version in zip(urls, versions)}
                with self.fetch_with(results) as fetch:
                    release = release_checker.fetch_latest_release()
                self.assertEqual(release.version, max(versions, key=release_checker.parse_version))
                self.assertCountEqual([call.args[0] for call in fetch.call_args_list], urls)

    def test_either_address_can_fail(self):
        urls = release_checker.RELEASE_API_URLS
        for failed in urls:
            results = {url: OSError('404') if url == failed else ReleaseInfo('v1.5.15', url, '')
                       for url in urls}
            with self.fetch_with(results):
                self.assertEqual(release_checker.fetch_latest_release().version, 'v1.5.15')

    def test_both_fail_returns_no_update(self):
        with self.fetch_with({url: OSError('offline') for url in release_checker.RELEASE_API_URLS}):
            self.assertIsNone(release_checker.get_available_update('1.5.14'))

    def test_invalid_version_does_not_override_stable_release(self):
        urls = release_checker.RELEASE_API_URLS
        with self.fetch_with({urls[0]: ReleaseInfo('v1.5.15', '', ''),
                              urls[1]: ReleaseInfo('v99.0.0-rc.1', '', '')}):
            self.assertEqual(release_checker.fetch_latest_release().version, 'v1.5.15')

    def test_same_version_prefers_existing_address(self):
        urls = release_checker.RELEASE_API_URLS
        results = {url: ReleaseInfo('v1.5.15', url, '') for url in urls}
        with self.fetch_with(results):
            self.assertIs(release_checker.fetch_latest_release(), results[urls[0]])

    def test_custom_address_is_not_replaced(self):
        url = 'https://example.test/releases/latest'
        with self.fetch_with({url: ReleaseInfo('v1.5.15', url, '')}) as fetch:
            self.assertEqual(release_checker.fetch_latest_release(url).url, url)
        fetch.assert_called_once_with(url)


class DownloadAddressTest(unittest.TestCase):
    def release(self, repo, package):
        name = f'{package}-v1.5.15.zip'
        assets = tuple({'name': asset, 'browser_download_url':
                        f'https://github.com/{repo}/releases/download/v1.5.15/{asset}'}
                       for asset in (name, name + '.sha256.txt'))
        return ReleaseInfo('v1.5.15', '', '', assets=assets)

    def test_both_package_formats_on_both_repositories(self):
        for repo in ('pelierze/SecretShopBot-E7', 'pelierze/EAB'):
            for package in ('SecretShopBot-E7', 'EAB'):
                with self.subTest(repo=repo, package=package):
                    self.assertEqual(release_assets(self.release(repo, package))[0], f'{package}-v1.5.15.zip')

    def test_unapproved_and_mixed_repository_addresses_rejected(self):
        release = self.release('pelierze/EAB', 'EAB')
        original = release.assets[0]['browser_download_url']
        for url in (original.replace('pelierze/EAB', 'someone/EAB'),
                    original.replace('pelierze/EAB', 'pelierze/EAB-other'),
                    original.replace('github.com', 'github.com.evil.test'),
                    original.replace('/v1.5.15/', '/v1.5.14/'),
                    original.replace('/v1.5.15/', '/v1.5.15/extra/'),
                    original + '?redirect=elsewhere'):
            with self.subTest(url=url):
                release.assets[0]['browser_download_url'] = url
                with self.assertRaises(ValueError):
                    release_assets(release)
        release.assets[0]['browser_download_url'] = original.replace('pelierze/EAB', 'pelierze/SecretShopBot-E7')
        with self.assertRaisesRegex(ValueError, '저장소'):
            release_assets(release)


class RemoteAddressTest(unittest.TestCase):
    def sources(self):
        return ((auto_update, auto_update.SettingsUpdater, auto_update.UPDATE_URLS, 'update_url'),
                (remote_script, remote_script.RemoteScriptUpdater, remote_script.SCRIPT_URLS, 'script_url'))

    def test_missing_or_invalid_legacy_data_falls_back_to_new_address(self):
        for module, cls, urls, attribute in self.sources():
            for first in (OSError('404'), {'schema_version': 99}):
                with self.subTest(module=module.__name__, first=first):
                    updater = cls()
                    with patch.object(module, 'fetch_json', side_effect=[first, {'schema_version': 1}]) as fetch, \
                            patch.object(updater, 'save_cache') as save:
                        data, source = updater.load()
                    self.assertEqual(source, 'remote')
                    self.assertEqual(data['schema_version'], 1)
                    self.assertEqual([call.args[0] for call in fetch.call_args_list], list(urls))
                    save.assert_called_once_with(data)

    def test_working_legacy_address_does_not_need_extra_request(self):
        for module, cls, urls, attribute in self.sources():
            updater = cls()
            with patch.object(module, 'fetch_json', return_value={'schema_version': 1}) as fetch, \
                    patch.object(updater, 'save_cache'):
                self.assertEqual(updater.load()[1], 'remote')
            fetch.assert_called_once_with(urls[0])

    def test_both_fail_still_uses_cache_and_bundled_data(self):
        for module, cls, urls, attribute in self.sources():
            updater = cls()
            for fallback, data in (('cache', [{'schema_version': 1}]),
                                   ('bundled', [None, {'schema_version': 1}]),
                                   ('default', [None, None])):
                with self.subTest(module=module.__name__, fallback=fallback), \
                        patch.object(module, 'fetch_json', side_effect=OSError('offline')) as fetch, \
                        patch.object(module, 'read_json', side_effect=data):
                    self.assertEqual(updater.load()[1], fallback)
                    self.assertEqual(fetch.call_count, 2)

    def test_custom_address_is_not_replaced(self):
        for module, cls, urls, attribute in self.sources():
            url = 'https://example.test/config.json'
            updater = cls(url)
            with patch.object(module, 'fetch_json', return_value={'schema_version': 1}) as fetch, \
                    patch.object(updater, 'save_cache'):
                self.assertEqual(updater.load()[1], 'remote')
            fetch.assert_called_once_with(url)


if __name__ == '__main__':
    unittest.main()
