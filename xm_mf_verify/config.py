"""配置加载(半自动版)

读 config.yaml,转成 dataclass 给业务层用
简化:去掉 accounts 配置(账号从 CLI 入参来,不预填)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml


@dataclass
class XiamenairConfig:
    login_url: str = ""
    home_url: str = ""
    orders_url: str = ""
    booking_url_template: str = ""  # 订单详情 URL 模板,如 https://int-et.xiamenair.com/bookingManagement/displayBooking/list/{order_no}
    user_agent: str = ""


@dataclass
class PlaywrightConfig:
    headless: bool = False  # 半自动必须 False,人看浏览器
    slow_mo: int = 0
    screenshot_on_error: bool = True
    screenshot_dir: str = "data/screenshots"


@dataclass
class DbConfig:
    accounts_db: str = "data/accounts.db"
    results_db: str = "data/verify_results.db"


@dataclass
class LogConfig:
    level: str = "INFO"
    dir: str = "data/logs"
    rotation: str = "10 MB"
    retention: str = "30 days"


@dataclass
class ApiConfig:
    host: str = "127.0.0.1"
    port: int = 8765


@dataclass
class AppConfig:
    xiamenair: Optional[XiamenairConfig] = None
    playwright: PlaywrightConfig = field(default_factory=PlaywrightConfig)
    db: DbConfig = field(default_factory=DbConfig)
    log: LogConfig = field(default_factory=LogConfig)
    api: ApiConfig = field(default_factory=ApiConfig)

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """加载 config.yaml

    找不到文件时返回默认配置(headless=False,适合半自动)
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[2] / p

    if not p.exists():
        return AppConfig()

    with open(p, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    cfg = AppConfig()

    # 厦航
    xm = raw.get("xiamenair", {})
    if xm:
        cfg.xiamenair = XiamenairConfig(
            login_url=str(xm.get("login_url", "")),
            home_url=str(xm.get("home_url", "")),
            orders_url=str(xm.get("orders_url", "")),
            booking_url_template=str(
                xm.get(
                    "booking_url_template",
                    "https://int-et.xiamenair.com/bookingManagement/displayBooking/list/{order_no}",
                )
            ),
            user_agent=str(
                xm.get(
                    "user_agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                )
            ),
        )

    # Playwright
    pw = raw.get("playwright", {})
    if pw:
        cfg.playwright = PlaywrightConfig(
            headless=bool(pw.get("headless", False)),  # 半自动默认 False
            slow_mo=int(pw.get("slow_mo", 0)),
            screenshot_on_error=bool(pw.get("screenshot_on_error", True)),
            screenshot_dir=str(pw.get("screenshot_dir", "data/screenshots")),
        )

    # DB
    db = raw.get("db", {})
    if db:
        cfg.db = DbConfig(
            accounts_db=str(db.get("accounts_db", "data/accounts.db")),
            results_db=str(db.get("results_db", "data/verify_results.db")),
        )

    # Log
    lg = raw.get("log", {})
    if lg:
        cfg.log = LogConfig(
            level=str(lg.get("level", "INFO")),
            dir=str(lg.get("dir", "data/logs")),
            rotation=str(lg.get("rotation", "10 MB")),
            retention=str(lg.get("retention", "30 days")),
        )

    # API
    api = raw.get("api", {})
    if api:
        cfg.api = ApiConfig(
            host=str(api.get("host", "127.0.0.1")),
            port=int(api.get("port", 8765)),
        )

    return cfg


# 全局单例
_global_cfg: AppConfig | None = None


def get_config(path: str | Path = "config.yaml") -> AppConfig:
    global _global_cfg
    if _global_cfg is None:
        _global_cfg = load_config(path)
    return _global_cfg


def reset_config() -> None:
    global _global_cfg
    _global_cfg = None
