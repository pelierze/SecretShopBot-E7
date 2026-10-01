"""Release image dependencies. Raw captures are included only when referenced."""
import ast
import json
from pathlib import Path


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def source_images(path):
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    return {node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value.lower().endswith('.png')}


def used_images(root):
    root = Path(root)
    used = set()
    node = json.loads((root/'src/chaos/node_layout.json').read_text(encoding='utf-8'))
    used.update(m['file'] for m in node['markers'].values())
    rec = json.loads((root/'src/chaos/recruitment_layout.json').read_text(encoding='utf-8'))
    needed = {'start', 'unlock', 'confirm_theme', 'recruit_card', 'filter',
              'filter_panel', 'recruit_active', 'completed'}
    needed.update(e+'_2' for e in ('dark','fire','ice','forest','light'))
    for hero in rec['heroes'].values():
        role = rec['classes'][hero['class']]
        needed.update((role['anchor'],role['header'],hero['portrait'],hero['selected'],
                       hero['completed_name'],hero['element']+'_1'))
    used.update('images/chaos/hero_selection/'+rec['markers'][name]['file'] for name in needed)
    used.update(f'images/chaos/hero_selection/templates/themes/select_supply_{i}.png' for i in (1,2))
    # These directories are runtime registries, not development image dumps.
    for directory, pattern in [('blocked_choices','*.png'),('classes','class_*.png')]:
        used.update(p.relative_to(root).as_posix() for p in
                    (root/'images/chaos/node_progression/templates'/directory).glob(pattern))
    groups = {
        'images/buttons': ['src/secret_shop_bot.py','src/json_macro_engine.py'],
        'images/items': ['src/secret_shop_bot.py','src/json_macro_engine.py'],
        'images/penguin': ['src/penguin_bot.py'],
        'images/equipment_options': ['src/equipment_reroll_bot.py'],
        'images/2026_summer_event': ['src/event/events/2026_summer_event/observer.py'],
    }
    remote = json.loads((root/'remote_script.json').read_text(encoding='utf-8'))
    remote_names = {Path(s).name for s in strings(remote) if s.lower().endswith('.png')}
    for directory, modules in groups.items():
        names = {Path(s).name for module in modules for s in source_images(root/module)}
        if directory in ('images/buttons', 'images/items'):
            names |= remote_names
        used.update(p.relative_to(root).as_posix() for p in (root/directory).glob('*.png') if p.name in names)
    missing = sorted(name for name in used if not (root/name).is_file())
    if missing:
        raise FileNotFoundError('Missing release images: '+', '.join(missing))
    return sorted(used)


def collect_images(root):
    return [(str(Path(root)/name), str(Path(name).parent)) for name in used_images(root)]


RUNTIME_FILES = (
    'tools/adb/adb.exe',
    'tools/adb/AdbWinApi.dll',
    'tools/adb/AdbWinUsbApi.dll',
    'assets/ocr/korean_PP-OCRv4_rec_mobile.onnx',
    'assets/ocr/LICENSE-RapidOCR.txt',
)


def collect_runtime_files(root):
    root = Path(root)
    missing = [name for name in RUNTIME_FILES if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError('Missing runtime files: ' + ', '.join(missing))
    return [(str(root / name), str(Path(name).parent)) for name in RUNTIME_FILES]


def validate_package(root, source_root=None):
    root = Path(root)
    required = {'SecretShopBot-E7.exe', 'SecretShopBot-Updater.exe', '_internal'}
    if {p.name for p in root.iterdir()} != required:
        raise ValueError('Unexpected or missing release root entries')
    if not (root / '_internal').is_dir() or not all((root / name).is_file() for name in required - {'_internal'}):
        raise ValueError('Invalid runtime entry types')
    internal = root / '_internal'
    source_root = Path(source_root) if source_root is not None else Path(__file__).resolve().parents[1]
    expected_images = set(used_images(source_root))
    actual_images = {p.relative_to(internal).as_posix()
                     for p in (internal / 'images').rglob('*') if p.is_file()}
    if actual_images != expected_images:
        raise ValueError('Unexpected or missing runtime images')
    for name in (
        'update_config.json', 'remote_script.json',
        'src/chaos/recruitment_layout.json', 'src/chaos/node_layout.json',
    ):
        if not (internal / name).is_file():
            raise ValueError('Missing application data: ' + name)
    for directory in ('tools', 'assets/ocr'):
        expected = {name for name in RUNTIME_FILES if name.startswith(directory + '/')}
        actual = {p.relative_to(internal).as_posix() for p in (internal / directory).rglob('*') if p.is_file()}
        if actual != expected:
            raise ValueError('Unexpected or missing runtime files: ' + directory)
    for name in ('docs', 'tests', 'build', '.git', '__pycache__'):
        if any(p.name == name for p in internal.rglob('*') if p.is_dir()):
            raise ValueError('Development directory in release: ' + name)
    if list(internal.rglob('opencv_videoio_ffmpeg*.dll')):
        raise ValueError('Unused video backend in release')
    if any(p.suffix.lower() in {'.md', '.txt', '.ps1', '.sh', '.bat'}
           for p in (internal / 'images').rglob('*') if p.is_file()):
        raise ValueError('Image documentation in release')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--validate', required=True)
    validate_package(parser.parse_args().validate)
