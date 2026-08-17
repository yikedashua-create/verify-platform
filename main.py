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
# 首启 Playwright 浏览器落盘 (2026-08-08 修复 ticket_generator.png 报错)
# ============================================
def ensure_playwright_browsers():
    """exe 启动时把解压目录的 chromium 复制到 %LOCALAPPDATA%\\ms-playwright,
    并设置 PLAYWRIGHT_BROWSERS_PATH 环境变量。

    为什么不直接用解压目录:
      - PyInstaller 每次启动会重新解压到新的 _MEIXXXXXX 临时目录
      - 但要等用户实际调用 ticket_generator(或其他用 Playwright 的代码)时
        解压目录已经被清理,需要从其他位置获取浏览器
      - 复制到系统路径 = 一次复制,永久使用

    需要复制的目录:
      - chromium-XXXX (chrome.exe 全功能,可选)
      - chromium_headless_shell-XXXX (chrome-headless-shell.exe 轻量,默认用)
      - ffmpeg-XXXX (视频录制用,ticket_generator 不用但保险起见带上)
    """
    if not getattr(sys, "frozen", False):
        return  # 开发模式不动

    try:
        import shutil
        local_pw = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
        if not local_pw.parent.exists():
            return  # 没 LOCALAPPDATA 就算了

        # 需要复制的子目录 (只复制 exe 里有解压的)
        copied = []
        for sub in [
            "chromium-1217",
            "chromium_headless_shell-1217",
            "ffmpeg-1011",
        ]:
            src = BUNDLE_DIR / sub
            if not src.is_dir():
                continue
            dst = local_pw / sub
            if dst.is_dir():
                continue  # 已有就不复制
            local_pw.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
            copied.append(sub)
            print(f"  [init] Copied {sub} -> {dst}")

        if copied:
            print(f"  [init] {len(copied)} browser(s) installed to {local_pw}")
        else:
            print(f"  [init] Playwright browsers already present in {local_pw}")

        # 设环境变量,让 Playwright 找到
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_pw)
    except Exception as e:
        # 不要因为这个阻塞 streamlit 启动
        print(f"  [WARN] ensure_playwright_browsers failed: {type(e).__name__}: {e}")


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


def run_update_helper(old_path: str, new_path: str):
    """Helper 模式 (2026-08-17 加): app.py 触发一键更新时 spawn 的辅助进程
    流程: 等旧 exe 完全退出 → 删旧 exe → 把新 exe rename 到旧路径 → 启动新 exe → 退出

    为什么需要独立进程: Windows 不允许修改/删除正在运行的 exe
    必须先退出旧 exe (释放文件句柄) 才能替换
    """
    import shutil
    print(f"[update-helper] PID={os.getpid()}, parent={os.getppid()}")
    print(f"[update-helper] Old: {old_path}")
    print(f"[update-helper] New: {new_path}")

    # 等 5 秒让旧 Streamlit 完全退出 (os._exit 不走 atexit 清理,文件句柄立即释放)
    print("[update-helper] waiting 5s for parent Streamlit to exit...")
    time.sleep(5)

    # 删旧 exe (重试 30 次, Windows 文件锁释放有时慢)
    for i in range(30):
        try:
            if os.path.exists(old_path):
                os.remove(old_path)
            print(f"[update-helper] old exe removed")
            break
        except OSError as e:
            print(f"[update-helper] remove retry {i+1}/30: {e}")
            time.sleep(1)
    else:
        print(f"[update-helper] FAILED to remove old exe after 30 retries")
        sys.exit(1)

    # 把新 exe rename 到旧 exe 路径
    try:
        os.rename(new_path, old_path)
        print(f"[update-helper] renamed new -> old")
    except OSError as e:
        # 兜底: copy + remove
        print(f"[update-helper] rename failed: {e}, trying copy+remove...")
        shutil.copy2(new_path, old_path)
        try:
            os.remove(new_path)
        except OSError:
            pass

    # 启动新 exe
    print(f"[update-helper] launching new exe: {old_path}")
    subprocess.Popen([old_path], close_fds=True)
    print(f"[update-helper] done, exiting")


def main():
    # 2026-08-17 加: helper 模式分发
    # app.py 触发一键更新时 spawn 这个 process 来做 exe 替换
    # 模式: verify-platform.exe --_do_update <old_path> <new_path>
    if len(sys.argv) >= 4 and sys.argv[1] == '--_do_update':
        run_update_helper(sys.argv[2], sys.argv[3])
        return

    print("=" * 60)
    print("  Verify Platform  -  客票验真平台")
    print(f"  v{os.environ.get('APP_VERSION', '1.0.0')}  (c) 2026")
    print("=" * 60)
    print()
    print(f"  Bundle: {BUNDLE_DIR}")
    print(f"  App:    {APP_PATH}")
    print()

    try:
        # 0. 首启把 Playwright 浏览器落盘到 %LOCALAPPDATA% (2026-08-08 加)
        ensure_playwright_browsers()

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
