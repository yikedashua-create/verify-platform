"""CLI 入口(半自动版)

用法:
    python -m xm_mf_verify verify <ticket_no> --account <phone> [--password <pwd>]   # 单次验真
    python -m xm_mf_verify accounts                                                 # 看最近用过的账号
    python -m xm_mf_verify history [--ticket XXX] [--account XXX] [--limit N]       # 看历史验真结果
    python -m xm_mf_verify serve                                                    # 启 HTTP API
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

from .config import get_config, reset_config
from .db import init_all, insert_verify_result, list_accounts, list_results
from .models import TicketStatus, VerifyResult
from .captcha import make_solver
from .xiamenair import verify_ticket
from .batch import read_orders_file, run_batch, write_json_output


def _prompt_password() -> str:
    """交互式问密码(用 input() 而不是 getpass(),PowerShell 5.1 兼容)

    _prompt_password() 依赖 TTY,PowerShell 5.1 没 TTY 会卡住。
    input() 会回显密码(请确保周围无人),但能保证输入成功。
    """
    try:
        return input("白鹭会员密码(可空,回车跳过,输入可见,周围请无人): ")
    except (EOFError, KeyboardInterrupt):
        return ""


# ============================================================
# 日志
# ============================================================

def setup_logging(log_dir: str, level: str = "INFO") -> None:
    from loguru import logger as _logger
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    _logger.remove()
    _logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
    )
    _logger.add(
        Path(log_dir) / "xm_mf_verify_{time:YYYY-MM-DD}.log",
        level=level,
        rotation="10 MB",
        retention="30 days",
        encoding="utf-8",
    )


# ============================================================
# 子命令
# ============================================================

def cmd_verify(args: argparse.Namespace) -> int:
    """单次验真(2026-07-27 URL 直跳版:订单号 + 账号 → 直接访问订单详情)"""
    cfg = get_config()
    setup_logging(cfg.log.dir, cfg.log.level)
    init_all(cfg.db.accounts_db, cfg.db.results_db)

    # --auto 模式:headless=True + 强制 ddddocr(无人值守)
    if args.auto:
        cfg.playwright.headless = True
        # 强制覆盖 --captcha 为 ddddocr(无人值守不 fallback manual)
        args.captcha = "ddddocr"
        logger.info("[verify] --auto 模式:headless=True + 纯 ddddocr(无人值守)")
    else:
        # 默认:headless=False(陪着看,安全)
        cfg.playwright.headless = False

    # debug 模式:慢动作
    if args.debug:
        cfg.playwright.slow_mo = 1000
        logger.info("[verify] DEBUG 模式:slow_mo=1000ms")

    # 密码:从 --password / --password-stdin / 交互输入
    password = args.password or ""
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n").rstrip("\r")
    if not password and not args.no_password:
        try:
            password = _prompt_password()
        except (EOFError, KeyboardInterrupt):
            password = ""

    # 验证码 solver
    try:
        solver = make_solver(args.captcha)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    result = verify_ticket(
        order_no=args.order_no,
        ticket_no=args.ticket_no or "",
        account_phone=args.account,
        account_password=password,
        cfg=cfg,
        accounts_db=cfg.db.accounts_db,
        captcha_solver=solver,
        debug_network=args.debug_network,
    )
    insert_verify_result(cfg.db.results_db, result)

    out = result.model_dump(mode="json")
    print(json.dumps(out, ensure_ascii=False, indent=2))

    if result.error:
        return 2
    if result.status == TicketStatus.UNKNOWN:
        return 1
    return 0


def cmd_accounts(args: argparse.Namespace) -> int:
    """看最近用过的账号(cookie 缓存)"""
    cfg = get_config()
    init_all(cfg.db.accounts_db, cfg.db.results_db)
    accounts = list_accounts(cfg.db.accounts_db, limit=args.limit)

    if not accounts:
        print("账号缓存为空。先跑 verify --account 13800138000 试试。")
        return 0

    print(f"{'账号(手机号)':<14} {'cookie':<8} {'最后使用':<20} {'最后登录':<20} {'备注'}")
    print("-" * 100)
    for a in accounts:
        cookie = "有" if a.cookie_json else "无"
        last_used = a.last_used_at.strftime("%Y-%m-%d %H:%M") if a.last_used_at else "从未"
        last_login = a.last_login_at.strftime("%Y-%m-%d %H:%M") if a.last_login_at else "从未"
        print(f"{a.phone:<14} {cookie:<8} {last_used:<20} {last_login:<20} {a.note}")


def cmd_history(args: argparse.Namespace) -> int:
    """看历史验真结果"""
    cfg = get_config()
    init_all(cfg.db.accounts_db, cfg.db.results_db)
    rows = list_results(
        cfg.db.results_db,
        ticket_no=args.ticket,
        order_no=args.order,
        account_phone=args.account,
        limit=args.limit,
    )

    if not rows:
        print("没有历史结果")
        return 0

    print(f"{'订单号':<22} {'票号':<16} {'状态':<8} {'原始':<18} {'账号':<14} {'查询时间':<20} {'耗时':<6} {'错误'}")
    print("-" * 140)
    for r in rows:
        qt = r.queried_at.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"{r.order_no:<22} {r.ticket_no:<16} {r.status:<8} {r.raw_status[:16]:<18} "
            f"{r.account_phone:<14} {qt:<20} {r.took_ms:<6} {r.error[:30]}"
        )


def cmd_serve(args: argparse.Namespace) -> int:
    """启 HTTP API"""
    from .api import run_server
    cfg = get_config()
    if args.host:
        cfg.api.host = args.host
    if args.port:
        cfg.api.port = args.port
    print(f"启动 HTTP API: http://{cfg.api.host}:{cfg.api.port}")
    run_server(cfg)
    return 0


def cmd_verify_batch(args: argparse.Namespace) -> int:
    """批量验真(从文件读订单号)"""
    cfg = get_config()
    setup_logging(cfg.log.dir, cfg.log.level)

    # --auto 模式:headless=True + 强制 ddddocr(无人值守)
    if args.auto:
        cfg.playwright.headless = True
        args.captcha = "ddddocr"
        logger.info("[batch] --auto 模式:headless=True + 纯 ddddocr(无人值守)")

    # debug 模式:慢动作 + 详细日志
    if args.debug:
        cfg.playwright.slow_mo = 1000
        logger.info("[batch] DEBUG 模式:slow_mo=1000ms,详细日志")

    # 读订单文件
    try:
        orders = read_orders_file(args.file)
    except (FileNotFoundError, ValueError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    logger.info(f"[batch] 从 {args.file} 读到 {len(orders)} 个订单")

    # 密码
    password = args.password or ""
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\n").rstrip("\r")
    if not password and not args.no_password:
        try:
            password = _prompt_password()
        except (EOFError, KeyboardInterrupt):
            password = ""

    # 验证码 solver
    try:
        solver = make_solver(args.captcha)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1

    # 跑
    summary = run_batch(
        orders=orders,
        account_phone=args.account,
        account_password=password,
        cfg=cfg,
        captcha_solver=solver,
        delay_sec=args.delay,
    )

    # 汇总
    summary.print_summary()

    # JSON 输出
    if args.output:
        try:
            write_json_output(summary, args.output)
        except Exception as e:
            logger.warning(f"[batch] 写 JSON 失败: {e}")

    # 退出码
    if summary.failed == 0:
        return 0
    if summary.success == 0:
        return 2
    return 1  # 部分成功


# ============================================================
# argparse
# ============================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="xm_mf_verify",
        description="厦门航空(MF)白鹭会员半自动验真 — 输入票号 + 账号,程序填好账号,人过 4 位验证码后自动抓票状态",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # verify
    p_verify = sub.add_parser("verify", help="单次验真(弹浏览器,登录后直跳订单详情)")
    p_verify.add_argument(
        "order_no",
        help="订单号(下单成功的订单号,不是票号)",
    )
    p_verify.add_argument(
        "--ticket-no", "-t",
        default="",
        help="票号(可选,仅做记录)",
    )
    p_verify.add_argument(
        "--account", "-a",
        required=True,
        help="白鹭会员手机号(出票时用的那个账号)",
    )
    p_verify.add_argument(
        "--password", "-p",
        default="",
        help="白鹭会员密码(可省,会交互输入)",
    )
    p_verify.add_argument(
        "--password-stdin",
        action="store_true",
        help="从 stdin 读密码(脚本调用友好)",
    )
    p_verify.add_argument(
        "--no-password",
        action="store_true",
        help="完全不要密码(只填手机号,验证码页自己输)",
    )
    p_verify.add_argument(
        "--captcha", "-c",
        default="auto",
        choices=["auto", "ddddocr", "manual"],
        help="验证码模式:auto=ddddocr 自动识别 + 失败 fallback 人工(default) / "
             "ddddocr=纯自动 / manual=纯人工输入",
    )
    p_verify.add_argument(
        "--auto",
        action="store_true",
        help="无人值守模式:headless=True + 纯 ddddocr(不弹浏览器,失败不 fallback)。"
             "前提:ddddocr 实际识别率得够高(建议先单独跑 1-2 张验证)",
    )
    p_verify.add_argument(
        "--debug",
        action="store_true",
        help="诊断模式:慢动作 + 详细日志(失败时输出截图 + body 文本)",
    )
    p_verify.add_argument(
        "--debug-network",
        action="store_true",
        help="网络诊断:打印所有 XHR/fetch 响应(用来找 booking API URL)",
    )
    p_verify.set_defaults(func=cmd_verify)

    # accounts
    p_acc = sub.add_parser("accounts", help="看最近用过的白鹭会员账号(cookie 缓存)")
    p_acc.add_argument("--limit", type=int, default=20, help="最多显示几条")
    p_acc.set_defaults(func=cmd_accounts)

    # history
    p_hist = sub.add_parser("history", help="看历史验真结果")
    p_hist.add_argument("--ticket", help="按票号过滤")
    p_hist.add_argument("--order", help="按订单号过滤")
    p_hist.add_argument("--account", help="按账号过滤")
    p_hist.add_argument("--limit", type=int, default=20, help="最多显示几条")
    p_hist.set_defaults(func=cmd_history)

    # serve
    p_serve = sub.add_parser("serve", help="启动 HTTP API(供 dashboard 调)")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.set_defaults(func=cmd_serve)

    # verify-batch
    p_batch = sub.add_parser("verify-batch", help="批量验真(从文件读订单号列表)")
    p_batch.add_argument(
        "--file", "-f",
        required=True,
        help="订单号文件路径(每行一个,支持 订单号 或 订单号,票号 格式)",
    )
    p_batch.add_argument(
        "--account", "-a",
        required=True,
        help="白鹭会员手机号(出票时用的那个账号,所有订单共用)",
    )
    p_batch.add_argument("--password", "-p", default="", help="白鹭会员密码")
    p_batch.add_argument("--password-stdin", action="store_true", help="从 stdin 读密码")
    p_batch.add_argument("--no-password", action="store_true", help="不要密码")
    p_batch.add_argument(
        "--captcha", "-c",
        default="auto",
        choices=["auto", "ddddocr", "manual"],
        help="验证码模式(默认 auto)",
    )
    p_batch.add_argument(
        "--delay", "-d",
        type=float,
        default=5.0,
        help="每个订单间隔秒数(防风控,默认 5)",
    )
    p_batch.add_argument(
        "--output", "-o",
        default="",
        help="结果输出 JSON 文件(可选)",
    )
    p_batch.add_argument(
        "--debug",
        action="store_true",
        help="诊断模式:慢动作 + 详细日志(失败时输出截图 + body 文本)",
    )
    p_batch.add_argument(
        "--auto",
        action="store_true",
        help="无人值守模式:headless=True + 纯 ddddocr(不弹浏览器,失败不 fallback)。"
             "前提:ddddocr 实际识别率得够高(建议先单独跑 1-2 张验证)",
    )
    p_batch.set_defaults(func=cmd_verify_batch)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
