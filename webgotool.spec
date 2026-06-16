# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('resources/*', 'resources')],
    hiddenimports=['playwright.sync_api', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets', 'ui', 'ui.mainwindow', 'ui.workflow_editor', 'browser', 'browser.chrome_manager', 'browser.cdp_client', 'browser.browser_worker', 'recorder', 'recorder.event_recorder', 'player', 'player.workflow_runner', 'flows', 'flows.schema', 'utils', 'utils.logger', 'utils.selector_utils'],
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
    name='WebGoTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
