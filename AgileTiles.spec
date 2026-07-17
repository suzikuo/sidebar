# -*- mode: python ; coding: utf-8 -*-
from core.plugin_system.host_environment import HOST_DISTRIBUTIONS
from os.path import dirname
from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)


def source_tree(root):
    tree = Tree(
        root,
        prefix=root,
        excludes=['__pycache__', '*.pyc', '*.pyo'],
    )
    return [(source, dirname(target) or '.') for target, source, _ in tree]


datas = source_tree('plugins') + source_tree('ui') + [('VERSION', '.')]
for distribution in HOST_DISTRIBUTIONS:
    datas += copy_metadata(distribution)
binaries = collect_dynamic_libs('qfluentwidgets')
hiddenimports = [
    'aiohttp',
    'base64',
    'core.web_ui.factory',
    'core.web_ui.web_plugin_host',
    'core.plugin_system.plugin_base',
    'core.security',
    'ctypes',
    'mimetypes',
    'paramiko',
    'PySide6.QtWebChannel',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'random',
    're',
    'shutil',
    'sqlite3',
    'string',
    'subprocess',
    'tempfile',
    'uuid',
]
datas += collect_data_files('qfluentwidgets')
hiddenimports += collect_submodules('qfluentwidgets')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name='AgileTiles',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AgileTiles',
)
