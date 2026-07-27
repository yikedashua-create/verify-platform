"""客票验真平台 - 桌面端启动器

PyInstaller .exe 入口:
  1. 准备 sys.argv 调 streamlit.web.cli.main() (同进程内,不 spawn 子进程)
  2. 后台线程等 streamlit ready 后,自动开浏览器
  3. streamlit 退出时整个 .exe 退出

⚠️ 不能用 subprocess.Popen([sys.executable, "-m", "streamlit" ...]):
   PyInstaller onefile 模式下 sys.executable 指向 .exe 自己(不是 Python),
   那样会 .exe 自递归,streamlit 永远起不来。
"""
import os
import sys
import time
import threading
import webbrowser
from pathlib import Path


# ============================================
# 资源路径 (兼容 PyInstaller --onefile)
# ============================================
def get_bundle_dir() -> Path:
    """PyInstaller --onefile 解压的临时目录;开发模式为脚本所在目录"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    return Path(__file__).parent.resolve()


BUNDLE_DIR = get_bundle_dir()
APP_PATH = BUNDLE_DIR / "app.py"
PORT = 8501
URL = f"http://127.0.0.1:{PORT}"


# ============================================
# 后台检查更新
# ============================================
def check_update_in_background():
    try:
        from auto_updater import check_and_notify
        check_and_notify()
    except Exception:
        pass


# ============================================
# 等 streamlit ready
# ============================================
def wait_for_streamlit(timeout: int = 30) -> bool:
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.5)
    return False


def open_browser_when_ready():
    """后台线程:等 streamlit ready 后自动开浏览器"""
    print("  [2/3] Waiting for Streamlit to be ready ...")
    if not wait_for_streamlit(timeout=30):
        print("  [ERROR] Streamlit did not start in 30 seconds.")
        print("  Check console above for errors.")
        return

    print("  [3/3] Streamlit ready. Opening browser ...")
    time.sleep(1.5)

    # Windows 用 os.startfile (最稳)
    if sys.platform == "win32":
        try:
            os.startfile(URL)
            print(f"  [OK] Browser opened: {URL}")
            return
        except Exception as e:
            print(f"  [WARN] os.startfile failed: {e}")

    # 其他系统用 webbrowser
    try:
        webbrowser.open(URL)
        print(f"  [OK] Browser opened: {URL}")
    except Exception as e:
        print(f"  [ERROR] Could not open browser: {e}")
        print(f"  Please manually open: {URL}")


# ============================================
# 准备 streamlit 启动环境
# ============================================
def prepare_streamlit_env():
    """让 streamlit 找到自己的资源 (PyInstaller 解压目录)"""
    if getattr(sys, "frozen", False):
        # 让 cwd 切到解压目录,这样 streamlit 找到模板/静态文件
        os.chdir(BUNDLE_DIR)
        # 把解压目录加到 sys.path,这样 import 能找到
        if str(BUNDLE_DIR) not in sys.path:
            sys.path.insert(0, str(BUNDLE_DIR))


def main():
    print("=" * 60)
    print("  Verify Platform  -  客票验真平台")
    print(f"  v{os.environ.get('APP_VERSION', '1.0.0')}  (c) 2026")
    print("=" * 60)
    print()
    print(f"  Bundle: {BUNDLE_DIR}")
    print(f"  App:    {APP_PATH}")
    print()

    try:
        # 1. 准备 streamlit 运行环境
        prepare_streamlit_env()

        # 2. 启动后台更新检查
        threading.Thread(target=check_update_in_background, daemon=True).start()

        # 3. 启动后台线程:等 streamlit ready 后开浏览器
        threading.Thread(target=open_browser_when_ready, daemon=True).start()

        # 4. 配置 streamlit 命令行参数
        # ⚠️ streamlit 1.58+ PyInstaller freeze 模式默认开 global.developmentMode,
        #    不接受 --server.port (会抛 RuntimeError) — 用默认 port 8501
        # ⚠️ headless=true 必须保留(默认会尝试开浏览器,我们自己用 os.startfile)
        # ⚠️ global.developmentMode=false 显式关掉,确保未来如果加上 server.port 不报错
        sys.argv = [
            "streamlit",
            "run", str(APP_PATH),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
            "--global.developmentMode", "false",
        ]
        print(f"  [1/3] Starting Streamlit: streamlit run {APP_PATH.name}")
        print(f"        port={PORT} (default), headless=true")
        print()

        # 5. 直接调 streamlit.web.cli.main() 启 streamlit
        # (不能用 runpy.run_module("streamlit", run_name="__main__"),
        #  因为 PyInstaller 收集 streamlit 包时不会自动把 __main__.py 当入口)
        from streamlit.web import cli as stcli
        stcli.main()

    except KeyboardInterrupt:
        print()
        print("  Received Ctrl+C, stopping ...")
    except SystemExit as e:
        # streamlit 退出时正常抛 SystemExit(0)
        if e.code not in (0, None):
            print(f"  Streamlit exited with code {e.code}")
    except Exception as e:
        # 把所有错误打印出来
        import traceback
        print()
        print("  " + "=" * 56)
        print("  [ERROR] Streamlit failed to start")
        print("  " + "=" * 56)
        print(f"  Error: {e}")
        print()
        print("  Full traceback:")
        print()
        traceback.print_exc()
        print()
        print("  " + "=" * 56)
        print()

    # 不论成功失败,等用户按 Enter 才退出(让用户看错误)
    try:
        input("  Press Enter to close this window...")
    except (EOFError, KeyboardInterrupt):
        pass

    print("  Goodbye.")


if __name__ == "__main__":
    main()
