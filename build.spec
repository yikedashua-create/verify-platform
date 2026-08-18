# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec - 打包 verify-platform 为单文件 .exe

使用: pyinstaller build.spec
产物: dist/客票验真.exe (约 200-300 MB,含 Playwright chromium)
"""
import sys
import os
from pathlib import Path

# 2026-08-17 修: build.yml 传 APP_VERSION 给 PyInstaller step,
# 但 PyInstaller 不会把 env 烤进 exe (env 是 runtime 的,不是 build 时的)
# → 同事跑 v1.0.4 的 exe 时 os.environ.get("APP_VERSION", "dev") 永远拿到 "dev"
# 修法: build 时把 APP_VERSION 写进 _embedded/version.txt,
#       runtime 从 sys._MEIPASS/_embedded/version.txt 读真实版本
APP_VERSION = os.environ.get("APP_VERSION", "dev").strip()
_EMBEDDED_DIR = os.path.join(os.path.dirname(SPEC), "_embedded")
os.makedirs(_EMBEDDED_DIR, exist_ok=True)
_VERSION_TXT = os.path.join(_EMBEDDED_DIR, "version.txt")
with open(_VERSION_TXT, "w", encoding="utf-8") as _f:
    _f.write(APP_VERSION)
print(f"  [spec] Baked APP_VERSION = {APP_VERSION}  ->  {_VERSION_TXT}")

# 2026-08-12 GitHub Actions runner 修复: stdout 默认 cp1252,build.spec 里 print 中文
# 直接 UnicodeEncodeError。强制 reconfigure utf-8 (errors='replace' 兜底异常字符)
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# 2026-08-12 GitHub Actions runner 修复: 跨平台 site-packages 路径
# 之前 hardcoded `D:\pycharm3\.venv\Lib\site-packages\...` 在 CI runner 上不存在
# runner 实际路径: C:\hostedtoolcache\windows\Python\3.11.9\x64\Lib\site-packages\
# 用 site.getsitepackages() 一次拿全
import site as _site
_SITE_PACKAGES_DIRS = [p for p in _site.getsitepackages() if os.path.isdir(p)]
# 兜底: 直接从 sys.executable parent 推 (venv 结构: Scripts/python.exe + Lib/site-packages/)
if not _SITE_PACKAGES_DIRS:
    _exe_parent = os.path.dirname(sys.executable)
    for cand in [
        os.path.join(_exe_parent, 'Lib', 'site-packages'),         # Windows venv
        os.path.join(_exe_parent, 'lib', 'python3.11', 'site-packages'),  # Linux
        os.path.join(_exe_parent, '..', 'Lib', 'site-packages'),    # Windows 相对
    ]:
        if os.path.isdir(cand):
            _SITE_PACKAGES_DIRS.append(os.path.abspath(cand))
            break

block_cipher = None

# ============================
# 数据文件收集
# ============================
# 0. app.py (Streamlit 入口,主入口 main.py 运行时用 runpy 调它)
datas = [('app.py', '.')]

# 1. 整个 airlines/ 目录
datas.append(('airlines', 'airlines'))

# 1.1 xm_mf_verify 目录(2026-07-28 接入,MF 自动验真)
# 这是从 xm-mf-ticket-verify 拷过来的整个包,内含 MF 订单详情自动化
if Path('xm_mf_verify').exists():
    datas.append(('xm_mf_verify', 'xm_mf_verify'))
    print("  [spec] Including xm_mf_verify (MF 自动验真)")

# 2. .streamlit 配置目录
if Path('.streamlit').exists():
    datas.append(('.streamlit', '.streamlit'))

# 3. streamlit 的 dist-info (importlib.metadata 需要!)
# 否则 streamlit/version.py 调 importlib.metadata.version('streamlit') 会报错
import glob
for _sp in _SITE_PACKAGES_DIRS:
    for dist_info in glob.glob(os.path.join(_sp, 'streamlit-*.dist-info')):
        target = os.path.basename(dist_info)
        datas.append((dist_info, target))
        print(f"  [spec] Including streamlit dist-info: {target}")

# 4. 其他依赖的 dist-info (有些库也用 importlib.metadata)
for pkg_name in ['altair', 'pandas', 'numpy', 'requests', 'urllib3', 'certifi', 'packaging', 'toml', 'Jinja2', 'MarkupSafe', 'pyarrow']:
    for _sp in _SITE_PACKAGES_DIRS:
        for m in glob.glob(os.path.join(_sp, f'{pkg_name}-*.dist-info')):
            target = os.path.basename(m)
            if not any(d[1] == target for d in datas):
                datas.append((m, target))
                print(f"  [spec] Including {target}")

# 3. Playwright 浏览器二进制 (chromium + headless_shell + ffmpeg)
# 路径: %LOCALAPPDATA%\ms-playwright\chromium-XXXX\chrome-win\
# ⚠️ 2026-08-08 修复 ticket_generator.png 生成报错:
#    Playwright p.chromium.launch() 默认走 chromium_headless_shell-XXXX
#    (更小),只拷 chromium-XXXX 找不到,需要同时拷 chromium_headless_shell-XXXX
#    main.py 启动时一次性解压到 %LOCALAPPDATA%\ms-playwright\ + 设环境变量
import glob
import os as _os
playwright_browsers = _os.environ.get('LOCALAPPDATA', '') + r'\ms-playwright'
if _os.path.isdir(playwright_browsers):
    for browser_dir in glob.glob(_os.path.join(playwright_browsers, 'chromium*')):
        # 匹配 chromium-XXXX 和 chromium_headless_shell-XXXX
        if _os.path.isdir(browser_dir):
            target_name = _os.path.basename(browser_dir)
            datas.append((browser_dir, target_name))
            print(f"  [spec] Including Playwright browser: {target_name}")

# 4. collect streamlit/altair/etc 的数据
from PyInstaller.utils.hooks import collect_data_files
datas += collect_data_files('streamlit', include_py_files=False)
datas += collect_data_files('altair')
datas += collect_data_files('plotly')

# 5. 嵌入版本号文件 (2026-08-17 加, runtime 从 sys._MEIPASS/_embedded/version.txt 读)
datas.append((_VERSION_TXT, "_embedded"))

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
    # === 2026-07-28 xm-mf-ticket-verify 接入 ===
    'xm_mf_verify',  # 主包
    'xm_mf_verify.captcha',  # ddddocr 识别
    'xm_mf_verify.xiamenair',  # MF 业务逻辑
    'xm_mf_verify.session',  # Playwright session
    'xm_mf_verify.config',  # 配置
    'xm_mf_verify.db',  # SQLite
    'xm_mf_verify.models',  # Pydantic models
    'xm_mf_verify.batch',  # 批量
    'ddddocr',  # 验证码 OCR(独立库)
    'ddddocr.tools',  # ddddocr 内部 tools
    'onnxruntime',  # ddddocr 底层依赖
    'loguru',  # 日志(xm_mf_verify 用了)
    'yaml',  # xm_mf_verify.config 用了
    'pydantic',  # xm_mf_verify.models 用了(已从 excludes 移出)
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
    runtime_hooks=['runtime_hook_pil.py'],  # 2026-08-10 PIL lazy __init__ 修复
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
        # ⚠️ 2026-08-10 不能再 exclude PIL!
        # streamlit st.image() 内部要 PIL 解析图片
        # 之前排除导致 "ModuleNotFoundError: No module named 'PIL'"
        # 'PIL',
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
        # ⚠️ 2026-07-28 不再 exclude pydantic 和 fastapi
        # 因为 xm-mf-ticket-verify 接入后,这两个库会被实际 import
        # 'pydantic',
        # 'fastapi',
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
    name='verify-platform',  # 2026-08-16 改 ASCII: GitHub Release UI "Attach binaries" 不保留中文文件名, 强制改 'default', 触发 auto_updater asset name mismatch 警告. 改 ASCII 后 .exe 干净, 用户下载也清晰.
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
