"""验证码自动识别 + 手动 fallback

3 种 solver:
- DdddocrSolver:用 ddddocr 识别 4 位字符(免费,准确率 70-85%,失败刷新重试)
- ManualSolver:卡在页面等人输
- AutoSolver:先 ddddocr,失败 N 次后 fallback Manual(默认)

设计:
- CaptchaSolver 是抽象基类,定义 solve(page) -> bool 接口
- 单张验证码的"截图 → 识别 → 填 → 提交 → 校验"在 solver 内部完成
- solver.solve() 返回 True = 登录成功 / False = 放弃(让 verify_ticket 返回 error)
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

from loguru import logger
from playwright.sync_api import Page


# ============================================================
# 通用选择器(宽口,适配多种页面)
# ============================================================

# 验证码图片 — 多种可能
# ⚠️ 顺序非常重要:越精确的越前面,避免子串匹配错抓
# 真实翻车案例(2026-07-27):img[alt*='验证码'] 会同时匹配
#   - 真验证码 <img alt="验证码">
#   - 喇叭图标 <img alt="播放图片验证码">  ← 抓到这个,ddddocr 当然认不出来
# 解法:用 class 直接锁定
CAPTCHA_IMG_SELECTORS = [
    # 厦航真实 class(2026-07-27 从 OAuth2 页面 HTML 确认)
    "img.J_Code",                           # 厦航主用
    "img.code-img",                         # 同上,class 形式
    "img[alt='验证码']",                     # 精确 alt 匹配(不是子串)
    "img[src='captcha']",                    # 相对路径
    # 兜底
    "img[class*='captcha']",
    "img[id*='captcha']",
    "img[src*='captcha']",
    "img[src*='verify']",
    # canvas 标签(动态绘制的验证码)
    "canvas[class*='captcha']",
    "canvas[id*='captcha']",
    "canvas[class*='verify']",
    "canvas[id*='verify']",
    # 通用 class 兜底
    ".captcha-img",
    ".verify-img",
    "#captcha-img",
    "#captcha",
    "#verifyImg",
    "#yzmImg",
    "[class*='captcha']:not(input):not(button):not(img[alt*='播放'])",
    ".el-image.captcha",
    ".login-captcha",
]

# 验证码输入框 — 多种可能
CAPTCHA_INPUT_SELECTORS = [
    # 厦航真实 class
    "input.J_Captcha",                      # 厦航主用
    "input.code1",                          # 同上
    "input[placeholder='请输入图片验证码']",  # 精确 placeholder
    "input[aria-label='请输入图片验证码']",
    # 兜底
    "input[name*='captcha']",
    "input[name*='verifyCode']",
    "input[name*='yzm']",
    "input[id*='captcha']",
    "input[id*='yzm']",
    "input[placeholder*='验证码']",
    "input[placeholder*='请输入']",
]

# 登录按钮 — 多种可能
LOGIN_BUTTON_SELECTORS = [
    # 厦航真实 class
    "button.J_Submit",                      # 厦航主用
    "button#login-btn-1",                   # 厦航 id
    # 兜底
    "button[type='submit']",
    "button:has-text('登录')",
    "a:has-text('登录')",
    ".login-btn",
    "#login-btn",
    "button.login",
]

# 登录失败的错误提示文本(任何一条出现 = 识别错了)
LOGIN_ERROR_MARKERS = [
    "验证码错误",
    "验证码不正确",
    "验证码已过期",
    "验证码失效",
    "请输入正确的验证码",
    "verify code error",
    "captcha error",
]


# ============================================================
# 抽象基类
# ============================================================

class CaptchaSolver(ABC):
    """验证码 solver 抽象基类"""

    name: str = "base"

    @abstractmethod
    def solve(self, page: Page, max_wait_sec: int = 300) -> bool:
        """解决验证码 + 完成登录

        Returns:
            True:登录成功(可继续后续操作)
            False:登录失败(放弃,verify_ticket 应返回 error)
        """


# ============================================================
# ddddocr 自动识别
# ============================================================

class DdddocrSolver(CaptchaSolver):
    """用 ddddocr 识别 4 位字符验证码

    流程(单次):
    1. 截验证码图片
    2. ddddocr 识别
    3. 填入输入框
    4. 点登录
    5. 等待 + 校验是否登录成功 / 验证码错误

    失败重试:
    - 识别失败 / 验证码错误 → 刷新验证码图片(点图片 / 等前端重载) → 重试
    - 最多 max_retries 次,默认 3 次
    - 都失败 → 返回 False
    """

    name = "ddddocr"

    def __init__(self, max_retries: int = 3, retry_interval_sec: float = 2.0):
        self.max_retries = max_retries
        self.retry_interval_sec = retry_interval_sec
        self._ocr = None
        self._init_ocr()

    def _init_ocr(self):
        """懒加载 ddddocr"""
        if self._ocr is not None:
            return
        try:
            import ddddocr
            # show_ad=False 关闭 ddddocr 的广告
            self._ocr = ddddocr.DdddOcr(show_ad=False)
            logger.info(f"[{self.name}] ddddocr 初始化完成")
        except ImportError:
            logger.error(f"[{self.name}] ddddocr 未安装,跑: pip install ddddocr")
            self._ocr = None
        except Exception as e:
            logger.exception(f"[{self.name}] ddddocr 初始化失败: {e}")
            self._ocr = None

    def _find_captcha_img(self, page: Page):
        """找验证码图片元素(多种 selector 试一遍)"""
        for sel in CAPTCHA_IMG_SELECTORS:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=500):
                    return el
            except Exception:
                continue
        return None

    def _find_captcha_input(self, page: Page):
        """找验证码输入框(多种 selector 试一遍)"""
        for sel in CAPTCHA_INPUT_SELECTORS:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=500):
                    return el
            except Exception:
                continue
        return None

    def _find_login_button(self, page: Page):
        """找登录按钮"""
        for sel in LOGIN_BUTTON_SELECTORS:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=500):
                    return el
            except Exception:
                continue
        return None

    def _ocr_image(self, img_bytes: bytes) -> Optional[str]:
        """调用 ddddocr 识别图片"""
        if not self._ocr:
            return None
        try:
            result = self._ocr.classification(img_bytes)
            return (result or "").strip()
        except Exception as e:
            logger.warning(f"[{self.name}] OCR 识别异常: {e}")
            return None

    def _refresh_captcha(self, page: Page, img_el) -> bool:
        """刷新验证码(点图片让它重新加载)"""
        try:
            img_el.click()
            time.sleep(0.5)
            return True
        except Exception as e:
            logger.warning(f"[{self.name}] 刷新验证码失败: {e}")
            return False

    def _has_error(self, page: Page) -> bool:
        """检查页面是否提示验证码错误"""
        try:
            body_text = page.locator("body").inner_text(timeout=1500)
        except Exception:
            return False
        for marker in LOGIN_ERROR_MARKERS:
            if marker in body_text:
                return True
        return False

    def _is_login_success(self, page: Page) -> bool:
        """检查是否登录成功(从 xiamenair 复用)"""
        from .xiamenair import LOGIN_SUCCESS_MARKERS
        try:
            body_text = page.locator("body").inner_text(timeout=1500)
        except Exception:
            return False
        return any(m in body_text for m in LOGIN_SUCCESS_MARKERS)

    def solve(self, page: Page, max_wait_sec: int = 300) -> bool:
        if not self._ocr:
            logger.error(f"[{self.name}] OCR 不可用,直接返回失败")
            return False

        # 1. 找元素
        img_el = self._find_captcha_img(page)
        input_el = self._find_captcha_input(page)
        btn_el = self._find_login_button(page)

        if not img_el:
            logger.error(f"[{self.name}] 找不到验证码图片(试过 {len(CAPTCHA_IMG_SELECTORS)} 种 selector)")
            # 诊断:dump 一下页面
            _dump_captcha_debug(page, tag="img_not_found")
            return False
        if not input_el:
            logger.error(f"[{self.name}] 找不到验证码输入框(试过 {len(CAPTCHA_INPUT_SELECTORS)} 种 selector)")
            _dump_captcha_debug(page, tag="input_not_found")
            return False

        logger.info(f"[{self.name}] 找到验证码元素,开始识别(最多 {self.max_retries} 次)")

        # 2. 循环重试
        for attempt in range(1, self.max_retries + 1):
            logger.info(f"[{self.name}] 第 {attempt}/{self.max_retries} 次识别")

            # 2.1 截验证码图片
            try:
                img_bytes = img_el.screenshot()
            except Exception as e:
                logger.warning(f"[{self.name}] 截图失败: {e}")
                self._refresh_captcha(page, img_el)
                continue

            if not img_bytes:
                logger.warning(f"[{self.name}] 截图为空,刷新验证码")
                self._refresh_captcha(page, img_el)
                continue

            # 2.1.1 关键:每次截图都保存(让我们看到截到啥)
            _save_captcha_image(img_bytes, attempt)

            # 2.2 OCR 识别
            code = self._ocr_image(img_bytes)
            if not code:
                logger.warning(f"[{self.name}] 识别结果为空(看 data/screenshots/captcha_*.png 排查)")
                self._refresh_captcha(page, img_el)
                time.sleep(self.retry_interval_sec)
                continue

            # 4 位字符过滤
            code_clean = "".join(c for c in code if c.isalnum())[:4]
            if len(code_clean) != 4:
                logger.warning(f"[{self.name}] 识别结果不是 4 位: {code!r} → {code_clean!r},刷新重试")
                self._refresh_captcha(page, img_el)
                time.sleep(self.retry_interval_sec)
                continue

            logger.info(f"[{self.name}] 识别结果: {code_clean}")

            # 2.3 填验证码
            try:
                input_el.fill(code_clean)
            except Exception as e:
                logger.warning(f"[{self.name}] 填验证码失败: {e}")
                continue

            # 2.4 点登录
            if btn_el:
                try:
                    btn_el.click()
                except Exception as e:
                    logger.warning(f"[{self.name}] 点登录按钮失败: {e}")
            time.sleep(2)

            # 2.5 校验
            if self._is_login_success(page):
                logger.info(f"[{self.name}] ✅ 登录成功(尝试 {attempt} 次)")
                return True

            if self._has_error(page):
                logger.warning(f"[{self.name}] 验证码错误,刷新重试")
                self._refresh_captcha(page, img_el)
                time.sleep(self.retry_interval_sec)
                continue

            # 不确定状态,等一下再看
            time.sleep(2)
            if self._is_login_success(page):
                logger.info(f"[{self.name}] ✅ 登录成功(尝试 {attempt} 次,延迟确认)")
                return True

        logger.error(f"[{self.name}] ❌ {self.max_retries} 次识别都失败")
        _dump_captcha_debug(page, tag="all_retries_failed")
        return False


# ============================================================
# 人工输入
# ============================================================

class ManualSolver(CaptchaSolver):
    """人工输入验证码(在浏览器里手动填 + 提交)

    流程:
    - 等用户输入 + 提交
    - 轮询页面,等"我的/退出"等登录成功标志
    - 最多等 max_wait_sec 秒
    """

    name = "manual"

    def solve(self, page: Page, max_wait_sec: int = 300) -> bool:
        from .xiamenair import LOGIN_SUCCESS_MARKERS, LOGIN_FAILED_MARKERS

        logger.info("=" * 60)
        logger.info("MANUAL 模式:请在浏览器里输入 4 位验证码 + 点'登录'")
        logger.info(f"⏳ 程序会等 {max_wait_sec} 秒,登录成功会自动接管")
        logger.info("=" * 60)

        t0 = time.time()
        while time.time() - t0 < max_wait_sec:
            try:
                body_text = page.locator("body").inner_text(timeout=1500)
            except Exception:
                body_text = ""

            # 成功
            for marker in LOGIN_SUCCESS_MARKERS:
                if marker in body_text:
                    time.sleep(1)
                    try:
                        body_text2 = page.locator("body").inner_text(timeout=1500)
                    except Exception:
                        body_text2 = ""
                    if marker in body_text2:
                        logger.info("[manual] ✅ 登录成功")
                        return True

            # 失败
            for marker in LOGIN_FAILED_MARKERS:
                if marker in body_text:
                    logger.warning(f"[manual] 检测到错误提示: {marker!r}")
                    return False

            time.sleep(2)

        logger.error(f"[manual] {max_wait_sec} 秒内未登录,放弃")
        return False


# ============================================================
# 工厂:AutoSolver(ddddocr + fallback manual)
# ============================================================

class AutoSolver(CaptchaSolver):
    """默认 solver:先 ddddocr 识别 N 次,失败 fallback manual

    这是 verify_ticket 默认用的 solver
    """

    name = "auto"

    def __init__(self, ddddocr_max_retries: int = 3):
        self._ddddocr = DdddocrSolver(max_retries=ddddocr_max_retries)
        self._manual = ManualSolver()

    def solve(self, page: Page, max_wait_sec: int = 300) -> bool:
        if self._ddddocr._ocr:
            logger.info(f"[{self.name}] 先用 ddddocr 自动识别")
            ok = self._ddddocr.solve(page, max_wait_sec=60)
            if ok:
                return True
            logger.warning(f"[{self.name}] ddddocr 失败,fallback 人工输入")
        else:
            logger.info(f"[{self.name}] ddddocr 不可用,直接走人工输入")

        # fallback
        return self._manual.solve(page, max_wait_sec=max_wait_sec)


# ============================================================
# 诊断辅助(2026-07-27 加:每次截图保存,失败时 dump body 文本)
# ============================================================

import os as _os
from datetime import datetime as _dt


def _save_captcha_image(img_bytes: bytes, attempt: int) -> None:
    """保存 ddddocr 截到的验证码图片(让我能看截到啥)"""
    try:
        dir_path = _os.path.join("data", "screenshots")
        _os.makedirs(dir_path, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = _os.path.join(dir_path, f"captcha_attempt{attempt}_{ts}.png")
        with open(path, "wb") as f:
            f.write(img_bytes)
        logger.info(f"[ddddocr] 验证码图片已保存: {path}")
    except Exception as e:
        logger.warning(f"[ddddocr] 保存验证码图片失败: {e}")


def _dump_captcha_debug(page: Page, tag: str) -> None:
    """失败时 dump body 文本 + 截全页图"""
    try:
        body_text = page.locator("body").inner_text(timeout=3000)
    except Exception as e:
        logger.warning(f"[debug] 拿 body 失败: {e}")
        body_text = ""

    preview = body_text[:2000] if body_text else "(空)"
    logger.error(f"[debug] === body 预览(前 2000 字,tag={tag}) ===\n{preview}\n=== 预览结束 ===")

    try:
        dir_path = _os.path.join("data", "screenshots")
        _os.makedirs(dir_path, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        path = _os.path.join(dir_path, f"page_state_{tag}_{ts}.png")
        page.screenshot(path=str(path), full_page=True)
        logger.error(f"[debug] 全页截图: {path}")
    except Exception as e:
        logger.warning(f"[debug] 截全页图失败: {e}")


# ============================================================
# 工厂
# ============================================================

def make_solver(mode: str = "auto") -> CaptchaSolver:
    """根据 CLI 参数创建 solver

    Args:
        mode: auto / ddddocr / manual
    """
    mode = (mode or "auto").lower().strip()
    if mode == "ddddocr":
        return DdddocrSolver()
    if mode == "manual":
        return ManualSolver()
    if mode == "auto":
        return AutoSolver()
    raise ValueError(f"未知的 captcha mode: {mode!r},可选: auto / ddddocr / manual")
