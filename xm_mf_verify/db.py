"""SQLite 封装(半自动版)

两个数据库:
- accounts.db: accounts 表(phone → cookie_json + 状态)
- verify_results.db: verify_results 表(每次验真记录,供 dashboard 查)

⚠️ accounts 表不再是"账号池",只是"cookie 缓存":每个 phone 对应最近一次的 cookie
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from loguru import logger

from .models import Account, VerifyResult


# ============================================================
# 通用工具
# ============================================================

def ensure_db_dir(db_path: str | Path) -> None:
    """确保 db 所在目录存在"""
    p = Path(db_path)
    if not p.is_absolute():
        p = Path.cwd() / p
    p.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connect(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """SQLite 连接上下文管理器"""
    ensure_db_dir(db_path)
    conn = sqlite3.connect(str(db_path), timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


# ============================================================
# accounts.db(简化:只为 cookie 缓存)
# ============================================================

ACCOUNTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    phone              TEXT    PRIMARY KEY,
    cookie_json        TEXT,
    cookie_expires_at  TEXT,
    last_login_at      TEXT,
    last_used_at       TEXT,
    note               TEXT    NOT NULL DEFAULT '',
    created_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_accounts_last_used ON accounts(last_used_at);
"""


def init_accounts_db(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.executescript(ACCOUNTS_SCHEMA)


def upsert_account_note(db_path: str, phone: str, note: str = "") -> None:
    """新建或更新一个账号的 note(用于预填账号信息)"""
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO accounts (phone, note) VALUES (?, ?)
            ON CONFLICT(phone) DO UPDATE SET
                note = excluded.note,
                updated_at = datetime('now', 'localtime')
            """,
            (phone, note),
        )


def update_account_cookie(
    db_path: str,
    phone: str,
    cookie_json: str,
    cookie_expires_at: Optional[datetime] = None,
    note: str = "",
) -> None:
    """更新某个账号的 cookie(登录成功后调用)"""
    expires_str = cookie_expires_at.isoformat() if cookie_expires_at else None
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO accounts (phone, cookie_json, cookie_expires_at, last_login_at, last_used_at, note)
            VALUES (?, ?, ?, datetime('now', 'localtime'), datetime('now', 'localtime'), ?)
            ON CONFLICT(phone) DO UPDATE SET
                cookie_json = excluded.cookie_json,
                cookie_expires_at = excluded.cookie_expires_at,
                last_login_at = datetime('now', 'localtime'),
                last_used_at = datetime('now', 'localtime'),
                note = COALESCE(NULLIF(excluded.note, ''), accounts.note),
                updated_at = datetime('now', 'localtime')
            """,
            (phone, cookie_json, expires_str, note),
        )


def touch_last_used(db_path: str, phone: str) -> None:
    """更新 last_used_at(verify 完成后调用)"""
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE accounts SET last_used_at = datetime('now', 'localtime') WHERE phone = ?",
            (phone,),
        )


def get_account_by_phone(db_path: str, phone: str) -> Optional[Account]:
    with connect(db_path) as conn:
        row = conn.execute("SELECT * FROM accounts WHERE phone = ?", (phone,)).fetchone()
        if not row:
            return None
        return _row_to_account(row)


def list_accounts(db_path: str, limit: int = 50) -> list[Account]:
    """列最近用过的账号"""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM accounts ORDER BY COALESCE(last_used_at, '') DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_account(r) for r in rows]


def _row_to_account(row: sqlite3.Row) -> Account:
    return Account(
        phone=row["phone"],
        cookie_json=row["cookie_json"],
        cookie_expires_at=_parse_dt(row["cookie_expires_at"]) if row["cookie_expires_at"] else None,
        last_login_at=_parse_dt(row["last_login_at"]) if row["last_login_at"] else None,
        last_used_at=_parse_dt(row["last_used_at"]) if row["last_used_at"] else None,
        note=row["note"] or "",
    )


