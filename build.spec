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
# 0. app.py (Streamlit 入口,主入口 main.py 运行时用 runpy 调它)
datas = [('app.py', '.')]

# 1. 整个 airlines/ 目录
datas.append(('airlines', 'airlines'))

# 2. .streamlit 配置目录
if Path('.streamlit').exists():
    datas.append(('.streamlit', '.streamlit'))

# 3. streamlit 的 dist-info (importlib.metadata 需要!)
# 否则 streamlit/version.py 调 importlib.metadata.version('streamlit') 会报错
import glob
for dist_info in glob.glob(r'D:\pycharm3\.venv\Lib\site-packages\streamlit-*.dist-info'):
    target = os.path.basename(dist_info)
    datas.append((dist_info, target))
    print(f"  [spec] Including streamlit dist-info: {target}")

# 4. 其他依赖的 dist-info (有些库也用 importlib.metadata)
for pkg_name in ['altair', 'pandas', 'numpy', 'requests', 'urllib3', 'certifi', 'packaging', 'toml', 'Jinja2', 'MarkupSafe', 'pyarrow']:
    matches = glob.glob(rf'D:\pycharm3\.venv\Lib\site-packages\{pkg_name}-*.dist-info')
    for m in matches:
        target = os.path.basename(m)
        if not any(d[1] == target for d in datas):
            datas.append((m, target))
            print(f"  [spec] Including {target}")

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
    'streamlit.runtime.scriptrunner',
    'streamlit.runtime.scriptrunner.magic_funcs',
    'streamlit.runtime.scriptrunner.exec_code',
    'streamlit.runtime.scriptrunner.magic',
    'streamlit.runtime.scriptrunner.script_cache',
    'streamlit.runtime.scriptrunner.script_runner',
    'streamlit.components',
    'uvicorn',  # streamlit 1.58+ web server 需要
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
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
    'h11',
    'sniffio',
    'anyio',
    'starlette',
    'fastapi',  # streamlit 内部 web server 用
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
        # 排除大库 / 跟项目无关的库,加速 build + 减体积
        # 只排除第三方库,别排除标准库(asyncio / concurrent / tkinter 等是必需的!)
        # 大科学库(没装也别扫)
        'tensorflow',
        'torch',
        'transformers',
        'sklearn',
        'scipy',
        'sympy',
        'matplotlib',
        'plotly',
        'pandas',  # 我们没直接用 pandas
        'PIL',
        'cv2',
        'IPython',
        'notebook',
        'jupyter',
        'pytest',
        'sphinx',
        # 跟项目无关的库
        'nltk',
        'datasets',
        'emoji',
        'soundfile',
        'librosa',
        'pydantic',
        'fastapi',
        # ⚠️ 不能再 exclude uvicorn! streamlit 1.58+ 内部 web server 依赖它
        # 之前排除导致 "ModuleNotFoundError: No module named 'uvicorn'"
        'sqlalchemy',
        'alembic',
        'twisted',
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
    upx=False,            # 关掉 UPX 压缩 (return code -3 解压错误的根因)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
