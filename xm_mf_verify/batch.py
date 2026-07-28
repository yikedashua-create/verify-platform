"""批量验真(2026-07-27 加)

设计:
- 串行处理(避免风控,几十张/天场景不需要并发)
- 每次都跑完整流程(登录 + 取详情),不复用 session
  - 简单不容易出 bug
  - 几十张 × 3-5 秒 = 几分钟完成
  - cookie 复用由 verify_ticket 内部处理(同账号 30 分钟内)

输入文件格式(每行一个订单):
    # 注释行(以 # 开头),空行跳过
    202607271231063941
    202607271231063942,731-1234567890
    202607271231063943

支持两种格式:
- 纯订单号: 202607271231063941
- 订单号 + 票号(逗号分隔): 202607271231063942,731-1234567890
  票号仅做记录,不参与查询
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

from .config import AppConfig
from .db import init_all, insert_verify_result
from .models import TicketStatus, VerifyResult
from .xiamenair import verify_ticket


# ============================================================
# 数据类
# ============================================================

@dataclass
class BatchSummary:
    """批量验真汇总"""

    total: int = 0
    success: int = 0
    failed: int = 0
    results: list[VerifyResult] = field(default_factory=list)
    status_dist: dict[str, int] = field(default_factory=dict)  # 票状态分布
    error_dist: dict[str, int] = field(default_factory=dict)   # 错误信息分布
    took_sec: float = 0.0

    def add(self, result: VerifyResult) -> None:
        """累加一条结果"""
        self.total += 1
        self.results.append(result)

        if result.error:
            self.failed += 1
            # 错误归一化(取错误信息前 30 字作为 key)
            err_key = result.error[:30] or "未知错误"
            self.error_dist[err_key] = self.error_dist.get(err_key, 0) + 1
        else:
            self.success += 1
            # 票状态归一化
            status = result.status if isinstance(result.status, str) else result.status.value
            self.status_dist[status] = self.status_dist.get(status, 0) + 1

    def print_summary(self) -> None:
        """打印汇总"""
        logger.info("=" * 60)
        logger.info("批量验真汇总")
        logger.info("=" * 60)
        logger.info(f"  总数: {self.total}")
        logger.info(f"  成功: {self.success}")
        logger.info(f"  失败: {self.failed}")
        logger.info(f"  总耗时: {self.took_sec:.1f}s")
        logger.info(f"  平均: {self.took_sec / max(1, self.total):.1f}s/单")

        if self.status_dist:
            logger.info("")
            logger.info("  票状态分布:")
            for status, count in sorted(self.status_dist.items(), key=lambda x: -x[1]):
                pct = count / self.success * 100 if self.success else 0
                logger.info(f"    {status}: {count} ({pct:.1f}%)")

        if self.error_dist:
            logger.info("")
            logger.info("  错误分布:")
            for err, count in sorted(self.error_dist.items(), key=lambda x: -x[1]):
                logger.info(f"    [{count}次] {err}")

    def to_dict(self) -> dict:
        """转 dict(供 JSON 序列化)"""
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "took_sec": round(self.took_sec, 2),
            "status_dist": self.status_dist,
            "error_dist": self.error_dist,
            "results": [
                {
                    "order_no": r.order_no,
                    "ticket_no": r.ticket_no,
                    "status": r.status if isinstance(r.status, str) else r.status.value,
                    "raw_status": r.raw_status,
                    "account_phone": r.account_phone,
                    "queried_at": r.queried_at.isoformat() if hasattr(r.queried_at, "isoformat") else str(r.queried_at),
                    "took_ms": r.took_ms,
                    "error": r.error,
                }
                for r in self.results
            ],
        }


# ============================================================
# 订单文件读取
# ============================================================

def read_orders_file(path: str | Path) -> list[tuple[str, str]]:
    """读订单号文件

    Returns:
        [(order_no, ticket_no), ...]  # ticket_no 可能为空
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"订单文件不存在: {path}")

    orders: list[tuple[str, str]] = []
    with open(p, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            # 跳过空行 / 注释行
            if not line or line.startswith("#"):
                continue

            # 拆订单号 + 票号(逗号分隔)
            parts = [x.strip() for x in line.split(",")]
            order_no = parts[0]
            ticket_no = parts[1] if len(parts) > 1 else ""

            if not order_no:
                logger.warning(f"[batch] 第 {lineno} 行订单号为空,跳过: {line!r}")
                continue

            orders.append((order_no, ticket_no))

    if not orders:
        raise ValueError(f"订单文件 {path} 里没有有效订单")

    return orders


# ============================================================
# 批量执行
# ============================================================

def run_batch(
    orders: list[tuple[str, str]],
    account_phone: str,
    account_password: str,
    cfg: AppConfig,
    captcha_solver,
    delay_sec: float = 5.0,
) -> BatchSummary:
    """串行跑所有订单

    Args:
        orders: [(order_no, ticket_no), ...]
        account_phone: 白鹭会员手机号
        account_password: 白鹭会员密码
        cfg: AppConfig
        captcha_solver: CaptchaSolver 实例
        delay_sec: 每个订单之间间隔(防风控)

    Returns:
        BatchSummary
    """
    init_all(cfg.db.accounts_db, cfg.db.results_db)

    summary = BatchSummary()
    t0 = time.time()

    total = len(orders)
    for idx, (order_no, ticket_no) in enumerate(orders, 1):
        logger.info(f"[batch] [{idx}/{total}] 处理订单: {order_no}" + (f" (票号 {ticket_no})" if ticket_no else ""))

        try:
            result = verify_ticket(
                order_no=order_no,
                ticket_no=ticket_no,
                account_phone=account_phone,
                account_password=account_password,
                cfg=cfg,
                accounts_db=cfg.db.accounts_db,
                captcha_solver=captcha_solver,
            )
            insert_verify_result(cfg.db.results_db, result)
            summary.add(result)

            # 实时打印当前结果
            if result.error:
                logger.warning(f"  → ❌ 失败: {result.error}")
            else:
                status = result.status if isinstance(result.status, str) else result.status.value
                logger.info(f"  → ✅ {status} ({result.took_ms}ms) raw: {result.raw_status[:50]!r}")
        except Exception as e:
            logger.exception(f"  → 💥 异常: {e}")
            # 包装成 VerifyResult
            from datetime import datetime
            error_result = VerifyResult(
                ticket_no=ticket_no,
                order_no=order_no,
                status=TicketStatus.UNKNOWN,
                raw_status="",
                queried_at=datetime.now(),
                account_phone=account_phone,
                took_ms=0,
                error=f"批量执行异常: {type(e).__name__}: {e}",
            )
            insert_verify_result(cfg.db.results_db, error_result)
            summary.add(error_result)

        # 间隔(最后一条不间隔)
        if idx < total and delay_sec > 0:
            logger.debug(f"[batch] 等待 {delay_sec}s ...")
            time.sleep(delay_sec)

    summary.took_sec = time.time() - t0
    return summary


def write_json_output(summary: BatchSummary, path: str | Path) -> None:
    """写 JSON 输出"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(summary.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info(f"[batch] 结果已保存到: {p}")
