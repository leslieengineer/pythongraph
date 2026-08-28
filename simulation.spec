# -*- mode: python ; coding: utf-8 -*-
import os

# Tự động lấy đường dẫn tuyệt đối của thư mục hiện tại
spec_dir = os.path.abspath(SPECPATH)
icon_file = os.path.join(spec_dir, 'app_icon.ico')

a = Analysis(
    ['main.py'],
    pathex=[spec_dir],
    binaries=[],
    datas=[(icon_file, '.')],  # Gói file icon vào thư mục gốc của .exe
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='simulation',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,  # Gắn logo cho file .exe
)