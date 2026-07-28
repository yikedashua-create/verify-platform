"""Playwright session 管理(半自动版)

只负责:启 Chromium + 加载 storage_state + 保存 storage_state
不管登录:登录由 xiamenair.verify_ticket 自己管(login_interactive 等用户过码)
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional

from loguru import logger
from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from .config import PlaywrightConfig
from .models import Account


class SessionExpiredError(RuntimeError):
    """登录态失效(被踢回登录页 / cookie 过期)"""


class SessionManager:
    """Playwright session 生命周期管理

    用法:
        sm = SessionManager(pw_cfg=pw_cfg, account=acc)
        with sm.open() as page:
            # 用 page 操作
            ...
        # 退出时,sm.account.cookie_json 自动更新

    注:本类只管浏览器启停 + cookie 加载/保存,**不管登录**
    登录由调用方在 with 块里自己管(xiamenair.verify_ticket 负责)
    """

    def __init__(
        self,
        pw_cfg: PlaywrightConfig,
        account: Account,
    ):
        self.pw_cfg = pw_cfg
        self.account = account
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._storage_state: Optional[dict[str, Any]] = None

    def _ensure_dirs(self) -> None:
        Path(self.pw_cfg.screenshot_dir).mkdir(parents=True, exist_ok=True)

    def load_storage_state(self) -> Optional[dict[str, Any]]:
        """从 account 读 storage_state(供调用方判断是否要重新登录)"""
        if not self.account.cookie_json:
            return None
        try:
            return json.loads(self.account.cookie_json)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[session] 账号 {self.account.phone} cookie 解析失败: {e}")
            return None

    def _get_ua(self) -> str:
        from .config import get_config
        cfg = get_config()
        if cfg.xiamenair:
            return cfg.xiamenair.user_agent
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )

    def _screenshot(self, page: Page, tag: str) -> None:
        if not self.pw_cfg.screenshot_on_error:
            return
        self._ensure_dirs()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(self.pw_cfg.screenshot_dir) / f"{self.account.phone}_{ts}_{tag}.png"
        try:
            page.screenshot(path=str(path), full_page=True)
            logger.info(f"[session] 截图已存: {path}")
        except Exception as e:
            logger.warning(f"[session] 截图失败: {e}")

    @contextmanager
    def open(self) -> Iterator[Page]:
        """打开 session,返回 page

        退出 with 块时,自动保存 storage_state 到 self.account.cookie_json
        """
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(
                headless=self.pw_cfg.headless,
                slow_mo=self.pw_cfg.slow_mo,
            )
            ctx_args: dict[str, Any] = {
                "user_agent": self._get_ua(),
                "viewport": {"width": 1280, "height": 800},
                "locale": "zh-CN",
                "timezone_id": "Asia/Shanghai",
                "ignore_https_errors": True,
            }
            storage_state = self.load_storage_state()
            if storage_state:
                ctx_args["storage_state"] = storage_state
                logger.debug(f"[session] 账号 {self.account.phone} 加载已有 cookie")

            self._context = self._browser.new_context(**ctx_args)
            page = self._context.new_page()

            try:
                yield page
            finally:
                # 退出前保存 storage_state
                try:
                    self._storage_state = self._context.storage_state()
                    self.account.cookie_json = json.dumps(self._storage_state, ensure_ascii=False)
                    self.account.cookie_expires_at = datetime.now() + timedelta(days=7)
                    logger.debug(f"[session] 已保存 {self.account.phone} 新 cookie")
                except Exception as e:
                    logger.warning(f"[session] 保存 storage_state 失败: {e}")
                try:
                    self._context.close()
                except Exception:
                    pass
                try:
                    self._browser.close()
                except Exception:
                    pass
        finally:
            try:
                if self._pw:
                    self._pw.stop()
            except Exception:
                pass

    def screenshot(self, page: Page, tag: str) -> None:
        """公开给业务层用(失败时截图)"""
        self._screenshot(page, tag)

    def get_storage_state(self) -> Optional[dict[str, Any]]:
        """获取最新 storage_state"""
        return self._storage_state


# ============================================================
# 工具函数
# ============================================================

def parse_storage_state(s: str | bytes) -> Optional[dict[str, Any]]:
    if isinstance(s, bytes):
        s = s.decode("utf-8")
    if not s:
        return None
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None


def dump_storage_state(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False)
