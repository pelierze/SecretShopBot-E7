# -*- mode: python ; coding: utf-8 -*-

import os

# 백업 파일 제외하고 이미지 수집
def collect_images():
    datas = []
    for root, dirs, files in os.walk('images'):
        for f in files:
            if f.endswith('.png') and not f.endswith('_backup.png'):
                src = os.path.join(root, f)
                dst = root
                datas.append((src, dst))
    return datas


datas = collect_images() + [
    ('tools', 'tools'),
    ('update_config.json', '.'),
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['cv2', 'numpy', 'PIL', 'tkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pure-python-adb'],
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
