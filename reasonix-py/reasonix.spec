# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec — 打包 reasonix 为单个 exe。

用法：
    pip install pyinstaller
    pyinstaller reasonix.spec

输出: dist/reasonix.exe (~60MB，含 Python 3.12 + 全部依赖 + 源码)
"""

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['reasonix/__main__.py'],
    pathex=['.'],
    binaries=[],
    datas=[('reasonix/experiments/worker.py', 'reasonix/experiments')],
    hiddenimports=[
        'reasonix.cli',
        'reasonix.cli.cli',
        'reasonix.cli.chat_tui',
        'reasonix.boot',
        'reasonix.config',
        'reasonix.control.controller',
        'reasonix.agent.runner',
        'reasonix.agent.compose',
        'reasonix.event',
        'reasonix.provider',
        'reasonix.provider.openai',
        'reasonix.provider.anthropic',
        'reasonix.tool.base',
        'reasonix.tool.registry',
        'reasonix.tool.builtin',
        'reasonix.tool.builtin.bash',
        'reasonix.tool.builtin.readfile',
        'reasonix.tool.builtin.writefile',
        'reasonix.tool.builtin.grep',
        'reasonix.tool.builtin.web_fetch',
        'reasonix.tool.builtin.edit_file',
        'reasonix.tool.builtin.glob',
        'reasonix.tool.builtin.task',
        'reasonix.tool.builtin.ask',
        'reasonix.tool.builtin.todo_write',
        'reasonix.tool.builtin.complete_step',
        'reasonix.tool.builtin.remember',
        'reasonix.tool.builtin.forget',
        'reasonix.tool.builtin.move_file',
        'reasonix.tool.builtin.notebook_edit',
        'reasonix.tool.builtin.delete_range',
        'reasonix.memory',
        'reasonix.diff',
        'reasonix.permission.permission',
        'reasonix.guardian.guardian',
        'reasonix.secrets.redact',
        'reasonix.evidence',
        'reasonix.serve.server',
        'reasonix.desktop',
        'reasonix.grpc',
        'reasonix.grpc.client',
        'reasonix.grpc.security_pb2',
        'reasonix.grpc.security_pb2_grpc',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'test',
        'unittest',
        'setuptools',
        'pip',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='reasonix.ico' if Path('reasonix.ico').exists() else None,
)
