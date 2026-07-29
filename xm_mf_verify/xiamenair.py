"""MF 厦航业务逻辑(URL 直跳版,2026-07-27 第三轮简化)

设计:
- 登录后直接访问 booking URL 模板 + 订单号,不再"进我的订单 + 搜票号"
- 流程:填账号 + 自动验证码 + 登录 + 跳到订单详情 + 抓票状态
- 验证码由 captcha_solver 解决(默认 auto:ddddocr + manual fallback)

⚠️ selector 仍需根据真实页面微调(验证码元素 / 登录按钮 / 票状态文本)
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from playwright.sync_api import Page, TimeoutError as PWTimeoutError

from .config import AppConfig
from .db import get_account_by_phone, update_account_cookie
from .models import Account, TicketStatus, VerifyResult
from .session import SessionExpiredError, SessionManager
from .captcha import CaptchaSolver, ManualSolver


# ============================================================
# 业务常量
# ============================================================

# MF 厦航票号:731 开头 + 10 位数字,共 13 位
TICKET_NO_RE = re.compile(r"^731[-\s]?(\d{10})$")

# 票状态关键字(2026-07-27 加'出票成功'等,跟 from_raw 保持一致)
STATUS_KEYWORDS = [
    # 退票
    "已退票", "退票中", "申请退票", "退票成功", "全退", "部分退", "已退",
    # 改期
    "已改期", "已改签", "改期中", "已变更", "改签成功", "已改",
    # 已使用
    "已使用", "已乘机", "已出行", "已飞", "已登机",
    # 未使用 / 出票成功
    "未使用", "未出行", "未乘机", "已出票", "可使用", "出票完成",
    "出票成功", "待出票", "出票中",
]

# 登录成功的特征
# 2026-07-28 加:"注销" / "白鹭俱乐部" / "您好," / "我的白鹭"(实际页面里这些比"我的订单"更常见)
# 2026-07-28 加:booking 详情页的"客票号" / "OPEN_FOR_USE" / "订单单号"(verify_ticket 用 int-et 测 cookie)
LOGIN_SUCCESS_MARKERS = [
    "注销",
    "退出",
    "退出登录",
    "您好,",
    "白鹭俱乐部",
    "我的白鹭",
    "个人中心",
    "我的订单",
    "我的行程",
    "我的账户",
    "我的",
    "头像",
    # booking 页面特征(verify_ticket 4.1 步用 booking URL 测 cookie)
    "客票号",
    "OPEN_FOR_USE",
    "FLOWN",
    "REFUNDED",
    "订单单号",
    "PNR",
]

# 登录失败的特征
LOGIN_FAILED_MARKERS = [
    "验证码错误", "密码错误", "账号不存在", "请输入正确的",
    "登录失败", "操作频繁", "账号或密码",
]

# 登录失效的特征(被踢回登录页)
LOGIN_EXPIRED_MARKERS = [
    "请登录", "登录后查看", "请先登录",
    "会话已过期", "登录已失效", "未登录",
]


# ============================================================
# 订单详情(2026-07-27 升级:用 HTML 结构化解析拿票号 + 状态)
# ============================================================

# HTML 结构(2026-07-27 真实页面确认)
# 票号: <div class="ticket-number"><span class="number">客票号:7312160543420</span></div>
# 状态: <div class="segment-td status">OPEN_FOR_USE</div>
# 航班: <div class="flight-info"> ... departure/arrival ...
# PNR:  <div class="...">JX2EE1</div>
TICKET_NO_HTML_RE = re.compile(r"客票号[:：]\s*(\d{13})")
TICKET_NO_DIRECT_RE = re.compile(r"\b(731\d{10})\b")

# ticketStatus 业务映射(API 用的英文,我们要中文)
# OPEN_FOR_USE / FLOWN / REFUNDED / EXCHANGED
TICKET_STATUS_HTML_MAP = {
    "OPEN_FOR_USE": "未使用",
    "FLOWN": "已使用",
    "USED": "已使用",
    "REFUNDED": "已退票",
    "EXCHANGED": "已改期",
    "CHANGED": "已改期",
    "VOID": "已作废",
}


def _extract_ticket_no_from_html(html: str) -> Optional[str]:
    """从 HTML 源码里提票号(优先 '客票号:' 前缀)"""
    m = TICKET_NO_HTML_RE.search(html)
    if m:
        return m.group(1)
    # 兜底:任意 731 开头 13 位
    m = TICKET_NO_DIRECT_RE.search(html)
    if m:
        return m.group(1)
    return None


def _extract_status_from_html(html: str) -> Optional[str]:
    """从 HTML 源码里提票状态(英文 OPEN_FOR_USE / FLOWN / ...)"""
    # 1. 优先从结构化 .segment-td.status 取
    m = re.search(r'<div\s+class="segment-td\s+status"[^>]*>([A-Z_]+)</div>', html)
    if m:
        return m.group(1)
    # 2. 兜底:在 HTML 任意位置找 OPEN_FOR_USE/FLOWN/REFUNDED/EXCHANGED
    for kw in ["OPEN_FOR_USE", "FLOWN", "REFUNDED", "EXCHANGED"]:
        if kw in html:
            return kw
    return None


def _extract_pnr_from_html(html: str) -> Optional[str]:
    """从 HTML 源码里提 PNR(6 位字母数字)"""
    # 通常显示在 'PNR:' 后面
    m = re.search(r"PNR[:：]\s*([A-Z0-9]{6})", html)
    if m:
        return m.group(1)
    # 兜底:在 PNR 关键字附近找 6 位
    m = re.search(r"PNR[^A-Z0-9]{0,20}([A-Z0-9]{6})", html)
    if m:
        return m.group(1)
    return None


# ============================================================
# 票号归一化
# ============================================================

def normalize_ticket_no(raw: str) -> str:
    """归一化票号:去空格/横线,统一为 731-XXXXXXXXXX

    MF 厦航票号必须以 731 开头(13 位),否则直接拒收
    """
    if not raw:
        raise ValueError("票号为空")
    s = re.sub(r"[\s-]", "", raw.strip())
    if not s.isdigit():
        raise ValueError(f"票号必须全为数字,实际: {raw!r}")
    if not s.startswith("731"):
        raise ValueError(f"MF 厦航票号必须以 731 开头,实际: {raw!r}")
    if len(s) != 13:
        raise ValueError(f"MF 厦航票号必须为 13 位(731 + 10 位数字),实际 {len(s)} 位: {raw!r}")
    return f"731-{s[3:]}"


def validate_order_no(raw: str) -> str:
    """校验订单号(非空即可,具体格式不严格)"""
    if not raw or not raw.strip():
        raise ValueError("订单号为空")
    return raw.strip()


# ============================================================
# 登录:填账号 + 自动/人工过 4 位验证码
# ============================================================

def fill_credentials(page: Page, phone: str, password: str) -> bool:
    """填手机号 + 密码(不点登录,留给 captcha solver 解决)

    ⚠️ 骨架版:selector 需要根据实际页面微调
    """
    # 0. 尝试切到"账号密码登录" tab
    try:
        tab = page.locator("text=/账号密码|密码登录|账密登录/").first
        if tab.is_visible(timeout=1500):
            tab.click()
            time.sleep(0.5)
    except PWTimeoutError:
        pass

    # 1. 填手机号 — 2026-07-28 改:优先 OAuth2 input.account,fallback 通用 selector
    try:
        phone_selectors = [
            "input.account",  # 厦航 OAuth2
            "input[alt*='手机号']",
            "input[type='tel']",
            "input[placeholder*='手机']",
            "input[name*='phone']",
        ]
        for sel in phone_selectors:
            el = page.locator(sel).first
            if el.is_visible(timeout=500):
                el.fill(phone)
                break
        else:
            raise RuntimeError("所有 phone selector 都不可见")
    except Exception as e:
        logger.error(f"[login] 找不到手机号输入框: {e}")
        return False

    # 2. 填密码
    if password:
        try:
            # 2026-07-28 改:厦航 input.password 跟通用 input[type='password'] 一起试
            pwd_selectors = [
                "input.password",  # 厦航 OAuth2
                "input[type='password']",
            ]
            for sel in pwd_selectors:
                el = page.locator(sel).first
                if el.is_visible(timeout=500):
                    el.fill(password)
                    break
            else:
                raise RuntimeError("所有 password selector 都不可见")
        except Exception as e:
            logger.error(f"[login] 找不到密码输入框: {e}")
            return False

    # 3. 勾隐私协议
    try:
        checkbox = page.locator("input[type='checkbox']").first
        if checkbox.is_visible(timeout=800) and not checkbox.is_checked():
            checkbox.check()
    except Exception:
        pass

    return True


# ============================================================
# 主页 → 点"登录"按钮 → 登录表单(2026-07-27 用户反馈)
# ============================================================

def ensure_login_form_visible(page: Page, max_wait_sec: int = 60) -> bool:
    """确保登录表单可见(主站首页要点击'登录'按钮才出现登录表单)

    流程(2026-07-27 增强):
    1. 等页面 JS 渲染完成(networkidle, 最多 10s)
    2. 多种 selector 找"登录表单"——不再只查 input[type='tel']
    3. 没找到 → 尝试点"登录"按钮
    4. 还没 → 提示用户手动点,等 60s
    5. 超时 → 截全页图 + 输出 body 文本

    Returns: True = 表单可见,False = 超时
    """
    # 0. 等 JS 渲染完成
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except PWTimeoutError:
        logger.debug("[login] networkidle 超时(继续)")

    # 1. 多种 selector 找登录表单(覆盖更多可能)
    form_selectors = [
        # === 2026-07-28 加:OAuth2 登录表单(厦航 ecipuia.xiamenair.com)===
        # 真实 HTML: <input class="account" placeholder="请输入白鹭卡号/..."> + <input class="password"> + <input class="code1">
        "input.account",  # 手机号/白鹭卡号
        "input.password",  # 密码
        "input.code1",  # 验证码
        "input.J_Captcha",  # 同上
        # === 原有的:OTA 平台常见登录 ===
        "input[type='tel']",
        "input[name='username']",
        "input[name='mobile']",
        "input[name='phone']",
        "input[placeholder*='手机']",
        "input[placeholder*='账号']",
        "input[placeholder*='用户名']",
        "input[id*='username']",
        "input[id*='account']",
        "input[id*='mobile']",
    ]

    def _has_form() -> bool:
        """检查任一登录表单 selector 是否可见(2026-07-28:timeout 300→2000 适应慢 JS 渲染)"""
        for sel in form_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    logger.debug(f"[login] 找到登录表单(selector={sel!r})")
                    return True
            except Exception as e:
                logger.debug(f"[login] selector {sel!r} 失败: {type(e).__name__}")
                continue
        return False

    if _has_form():
        logger.debug("[login] 登录表单已可见")
        return True

    # 2026-07-28 加诊断:_has_form 全失败时,看 page.url + 几个关键 selector 状态
    logger.warning(f"[login] _has_form 失败,page.url={page.url}")
    for sel in form_selectors[:3]:
        try:
            el = page.locator(sel).first
            count = page.locator(sel).count()
            logger.warning(f"  selector {sel!r}: count={count}")
        except Exception as e:
            logger.warning(f"  selector {sel!r}: 异常 {e}")

    # 2. 尝试点"登录"按钮(主站首页 → 跳转 OAuth2)
    # 2026-07-28 加:页面有 mask 元素挡住 header,需要 force=True 或先关掉 mask
    login_btn_selectors = [
        "header a:has-text('登录')",
        "nav a:has-text('登录')",
        "a:has-text('登录')",  # 兜底
        "button:has-text('登录')",
    ]
    for sel in login_btn_selectors:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=500):
                logger.info(f"[login] 点'登录'按钮(selector: {sel!r})")
                # 2026-07-28:先关掉 mask 元素(mask 是 home-footer 里的弹窗,会挡 header)
                try:
                    page.evaluate(
                        "document.querySelectorAll('.mask').forEach(m => m.style.display='none')"
                    )
                except Exception:
                    pass
                try:
                    btn.click(force=True)  # 强制点,即使被遮挡
                except Exception:
                    btn.click()
                time.sleep(2)  # 等跳转
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except PWTimeoutError:
                    pass
                if _has_form():
                    logger.info("[login] 登录表单出现(点了登录后),继续")
                    return True
        except Exception as e:
            logger.debug(f"[login] selector {sel!r} 失败: {e}")
            continue

    # 3. 自动点不到,提示用户手动点
    logger.warning("[login] ⚠️ 程序找不到'登录'按钮或点了没反应")
    logger.warning("[login] 👉 请在浏览器里手动点击右上角'登录'按钮")
    logger.info(f"[login] 等待登录表单出现(最多 {max_wait_sec} 秒)...")

    t0 = time.time()
    while time.time() - t0 < max_wait_sec:
        if _has_form():
            logger.info("[login] 登录表单出现了(用户手动点的),继续")
            return True
        time.sleep(1)

    # 4. 超时 — 截全页图 + 输出 body 文本(诊断)
    logger.error(f"[login] {max_wait_sec} 秒内登录表单没出现,放弃")
    _dump_page_state(page, tag="login_form_not_found")
    return False


def _dump_page_state(page: Page, tag: str) -> None:
    """失败时输出 body 文本 + 截图(诊断用)"""
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception as e:
        logger.warning(f"[login] 拿 body 文本失败: {e}")
        body_text = ""

    preview = body_text[:2000] if body_text else "(空)"
    logger.error(f"[login] === 当前页面 body 预览(前 2000 字) ===\n{preview}\n=== 预览结束 ===")

    # 截全页图
    try:
        from pathlib import Path
        from datetime import datetime
        screenshot_dir = Path("data/screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = screenshot_dir / f"page_state_{tag}_{ts}.png"
        page.screenshot(path=str(path), full_page=True)
        logger.error(f"[login] 📸 全页截图: {path}")
    except Exception as e:
        logger.warning(f"[login] 截图失败: {e}")

    # 当前 URL
    logger.error(f"[login] 当前 URL: {page.url}")


def is_login_success(page: Page) -> bool:
    """检查当前页面是否登录成功(启发式)"""
    try:
        body_text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        body_text = ""
    for marker in LOGIN_SUCCESS_MARKERS:
        if marker in body_text:
            return True
    for marker in LOGIN_EXPIRED_MARKERS:
        if marker in body_text:
            return False
    return False


def login_interactive(
    page: Page,
    phone: str,
    password: str,
    cfg: AppConfig,
    captcha_solver: Optional[CaptchaSolver] = None,
) -> bool:
    """交互式登录(2026-07-27 URL 直跳版)

    流程:
    1. 打开登录页
    2. 填账号密码
    3. 用 captcha_solver 解决验证码(默认 AutoSolver)
    4. 校验登录成功
    """
    if not cfg.xiamenair:
        raise RuntimeError("config.xiamenair 未配置")

    login_url = cfg.xiamenair.login_url
    if not login_url:
        raise RuntimeError("config.xiamenair.login_url 为空")

    solver = captcha_solver or ManualSolver()
    logger.info(f"[login] 打开登录页: {login_url},验证码模式: {solver.name}")
    page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(1)

    # 主站首页需要点"登录"按钮才出登录表单
    if not ensure_login_form_visible(page, max_wait_sec=30):
        return False

    if not fill_credentials(page, phone, password):
        return False

    ok = solver.solve(page, max_wait_sec=300)
    if ok:
        logger.info("[login] ✅ 登录成功")
    else:
        logger.error("[login] ❌ 登录失败")
    return ok


# ============================================================
# 订单详情:URL 直跳 + 抓票状态(2026-07-27 新)
# ============================================================

def fetch_booking_details(
    page: Page,
    order_no: str,
    cfg: AppConfig,
    debug_network: bool = False,
) -> Optional["BookingDetails"]:
    """访问订单详情 URL,解析页面拿票号 + 状态 + PNR(2026-07-27 升级版)

    流程:
    1. 拼 URL: cfg.xiamenair.booking_url_template.format(order_no=order_no)
    2. 访问 URL
    3. 等页面加载
    4. 从 HTML 源码结构化解析(2026-07-27 新):
       - 票号: <div class="ticket-number"><span class="number">客票号:7312160543420</span></div>
       - 状态: <div class="segment-td status">OPEN_FOR_USE</div>
       - PNR: PNR:XXXXXX
    5. 兜底:扫 body 文本找"票状态"关键词(兼容老页面)
    6. 返回 BookingDetails

    Args:
        debug_network: True 时打印所有 XHR/fetch 响应 URL

    Returns:
        成功 → BookingDetails
        未找到 → None
        失败 → 抛 SessionExpiredError(被踢回登录页)
    """
    if not cfg.xiamenair or not cfg.xiamenair.booking_url_template:
        raise RuntimeError("config.xiamenair.booking_url_template 未配置")

    url = cfg.xiamenair.booking_url_template.format(order_no=order_no)
    logger.info(f"[booking] 直接访问订单详情: {url}")

    # 2026-07-27 加:debug_network 时挂监听
    captured_responses = []
    if debug_network:
        def _on_response(resp):
            try:
                req = resp.request
                if req.resource_type in ("xhr", "fetch"):
                    captured_responses.append({
                        "url": resp.url,
                        "method": req.method,
                        "status": resp.status,
                        "ct": resp.headers.get("content-type", ""),
                        "size": len(resp.body() or b""),
                    })
            except Exception as e:
                logger.debug(f"[booking] 监听 response 异常: {e}")
        page.on("response", _on_response)

    page.goto(url, wait_until="domcontentloaded", timeout=30000)

    time.sleep(2)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeoutError:
        pass

    # debug_network 跑完,打所有 XHR URL
    if debug_network:
        logger.info(f"[booking] 捕获到 {len(captured_responses)} 个 XHR/fetch 响应")
        for i, r in enumerate(captured_responses):
            logger.info(f"[booking]   [{i+1}] {r['method']} {r['status']} {r['size']}B {r['url']}")
        booking_like = [r for r in captured_responses if any(k in r['url'].lower() for k in ['booking', 'order', 'ticket', 'b8b2', order_no.lower()])]
        if booking_like:
            logger.info(f"[booking] 疑似 booking API({len(booking_like)} 个):")
            for r in booking_like:
                logger.info(f"[booking]   -> {r['method']} {r['status']} {r['size']}B {r['url']}")
        page.remove_listener("response", _on_response)

    # 拿 HTML 源码
    try:
        html = page.content()
    except Exception as e:
        logger.warning(f"[booking] 拿 HTML 失败: {e}")
        return None

    if not html:
        return None

    # 检查是不是被踢回登录页
    for marker in LOGIN_EXPIRED_MARKERS:
        if marker in html:
            raise SessionExpiredError(
                f"访问订单详情时被踢回登录页(检测到 {marker!r})"
            )

    # === 主路径:HTML 结构化解析 ===
    raw_ticket = _extract_ticket_no_from_html(html)
    raw_status = _extract_status_from_html(html)
    pnr = _extract_pnr_from_html(html)

    # 票号归一化
    ticket_no = ""
    if raw_ticket:
        try:
            ticket_no = normalize_ticket_no(raw_ticket)
            logger.info(f"[booking] 拿到票号: {ticket_no} (raw={raw_ticket})")
        except ValueError as e:
            logger.warning(f"[booking] 票号归一化失败: {e} (raw={raw_ticket})")

    # 状态归一化
    status = TicketStatus.UNKNOWN
    status_source = ""
    if raw_status:
        status_source = raw_status
        # 优先用 HTML 业务映射
        if raw_status in TICKET_STATUS_HTML_MAP:
            status = TicketStatus(TICKET_STATUS_HTML_MAP[raw_status])
        else:
            # 兜底用 from_raw(可能扫 body 文本)
            status = TicketStatus.from_raw(raw_status)
        logger.info(f"[booking] 票状态: {raw_status} -> {status.value}")
    else:
        # 兜底:扫 body 文本找"票状态"关键词(老页面兼容)
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
        except Exception as e:
            logger.warning(f"[booking] 拿 body 文本失败: {e}")
            body_text = ""
        logger.info(f"[booking] HTML 没找到状态,扫 body 文本(长度 {len(body_text)})...")
        for kw in STATUS_KEYWORDS:
            if kw in body_text:
                for line in body_text.splitlines():
                    if kw in line:
                        status_source = line.strip()
                        status = TicketStatus.from_raw(status_source)
                        logger.info(f"[booking] body 扫到: {status_source} -> {status.value}")
                        break
                if status != TicketStatus.UNKNOWN:
                    break

    # PNR
    if pnr:
        logger.info(f"[booking] PNR: {pnr}")

    if not raw_ticket and not raw_status:
        logger.warning(f"[booking] 订单详情页里没找到票号也没找到状态")
        preview = html[:800] if html else "(空)"
        logger.warning(f"[booking] === HTML 预览(前 800 字) ===\n{preview}\n=== 预览结束 ===")
        # 2026-07-29: 失败时把完整 HTML 保存到文件,方便排查页面结构变化
        try:
            import os
            from datetime import datetime
            debug_dir = os.path.join(os.path.dirname(__file__), "..", "data", "xm_mf_verify", "debug_html")
            debug_dir = os.path.abspath(debug_dir)
            os.makedirs(debug_dir, exist_ok=True)
            debug_file = os.path.join(debug_dir, f"order_{order_no}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html")
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(html or "")
            logger.info(f"[booking] 完整 HTML 已保存到: {debug_file}")
        except Exception as e:
            logger.warning(f"[booking] 保存 debug HTML 失败: {e}")
        return None

    return BookingDetails(
        raw_status=status_source,
        status=status,
        ticket_no=ticket_no,
        pnr=pnr or "",
    )


# BookingDetails 容器(2026-07-27 加)
@dataclass
class BookingDetails:
    """订单详情页解析结果"""
    raw_status: str
    status: TicketStatus
    ticket_no: str
    pnr: str = ""


# ============================================================
# 高层 API:verify_ticket(2026-07-27 URL 直跳版)
# ============================================================

def verify_ticket(
    order_no: str,
    ticket_no: str = "",
    account_phone: str = "",
    account_password: str = "",
    cfg: Optional[AppConfig] = None,
    accounts_db: Optional[str] = None,
    captcha_solver: Optional[CaptchaSolver] = None,
    debug_network: bool = False,
) -> VerifyResult:
    """单次验真(2026-07-27 URL 直跳版)

    Args:
        order_no: 订单号(**必填**,查订单详情用)
        ticket_no: 票号(可选,仅做记录,不参与查询)
        account_phone: 白鹭会员手机号
        account_password: 白鹭会员密码
        cfg: AppConfig
        accounts_db: accounts.db 路径
        captcha_solver: CaptchaSolver

    Returns:
        VerifyResult
    """
    from .config import get_config
    cfg = cfg or get_config()
    accounts_db = accounts_db or cfg.db.accounts_db

    t0 = time.time()

    # 1. 校验订单号
    try:
        order_no = validate_order_no(order_no)
    except ValueError as e:
        return VerifyResult(
            ticket_no=ticket_no,
            order_no=order_no,
            status=TicketStatus.UNKNOWN,
            raw_status="",
            queried_at=datetime.now(),
            account_phone=account_phone,
            took_ms=int((time.time() - t0) * 1000),
            error=str(e),
        )

    # 2. 校验票号(可选,只做归一化)
    if ticket_no:
        try:
            ticket_no = normalize_ticket_no(ticket_no)
        except ValueError as e:
            return VerifyResult(
                ticket_no=ticket_no,
                order_no=order_no,
                status=TicketStatus.UNKNOWN,
                raw_status="",
                queried_at=datetime.now(),
                account_phone=account_phone,
                took_ms=int((time.time() - t0) * 1000),
                error=f"票号格式错: {e}",
            )

    # 3. 查账号
    acc = get_account_by_phone(accounts_db, account_phone)
    if acc is None:
        from .db import upsert_account_note
        upsert_account_note(accounts_db, account_phone, note="")
        acc = Account(phone=account_phone)

    # 4. 启 Playwright(尊重 cfg.playwright.headless,不再强制)
    pw_cfg = cfg.playwright

    sm = SessionManager(pw_cfg=pw_cfg, account=acc)

    try:
        with sm.open() as page:
            # 4.1 检查 cookie 是否还有效
            storage_state = sm.load_storage_state()
            need_login = True
            if storage_state:
                # 2026-07-28 改:用 OAuth2 URL 测 cookie,不用 int-et booking URL
                # 原因:int-et 域的 cookie 缺失,booking URL 会重定向到地区选择页,
                #      is_login_success 检测不到已登录标志(白鹭俱乐部/注销),误判 cookie 失效
                if cfg.xiamenair and cfg.xiamenair.login_url:
                    test_url = cfg.xiamenair.login_url
                elif cfg.xiamenair and cfg.xiamenair.booking_url_template:
                    test_url = cfg.xiamenair.booking_url_template.format(order_no=order_no)
                else:
                    test_url = "https://www.xiamenair.com/"
                try:
                    page.goto(test_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(2)
                    try:
                        page.wait_for_load_state("networkidle", timeout=8000)
                    except PWTimeoutError:
                        pass
                except Exception as e:
                    logger.info(f"[verify] 访问 OAuth2 URL 失败,可能要登录: {e}")

                if is_login_success(page):
                    logger.info(f"[verify] 账号 {account_phone} cookie 仍有效,跳过登录")
                    need_login = False
                else:
                    logger.info(f"[verify] 账号 {account_phone} cookie 失效,需重新登录")

            # 4.2 登录(如果需要)
            if need_login:
                ok = login_interactive(
                    page, account_phone, account_password, cfg,
                    captcha_solver=captcha_solver,
                )
                if not ok:
                    return VerifyResult(
                        ticket_no=ticket_no,
                        order_no=order_no,
                        status=TicketStatus.UNKNOWN,
                        raw_status="",
                        queried_at=datetime.now(),
                        account_phone=account_phone,
                        took_ms=int((time.time() - t0) * 1000),
                        error="登录失败(验证码识别错 / 密码错误 / 超时)",
                    )

            # 4.3 直接访问订单详情(2026-07-27:返回 BookingDetails 含票号+状态+PNR)
            details = fetch_booking_details(page, order_no, cfg, debug_network=debug_network)

            if details is None:
                # 2026-07-29: 错误信息带上 HTML 路径 + 手动验证链接
                debug_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "xm_mf_verify", "debug_html"))
                # 找最新的 debug HTML(刚 fetch_booking_details 写的)
                debug_files = []
                if os.path.isdir(debug_dir):
                    debug_files = sorted(
                        [os.path.join(debug_dir, f) for f in os.listdir(debug_dir) if f.startswith(f"order_{order_no}_")],
                        key=os.path.getmtime, reverse=True
                    )
                latest_html = debug_files[0] if debug_files else ""
                manual_url = f"https://int-et.xiamenair.com/bookingManagement/displayBooking/list/{order_no}"
                err_msg = (
                    f"订单 {order_no} 详情页里没找到票号/状态(可能订单不存在 / 页面结构不同)\n"
                    f"📄 完整 HTML: {latest_html}\n"
                    f"🔗 手动核对(用白鹭会员 {account_phone} 登录后打开): {manual_url}\n"
                    f"💡 可能原因:\n"
                    f"   1. 订单不在账号 {account_phone} 下(用了别的白鹭会员号买的)\n"
                    f"   2. 订单还没出票(刚下的单子,票号还没生成)\n"
                    f"   3. 页面结构变了(打开上面 HTML 看实际渲染)"
                )
                return VerifyResult(
                    ticket_no=ticket_no,
                    order_no=order_no,
                    status=TicketStatus.UNKNOWN,
                    raw_status="",
                    queried_at=datetime.now(),
                    account_phone=account_phone,
                    took_ms=int((time.time() - t0) * 1000),
                    error=err_msg,
                )

            # 优先用页面拿到的真实票号(覆盖 CLI 传的,如果有)
            final_ticket_no = details.ticket_no or ticket_no
            return VerifyResult(
                ticket_no=final_ticket_no,
                order_no=order_no,
                status=details.status,
                raw_status=details.raw_status,
                queried_at=datetime.now(),
                account_phone=account_phone,
                took_ms=int((time.time() - t0) * 1000),
                error="",
            )
    except SessionExpiredError as e:
        return VerifyResult(
            ticket_no=ticket_no,
            order_no=order_no,
            status=TicketStatus.UNKNOWN,
            raw_status="",
            queried_at=datetime.now(),
            account_phone=account_phone,
            took_ms=int((time.time() - t0) * 1000),
            error=f"登录态失效: {e}",
        )
    except Exception as e:
        logger.exception(f"[verify] 未知异常: {e}")
        return VerifyResult(
            ticket_no=ticket_no,
            order_no=order_no,
            status=TicketStatus.UNKNOWN,
            raw_status="",
            queried_at=datetime.now(),
            account_phone=account_phone,
            took_ms=int((time.time() - t0) * 1000),
            error=f"未知异常: {type(e).__name__}: {e}",
        )
    finally:
        # 5. 保存新 cookie
        try:
            if sm.account.cookie_json:
                update_account_cookie(
                    accounts_db,
                    account_phone,
                    sm.account.cookie_json,
                    sm.account.cookie_expires_at,
                )
            from .db import touch_last_used
            touch_last_used(accounts_db, account_phone)
        except Exception as e:
            logger.warning(f"[verify] 保存状态失败: {e}")
