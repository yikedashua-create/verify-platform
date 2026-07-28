"""FastAPI HTTP 入口(半自动版)

⚠️ 安全提醒:
- 账号密码**不要**走 HTTP API(明文传输,日志暴露)
- 这个 API 主要给 dashboard 调,dashboard 跟工具**同机部署**

启动:python -m xm_mf_verify serve
"""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import FastAPI
from loguru import logger
from pydantic import BaseModel, Field

from .config import AppConfig
from .db import init_all, list_results
from .captcha import make_solver
from .xiamenair import verify_ticket


# ============================================================
# API 模型
# ============================================================

class VerifyRequest(BaseModel):
    order_no: str = Field(..., description="订单号(下单成功的订单号)")
    ticket_no: str = Field(default="", description="票号(可选,仅做记录)")
    account_phone: str = Field(..., description="白鹭会员手机号")
    captcha_mode: str = Field(
        default="auto",
        description="验证码模式: auto / ddddocr / manual",
    )
    # 密码**不**走 API(从环境变量 XM_MF_PWD_<phone> 读)


class VerifyResponse(BaseModel):
    ticket_no: str = ""
    order_no: str = ""
    status: str
    raw_status: str = ""
    queried_at: str
    account_phone: str = ""
    took_ms: int = 0
    error: str = ""


class HistoryItem(BaseModel):
    ticket_no: str
    order_no: str
    status: str
    raw_status: str
    queried_at: str
    account_phone: str
    took_ms: int
    error: str


# ============================================================
# app 工厂
# ============================================================

def _get_password_for_phone(phone: str) -> str:
    """从环境变量读密码(每个账号一个 env var)

    命名约定:XM_MF_PWD_<phone> = "your_password"
    例:set XM_MF_PWD_13800138000=mypwd
    """
    env_key = f"XM_MF_PWD_{phone}"
    return os.environ.get(env_key, "")


def create_app(cfg: AppConfig) -> FastAPI:
    app = FastAPI(
        title="xm-mf-ticket-verify",
        description="厦门航空(MF)白鹭会员半自动验真 — 弹浏览器,人过 4 位验证码,自动抓票状态",
        version="0.2.0",
    )

    @app.on_event("startup")
    def _startup():
        init_all(cfg.db.accounts_db, cfg.db.results_db)
        logger.info(f"[api] 启动: accounts={cfg.db.accounts_db}, results={cfg.db.results_db}")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": "0.2.0"}

    @app.post("/verify", response_model=VerifyResponse)
    def verify(req: VerifyRequest) -> VerifyResponse:
        # 密码从环境变量取
        password = _get_password_for_phone(req.account_phone)
        # 验证码 solver
        try:
            solver = make_solver(req.captcha_mode)
        except ValueError:
            solver = make_solver("auto")
        result = verify_ticket(
            order_no=req.order_no,
            ticket_no=req.ticket_no,
            account_phone=req.account_phone,
            account_password=password,
            cfg=cfg,
            accounts_db=cfg.db.accounts_db,
            captcha_solver=solver,
        )
        return VerifyResponse(
            ticket_no=result.ticket_no,
            order_no=result.order_no,
            status=str(result.status) if hasattr(result.status, "value") else result.status,
            raw_status=result.raw_status,
            queried_at=result.queried_at.isoformat() if hasattr(result.queried_at, "isoformat") else str(result.queried_at),
            account_phone=result.account_phone,
            took_ms=result.took_ms,
            error=result.error,
        )

    @app.get("/history/{order_no}", response_model=list[HistoryItem])
    def history(
        order_no: str,
        account_phone: Optional[str] = None,
        limit: int = 20,
    ) -> list[HistoryItem]:
        rows = list_results(
            cfg.db.results_db,
            order_no=order_no,
            account_phone=account_phone,
            limit=limit,
        )
        return [
            HistoryItem(
                ticket_no=r.ticket_no,
                order_no=r.order_no,
                status=str(r.status) if hasattr(r.status, "value") else r.status,
                raw_status=r.raw_status,
                queried_at=r.queried_at.isoformat() if hasattr(r.queried_at, "isoformat") else str(r.queried_at),
                account_phone=r.account_phone,
                took_ms=r.took_ms,
                error=r.error,
            )
            for r in rows
        ]

    return app


def run_server(cfg: AppConfig) -> None:
    import uvicorn
    app = create_app(cfg)
    uvicorn.run(
        app,
        host=cfg.api.host,
        port=cfg.api.port,
        log_level="info",
    )
