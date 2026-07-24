# -*- mode: python ; coding: utf-8 -*-
"""Minimal PyInstaller spec — fast build."""

from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ['reasonix/cli/cli.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=(
        collect_submodules('reasonix')
        + collect_submodules('langchain_mcp_adapters')
    ),
    excludes=['tkinter', 'test', 'unittest', 'pytest', '_pytest', 'py', 'lxml',
              'setuptools', 'pip', 'pkg_resources',
              'jaraco', 'importlib_metadata', 'zipp',
              'matplotlib', 'numpy', 'pandas', 'PIL', 'cv2', 'scipy', 'sympy',
              'notebook', 'jupyter', 'ipython'],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='reasonix',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
