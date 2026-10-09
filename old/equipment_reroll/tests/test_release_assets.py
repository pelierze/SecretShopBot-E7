import shutil
import tempfile
import unittest
from pathlib import Path
from build_support.release_assets import used_images, collect_runtime_files, validate_package, RUNTIME_FILES

ROOT = Path(__file__).resolve().parents[1]


class ReleaseAssetsTests(unittest.TestCase):
    def test_unused_captures_excluded_but_dynamic_registries_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for source in (ROOT/'src').rglob('*'):
                if source.suffix in ('.py','.json'):
                    target = root/source.relative_to(ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
            shutil.copyfile(ROOT/'remote_script.json', root/'remote_script.json')
            for name in used_images(ROOT):
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            unused = ['images/buttons/unused.png', 'images/chaos/raw/unused.png',
                      'images/chaos/hero_selection/templates/heroes/unused.png']
            dynamic = ['images/chaos/node_progression/templates/blocked_choices/new_block.png',
                       'images/chaos/node_progression/templates/classes/class_new.png']
            for name in unused+dynamic:
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            result = set(used_images(root))
            self.assertFalse(result.intersection(unused))
            self.assertTrue(set(dynamic).issubset(result))
            (root/'images/chaos/hero_selection/templates/themes/select_supply_1.png').unlink()
            with self.assertRaises(FileNotFoundError): used_images(root)


class RuntimePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.internal = self.root / '_internal'
        for name in ('SecretShopBot-E7.exe', 'SecretShopBot-Updater.exe'):
            (self.root / name).touch()
        names = list(RUNTIME_FILES) + used_images(ROOT) + [
            'update_config.json', 'remote_script.json',
            'src/chaos/recruitment_layout.json', 'src/chaos/node_layout.json',
        ]
        for name in names:
            path = self.internal / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()

    def test_runtime_package_retains_license_and_image_dependencies(self):
        validate_package(self.root)
        self.assertTrue((self.internal / 'assets/ocr/LICENSE-RapidOCR.txt').is_file())

    def test_missing_executable_model_image_and_config_are_rejected(self):
        for name in ('SecretShopBot-Updater.exe',
                     '_internal/assets/ocr/korean_PP-OCRv4_rec_mobile.onnx',
                     '_internal/' + used_images(ROOT)[0],
                     '_internal/src/chaos/node_layout.json'):
            path = self.root / name
            path.unlink()
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_package(self.root)
            path.touch()

    def test_development_files_and_video_library_are_rejected(self):
        for name in ('README.md', '_internal/tools/run_gui_preview.sh',
                     '_internal/assets/ocr/README.md',
                     '_internal/images/equipment_options/README.txt',
                     '_internal/cv2/opencv_videoio_ffmpeg_test.dll',
                     '_internal/docs/review.md'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_package(self.root)
            path.unlink()
            if path.parent.name == 'docs':
                path.parent.rmdir()

    def test_collection_fails_if_required_adb_library_is_missing(self):
        paths = collect_runtime_files(ROOT)
        self.assertEqual(len(paths), len(RUNTIME_FILES))
        (self.internal / 'tools/adb/AdbWinApi.dll').unlink()
        with self.assertRaises(FileNotFoundError):
            collect_runtime_files(self.internal)
