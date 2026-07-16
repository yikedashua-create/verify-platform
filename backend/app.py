"""FastAPI 入口"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

import sys
import os
# 让 backend/ 能 import 上层 airlines/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airlines import get_adapter, list_airlines
from airlines.ticket_generator import generate_tickets, generate_ticket_images

app = FastAPI(title="客票验真 API", version="0.1.0")

# 允许 Streamlit 前端跨域调 (本地开发会用到)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "service": "客票验真 API",
        "version": "0.1.0",
        "airlines_count": len(list_airlines()),
        "endpoints": ["/airlines", "/airlines/{code}", "/verify/{code}", "/ticket/generate", "/health"],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/airlines")
def get_airlines():
    """返回所有航司配置(供前端渲染航司选择 + 表单)"""
    return list_airlines()


@app.get("/airlines/{code}")
def get_airline(code: str):
    adapter = get_adapter(code)
    if not adapter:
        raise HTTPException(404, f"航司 {code} 不存在")
    return adapter.get_config()


class VerifyRequest(BaseModel):
    form_data: Dict[str, Any]


@app.post("/verify/{code}")
def verify(code: str, req: VerifyRequest):
    adapter = get_adapter(code)
    if not adapter:
        raise HTTPException(404, f"航司 {code} 不存在")

    result = adapter.query(req.form_data)
    return result


class TicketRequest(BaseModel):
    airline: str  # 航司代码 (e.g. "ij", "mm")
    flight_info: Dict[str, Any]  # 来自 /verify 的 raw 字段
    flight_schedule: str = ""  # MF 厦门航司用


@app.post("/ticket/generate")
def generate_ticket(req: TicketRequest):
    """从查询结果生成机票凭证 PNG 图片

    返回所有乘客×航段的 PNG (base64 编码),前端 download_button 一键下载
    跳过了原流程的"下载 HTML → 打开 → 截图 → 转 JPG"中间 3 步
    """
    result = generate_ticket_images(req.airline, req.flight_info, req.flight_schedule)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "生成失败"))
    return result


if __name__ == "__main__":
    import uvicorn
    # 端口 8000 被守护进程占着(用户的 launcher), 8001 是小铃工作台
    # 用 8002 避开
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="info")
