import shutil
import tempfile
import unittest
from pathlib import Path
from build_support.release_assets import used_images

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
