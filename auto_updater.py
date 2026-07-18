"""自动更新检查

启动时后台线程调 GitHub API,如果有新 release 写到一个临时文件,
Streamlit 启动后 app.py 读这个文件,显示更新提示。
"""
import json
import os
import sys
import time
import tempfile
import urllib.request
import urllib.error

# GitHub repo (公开的,private 也行 - GitHub API 默认匿名访问 public 没问题)
GITHUB_API_URL = "https://api.github.com/repos/yikedashua-create/verify-platform/releases/latest"
UPDATE_FILE = os.path.join(tempfile.gettempdir(), "verify-platform-update.json")

# 当前版本 - 由 GitHub Actions 注入(开发模式用 "dev")
CURRENT_VERSION = os.environ.get("APP_VERSION", "dev")


def parse_version(v: str):
    """'1.0.0' -> (1, 0, 0);  'dev' -> (0,)"""
    if v == "dev":
        return (0,)
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


def check_and_notify():
    """检查 GitHub 最新 release,如果有新版写更新文件(给 app.py 读)"""
    try:
        # User-Agent 必须,GitHub API 拒绝无 UA 的请求
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={"User-Agent": "verify-platform-updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))

        latest = (data.get("tag_name") or "").lstrip("v")
        if not latest:
            return

        if parse_version(latest) <= parse_version(CURRENT_VERSION):
            return  # 已是最新

        # 找 Windows .exe asset
        for asset in data.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(".exe"):
                payload = {
                    "latest": latest,
                    "current": CURRENT_VERSION,
                    "url": asset.get("browser_download_url"),
                    "file": name,
                    "size_mb": round(asset.get("size", 0) / 1024 / 1024, 1),
                    "release_notes": data.get("body", ""),
                    "html_url": data.get("html_url"),
                }
                with open(UPDATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
                return

    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        # 网络问题 / GitHub 限流 / 解析失败 - 静默忽略
        return
    except Exception:
        return


def read_update_info() -> dict:
    """app.py 调用这个读更新信息"""
    if not os.path.exists(UPDATE_FILE):
        return None
    try:
        with open(UPDATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def clear_update_info():
    """用户点"忽略"后调用,删掉更新文件"""
    try:
        if os.path.exists(UPDATE_FILE):
            os.remove(UPDATE_FILE)
    except OSError:
        pass
