# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Collect all submodules from our local packages
_local_imports = []
for pkg in ['utils', 'ui', 'browser', 'recorder', 'player', 'flows']:
    _local_imports.extend(collect_submodules(pkg))

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('resources/*', 'resources'),
    ],
    hiddenimports=[
        'playwright.sync_api',
        'playwright._impl._api_structures',
        'playwright._impl._browser_type',
        'playwright._impl._connection',
        'playwright._impl._page',
        'playwright._impl._locator',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'pandas',
        'openpyxl',
        'numpy',
        'PIL',
    ] + _local_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'email',
        'http',
        'xmlrpc',
        'test',
        'setuptools',
        'pip',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WebGoTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_architecture='x86_64',
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
