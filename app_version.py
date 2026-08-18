"""运行时读取真实 APP_VERSION

为什么需要这个 (2026-08-17):
- build.yml 传 APP_VERSION 给 PyInstaller step (build-time env)
- PyInstaller 不会把 env 烤进 exe (env 是 runtime 的,不是 build 时的)
- 之前同事跑 v1.0.4 的 exe 时 os.environ.get("APP_VERSION", "dev") 永远拿到 "dev"
- 修法: build.spec 把 APP_VERSION 写进 _embedded/version.txt,用 --add-data 打进 exe
- runtime 从 sys._MEIPASS/_embedded/version.txt 读真实版本
- 优先级: 嵌入文件 > 环境变量 > dev
"""
import os
import sys
from pathlib import Path


def get_app_version() -> str:
    """读真实 APP_VERSION (从嵌入文件, 兜底 env var, 兜底 'dev')"""
    # 1. 嵌入文件 (PyInstaller onefile 时 sys._MEIPASS = 解压目录)
    if getattr(sys, "frozen", False):
        bundle_dir = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
        vf = bundle_dir / "_embedded" / "version.txt"
        if vf.is_file():
            try:
                v = vf.read_text(encoding="utf-8").strip()
                if v:
                    return v
            except Exception:
                pass

    # 2. 环境变量 (dev 模式 or CI 直接设了 env)
    env_v = os.environ.get("APP_VERSION", "").strip()
    if env_v:
        return env_v

    # 3. dev 模式
    return "dev"


APP_VERSION = get_app_version()
