# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec - 打包 verify-platform 为单文件 .exe

使用: pyinstaller build.spec
产物: dist/客票验真.exe (约 200-300 MB,含 Playwright chromium)
"""
import sys
import os
from pathlib import Path

block_cipher = None

# ============================
# 数据文件收集
# ============================
# 1. 整个 airlines/ 目录
datas = [('airlines', 'airlines')]

# 2. .streamlit 配置目录
if Path('.streamlit').exists():
    datas.append(('.streamlit', '.streamlit'))

# 3. Playwright 浏览器二进制 (chromium + headless_shell + ffmpeg)
# 路径: %LOCALAPPDATA%\ms-playwright\chromium-XXXX\chrome-win\
import glob
import os as _os
playwright_browsers = _os.environ.get('LOCALAPPDATA', '') + r'\ms-playwright'
if _os.path.isdir(playwright_browsers):
    for chromium_dir in glob.glob(_os.path.join(playwright_browsers, 'chromium-*')):
        if _os.path.isdir(chromium_dir):
            # 拷贝整个 chromium 目录
            target_name = _os.path.basename(chromium_dir)
            datas.append((chromium_dir, target_name))
            print(f"  [spec] Including Playwright chromium: {target_name}")

# 4. collect streamlit/altair/etc 的数据
from PyInstaller.utils.hooks import collect_data_files
datas += collect_data_files('streamlit', include_py_files=False)
datas += collect_data_files('altair')
datas += collect_data_files('plotly')

# ============================
# 隐藏 import
# ============================
hiddenimports = [
    'streamlit',
    'streamlit.web',
    'streamlit.runtime',
    'streamlit.components',
    'playwright',
    'playwright.sync_api',
    'requests',
    'urllib3',
    'certifi',
    'pandas',
    'numpy',
    'PIL',
    'pytz',
    'dateutil',
    'jsonschema',
    'packaging',
    'toml',
    'sqlite3',
    'email',
    'http',
    'asyncio',
    'concurrent',
    'logging',
    'socket',
    'ssl',
    'subprocess',
    'threading',
    'webbrowser',
    'urllib',
    'json',
    'pathlib',
    'tempfile',
    'shutil',
    'zipfile',
    'glob',
    'fnmatch',
    'platform',
    'ctypes',
]

# ============================
# Analysis
# ============================
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除大库,减体积
        'tkinter',
        'test',
        'unittest',
        'pydoc',
        'doctest',
        'matplotlib',
        'scipy',
        'sympy',
        'pytest',
        'IPython',
        'notebook',
        'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ============================
# EXE - 单文件
# ============================
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='客票验真',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,         # 留 console 让用户看启动日志
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,            # 可以加 .ico 图标
)
