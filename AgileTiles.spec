# -*- mode: python ; coding: utf-8 -*-
from core.plugin_system.host_environment import HOST_DISTRIBUTIONS
from os.path import dirname
import os
from PyInstaller.building.datastruct import Tree
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    copy_metadata,
)
from PyInstaller.utils.hooks.qt import pyside6_library_info

from tools.build_support.pyinstaller_pruning import prune_qt_binaries, prune_qt_data


# Kept as a compatibility input for existing build scripts. Both profiles now
# use the same small WebView2 host and no longer carry QtWebEngine.
BUILD_PROFILE = os.environ.get("AGILE_TILES_BUILD_PROFILE", "full").strip().lower()
if BUILD_PROFILE not in {"full", "lite"}:
    raise ValueError("AGILE_TILES_BUILD_PROFILE must be 'full' or 'lite'.")


def source_tree(root):
    tree = Tree(
        root,
        prefix=root,
        excludes=['__pycache__', '*.pyc', '*.pyo'],
    )
    return [(source, dirname(target) or '.') for target, source, _ in tree]


datas = source_tree('resources') + source_tree('plugins') + [('VERSION', '.')]


def collect_webview2_plugin():
    """Collect the native WebView2 backend omitted by PyInstaller's hook."""
    _, module_binaries, _ = pyside6_library_info.collect_module(
        'PySide6.QtWebView'
    )
    return [
        entry
        for entry in module_binaries
        if os.path.basename(str(entry[0])).casefold() == 'qtwebview_webview2.dll'
    ]


for distribution in HOST_DISTRIBUTIONS:
    datas += copy_metadata(distribution)
binaries = collect_dynamic_libs('qfluentwidgets') + collect_webview2_plugin()
hiddenimports = [
    'aiohttp',
    'base64',
    'core.web_ui.factory',
    'core.web_ui.contracts',
    'core.plugin_system.plugin_base',
    'core.data_layer.json_store',
    'core.security',
    'ctypes',
    'mimetypes',
    'paramiko',
    'random',
    're',
    'shutil',
    'sqlite3',
    'string',
    'subprocess',
    'tempfile',
    'uuid',
    'zipfile',
]
hiddenimports += [
    'core.web_ui.web_plugin_host',
    'core.web_ui.runtime',
    'PySide6.QtWebView',
]
datas += collect_data_files('qfluentwidgets')

excluded_modules = [
    'PySide6.Qt3DAnimation',
    'PySide6.Qt3DCore',
    'PySide6.Qt3DExtras',
    'PySide6.Qt3DInput',
    'PySide6.Qt3DLogic',
    'PySide6.Qt3DRender',
    'PySide6.QtCharts',
    'PySide6.QtDataVisualization',
    'PySide6.QtGraphs',
    'PySide6.QtLocation',
    'PySide6.QtMultimedia',
    'PySide6.QtMultimediaWidgets',
    'PySide6.QtOpenGL',
    'PySide6.QtOpenGLWidgets',
    'PySide6.QtPdf',
    'PySide6.QtQml',
    'PySide6.QtQuick',
    'PySide6.QtQuickWidgets',
    'PySide6.QtQuick3D',
    'PySide6.QtQuickTest',
    'PySide6.QtRemoteObjects',
    'PySide6.QtScxml',
    'PySide6.QtSensors',
    'PySide6.QtSerialPort',
    'PySide6.QtTextToSpeech',
    'PIL.AvifImagePlugin',
    'PIL.WebPImagePlugin',
    'PIL.ImageCms',
    'PIL.ImageTk',
    'PIL.ImageWin',
    'PySide6.QtWebChannel',
    'PySide6.QtWebSockets',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineQuick',
]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excluded_modules + ['qfluentwidgets.multimedia'],
    noarchive=False,
    optimize=0,
)
a.binaries = prune_qt_binaries(a.binaries)
a.datas = prune_qt_data(a.datas)
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
