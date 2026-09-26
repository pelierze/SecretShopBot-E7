# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# 사용 중인 이미지만 선별 수집 (미사용 대용량 원본/스크린샷 및 백업 제외)
def collect_images():
    import json, re
    from pathlib import Path

    used = set()

    # 1. 노드 진행 설정 이미지
    nl_path = Path('src/chaos/node_layout.json')
    if nl_path.exists():
        nl = json.loads(nl_path.read_text(encoding='utf-8'))
        for k, v in nl.get('markers', {}).items():
            if 'file' in v:
                used.add(Path(v['file']).as_posix())

    # 2. 영웅 영입 설정 이미지
    rec_path = Path('src/chaos/recruitment_layout.json')
    if rec_path.exists():
        rec = json.loads(rec_path.read_text(encoding='utf-8'))
        rec_base = Path('images/chaos/hero_selection')
        for k, v in rec.get('markers', {}).items():
            if 'file' in v:
                used.add((rec_base / v['file']).as_posix())
        for theme in rec.get('themes', []):
            if 'file' in theme:
                used.add((rec_base / theme['file']).as_posix())
        for hero in rec.get('heroes', []):
            if 'file' in hero:
                used.add((rec_base / hero['file']).as_posix())

    # 3. 템플릿 폴더 이미지
    for p in Path('images/chaos/node_progression/templates').rglob('*.png'):
        used.add(p.as_posix())
    for p in Path('images/chaos/hero_selection/templates').rglob('*.png'):
        used.add(p.as_posix())

    # 4. 기본 봇 이미지 (버튼, 아이템, 장비, 펭귄, 이벤트)
    for folder in ['images/buttons', 'images/items', 'images/equipment_options', 'images/penguin', 'images/2026_summer_event']:
        for p in Path(folder).glob('*.png'):
            if not p.name.lower().endswith('_backup.png'):
                used.add(p.as_posix())

    # 5. 소스 코드에서 참조된 추가 이미지
    img_re = re.compile(r'images/[a-zA-Z0-9_/\\]+\.png')
    for p in Path('src').rglob('*'):
        if p.is_file() and p.suffix in ('.py', '.json'):
            txt = p.read_text(encoding='utf-8', errors='ignore')
            for m in img_re.finditer(txt):
                posix = Path(m.group(0)).as_posix()
                if Path(posix).exists() and not posix.lower().endswith('_backup.png'):
                    used.add(posix)

    datas = []
    for rel in sorted(used):
        src = os.path.normpath(rel)
        dst = os.path.dirname(src)
        datas.append((src, dst))
    return datas


def collect_icons():
    datas = []
    icon_root = os.path.join('assets', 'icons')
    for f in os.listdir(icon_root):
        if f.lower().endswith(('.ico', '.png')):
            datas.append((os.path.join(icon_root, f), icon_root))
    return datas


def collect_event_data():
    datas = []
    event_root = os.path.join('src', 'event', 'events')
    for root, dirs, files in os.walk(event_root):
        for f in files:
            if f.lower().endswith('.json'):
                datas.append((os.path.join(root, f), root))
    return datas


datas = collect_images() + collect_event_data() + [
    ('tools', 'tools'),
    ('images/equipment_options/README.txt', 'images/equipment_options'),
    ('update_config.json', '.'),
    ('remote_script.json', '.'),
    ('src/chaos/recruitment_layout.json', 'src/chaos'),
    ('src/chaos/node_layout.json', 'src/chaos'),
    ('assets/ocr', 'assets/ocr'),
] + collect_icons() + collect_data_files(
    'rapidocr_onnxruntime',
    includes=['config.yaml', 'models/*.onnx'],
)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'cv2', 'numpy', 'PIL', 'tkinter', 'rapidocr_onnxruntime',
    ] + collect_submodules('src.event.events.2026_summer_event'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pure-python-adb',
        'pytest',
        'torch',
        'torchvision',
        'torchaudio',
        'transformers',
        'tensorflow',
        'tensorboard',
        'av',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SecretShopBot-E7',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='assets/icons/app_icon_multi_size.ico',
    version='file_version_info.txt',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SecretShopBot-E7',
)
