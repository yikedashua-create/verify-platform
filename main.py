"""客票验真平台 - 桌面端启动器

被 PyInstaller 打成 .exe 后的入口:
  1. 后台检查 GitHub Releases,有新版提示更新
  2. 启 streamlit run app.py
  3. 等 streamlit 起来后,自动开浏览器
  4. 等用户关闭浏览器/退出后,关 streamlit
"""
import os
import sys
import time
import subprocess
import webbrowser
import threading
from pathlib import Path


# ============================================
# 资源路径 (兼容 PyInstaller --onefile)
# ============================================
def get_bundle_dir() -> Path:
    """PyInstaller --onefile 解压的临时目录;开发模式为脚本所在目录"""
    if getattr(sys, "frozen", False):
        # PyInstaller 解压目录 (_MEIPASS)
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
    """启动一个 daemon 线程检查 GitHub 最新 release"""
    try:
        from auto_updater import check_and_notify
        check_and_notify()
    except Exception:
        pass


# ============================================
# 启动 streamlit 子进程
# ============================================
def start_streamlit() -> subprocess.Popen:
    """启 streamlit run app.py,返回子进程对象"""
    cmd = [
        sys.executable,        # .exe 自己(打包后) or python.exe (开发)
        "-m", "streamlit", "run", str(APP_PATH),
        "--server.port", str(PORT),
        "--server.headless", "true",
        "--server.address", "127.0.0.1",   # 仅本机访问 (单机软件)
        "--browser.gatherUsageStats", "false",
    ]

    # Windows 隐藏 streamlit 的 console 窗口
    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000
        creationflags = subprocess.CREATE_NO_WINDOW

    # streamlit 写到 stdout (用户看不到,只看到 console 关闭)
    return subprocess.Popen(
        cmd,
        creationflags=creationflags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


# ============================================
# 等 streamlit ready
# ============================================
def wait_for_streamlit(timeout: int = 30) -> bool:
    """等 streamlit 在 8501 listen,最多等 timeout 秒"""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.5)
    return False


# ============================================
# 主流程
# ============================================
def main():
    print("=" * 60)
    print("  Verify Platform  -  客票验真平台")
    print("  v1.0.0  (c) 2026")
    print("=" * 60)
    print()
    print(f"  Bundle: {BUNDLE_DIR}")
    print(f"  App:    {APP_PATH}")
    print()

    # 1. 启动后台更新检查
    threading.Thread(target=check_update_in_background, daemon=True).start()

    # 2. 启 streamlit
    print(f"  [1/3] Starting Streamlit on port {PORT} ...")
    proc = start_streamlit()

    # 3. 等 streamlit 起来
    print("  [2/3] Waiting for Streamlit to be ready ...")
    if not wait_for_streamlit(timeout=30):
        print("  [ERROR] Streamlit did not start in 30 seconds.")
        print("  Check your Python + Streamlit installation.")
        proc.terminate()
        input("\n  Press Enter to exit...")
        sys.exit(1)

    print(f"  [3/3] Streamlit ready. Opening browser at {URL}")

    # 4. 自动开浏览器
    webbrowser.open(URL)

    print()
    print("  Browser opened. The tool is ready to use.")
    print("  Close this window OR press Ctrl+C to stop the tool.")
    print()

    # 5. 阻塞,等 streamlit 退出(用户关闭浏览器/手动 kill)
    try:
        # 用 poll() 周期检查,不让主进程阻塞在 wait()
        while True:
            retcode = proc.poll()
            if retcode is not None:
                # streamlit 子进程自己退出了
                print(f"  Streamlit exited with code {retcode}.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        print("  Stopping Streamlit ...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("  Goodbye.")


if __name__ == "__main__":
    main()