# ============================================================
# verify_results.db
# ============================================================

RESULTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS verify_results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_no       TEXT    NOT NULL DEFAULT '',
    order_no        TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL,
    raw_status      TEXT    NOT NULL DEFAULT '',
    queried_at      TEXT    NOT NULL,
    account_phone   TEXT    NOT NULL DEFAULT '',
    took_ms         INTEGER NOT NULL DEFAULT 0,
    error           TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_results_ticket ON verify_results(ticket_no);
CREATE INDEX IF NOT EXISTS idx_results_order ON verify_results(order_no);
CREATE INDEX IF NOT EXISTS idx_results_queried ON verify_results(queried_at);
CREATE INDEX IF NOT EXISTS idx_results_status ON verify_results(status);
CREATE INDEX IF NOT EXISTS idx_results_account ON verify_results(account_phone);
"""


def init_results_db(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.executescript(RESULTS_SCHEMA)


def insert_verify_result(db_path: str, result: VerifyResult) -> int:
    """插入一条验真结果,返回 rowid"""
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO verify_results
                (ticket_no, order_no, status, raw_status, queried_at, account_phone, took_ms, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.ticket_no,
                result.order_no,
                result.status if isinstance(result.status, str) else result.status.value,
                result.raw_status,
                result.queried_at.isoformat() if isinstance(result.queried_at, datetime) else str(result.queried_at),
                result.account_phone,
                result.took_ms,
                result.error,
            ),
        )
        return int(cur.lastrowid or 0)


def get_latest_result(db_path: str, ticket_no: str = "", order_no: str = "") -> Optional[VerifyResult]:
    """查某个票号/订单号最近一次验真结果"""
    with connect(db_path) as conn:
        if order_no:
            row = conn.execute(
                "SELECT * FROM verify_results WHERE order_no = ? ORDER BY id DESC LIMIT 1",
                (order_no,),
            ).fetchone()
        elif ticket_no:
            row = conn.execute(
                "SELECT * FROM verify_results WHERE ticket_no = ? ORDER BY id DESC LIMIT 1",
                (ticket_no,),
            ).fetchone()
        else:
            return None
        if not row:
            return None
        return _row_to_result(row)


def list_results(
    db_path: str,
    ticket_no: Optional[str] = None,
    order_no: Optional[str] = None,
    account_phone: Optional[str] = None,
    limit: int = 100,
) -> list[VerifyResult]:
    """列验真结果(可选按票号/订单号/账号过滤)"""
    with connect(db_path) as conn:
        conditions = []
        params: list = []
        if ticket_no:
            conditions.append("ticket_no = ?")
            params.append(ticket_no)
        if order_no:
            conditions.append("order_no = ?")
            params.append(order_no)
        if account_phone:
            conditions.append("account_phone = ?")
            params.append(account_phone)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM verify_results {where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_result(r) for r in rows]


def _row_to_result(row: sqlite3.Row) -> VerifyResult:
    return VerifyResult(
        ticket_no=row["ticket_no"] or "",
        order_no=row["order_no"] or "",
        status=row["status"],
        raw_status=row["raw_status"] or "",
        queried_at=_parse_dt(row["queried_at"]),
        account_phone=row["account_phone"] or "",
        took_ms=int(row["took_ms"] or 0),
        error=row["error"] or "",
    )


# ============================================================
# 通用
# ============================================================

def _parse_dt(s: str) -> datetime:
    """SQLite 时间字符串 → datetime(容错多种格式)"""
    s = (s or "").strip()
    if not s:
        return datetime.now()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    logger.warning(f"[db] 无法解析时间字符串: {s!r}, 用 now 兜底")
    return datetime.now()


def init_all(accounts_db: str, results_db: str) -> None:
    init_accounts_db(accounts_db)
    init_results_db(results_db)
    logger.info(f"[db] 初始化完成: accounts={accounts_db}, results={results_db}")
