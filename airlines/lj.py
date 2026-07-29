"""LJ Jin Air 韩国真航空适配器 (2026-07-29 第五版: 真实填表 + 拦截 XHR + 韩国代理)

查票方式: PNR + 姓 + 名 + 出发日期
- Cloudflare 反爬: Playwright + stealth 过 challenge 拿 cf_clearance
- 数据获取: 真实填写 booking/index 表单,拦截表单 onSubmit 触发的 XHR 响应
  - 接口: POST https://www.jinair.com/mypage/getReservationDetailJson?pnrNumber=<PNR>
  - 响应是完整 JSON (含 pnrStatusName/paxDetailList/segmentDetailList/flightCharge 等)
- 关键约束: 国内 IP 无法访问 jinair.com,必须配置 LJ_PROXY_URL 韩国代理
  - 2026-07-29 用户实测: Cloudflare 一直 403 = 国内 IP 被 Cloudflare 风控
  - 必须 http://user:pass@kr-proxy:port 或 socks5://user:pass@kr-proxy:port
  - 整个 Playwright 走代理(包括 DNS + TLS)
- 不用 page.evaluate(fetch) 的原因:
  - Cloudflare 在页面加载后做行为分析,纯 XHR 缺乏"用户交互"轨迹 → 403
  - 用真实表单提交,Cloudflare 信任,on('response') 拦截 XHR 直接拿 JSON
"""
import json
import os
import sys
import time
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

try:
    from playwright_stealth import Stealth as _StealthClass
    HAS_STEALTH = True
    _STEALTH_NEW_API = True
except ImportError:
    try:
        from playwright_stealth import stealth_sync  # 老 API (<2.0)
        HAS_STEALTH = True
        _STEALTH_NEW_API = False
    except ImportError:
        HAS_STEALTH = False
        _STEALTH_NEW_API = False

from .base import AirlineAdapter, FormField


# 数据接口地址(用户截图确认: POST, 响应 200 OK, 响应 Content-Type JSON)
API_URL = "https://www.jinair.com/mypage/getReservationDetailJson"

# 过 Cloudflare 的入口页(随便一个公开页都行,用 booking/index 顺便拿 form 让等待条件稳定)
WARMUP_URL = "https://www.jinair.com/booking/index"


class LJAdapter(AirlineAdapter):
    code = "lj"
    name = "LJ真航空"
    api_type = "custom"  # Playwright + 自定义 JSON API,不属于 4 种标准类型
    api_url = API_URL

    form_fields = [
        FormField("pnr", label="预订号码 (PNR)", placeholder="如:H3T96P"),
        FormField("lastName", label="姓 (LAST NAME)", placeholder="如:LIN"),
        FormField("firstName", label="名 (FIRST NAME)", placeholder="如:WENFENG"),
        FormField("departDate", label="出发日期", placeholder="2026-08-06", field_type="date"),
    ]

    def _call_api(self, form_data: dict):
        pnr = form_data.get("pnr", "").strip().upper()
        last_name = form_data.get("lastName", "").strip().upper()
        first_name = form_data.get("firstName", "").strip().upper()
        depart_date = form_data.get("departDate", "").strip()  # YYYY-MM-DD

        if not pnr or not last_name or not first_name or not depart_date:
            return {"_error": "请填写完整的预订号码 / 姓 / 名 / 出发日期"}

        result = {
            "pnr": pnr,
            "lastName": last_name,
            "firstName": first_name,
            "departDate": depart_date,
            "_html": "",
            "_method": "form_submit_intercept",
            "_raw": None,
        }

        # ============================================================
        # 2026-07-29: 解析代理 URL(国内 IP 无法访问韩国航司站)
        # ============================================================
        # LJ_PROXY_URL 格式:
        #   http://user:pass@host:port
        #   https://user:pass@host:port
        #   socks5://user:pass@host:port
        # 没配: 本地开发用系统 VPN 即可,生产环境(Railway)才强制要求
        proxy_url = os.environ.get("LJ_PROXY_URL", "").strip()
        is_railway = bool(os.environ.get("RAILWAY_ENVIRONMENT")) or bool(os.environ.get("RAILWAY_PROJECT_ID"))
        proxy_config = None

        if proxy_url:
            try:
                parsed = urlparse(proxy_url)
                proxy_config = {
                    "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                }
                if parsed.username:
                    proxy_config["username"] = parsed.username
                    proxy_config["password"] = parsed.password or ""
                # 记录到 result 但隐藏密码
                safe_url = proxy_url
                if "@" in safe_url:
                    safe_url = safe_url.split("@", 1)[0].split("://", 1)[0] + "://***@" + safe_url.split("@", 1)[1]
                result["_proxy"] = safe_url
            except Exception as e:
                return {
                    **result,
                    "_error": f"LJ_PROXY_URL 解析失败: {type(e).__name__}: {e}",
                }
        elif is_railway:
            # Railway 部署 = 生产,必须配代理
            return {
                **result,
                "_error": (
                    "Railway 部署必须配 LJ_PROXY_URL — 国内 IP 无法访问 jinair.com "
                    "(Cloudflare 直接 403),需在 Railway Variables 配韩国代理 "
                    "(支持 http(s)://user:pass@host:port 或 socks5://user:pass@host:port)"
                ),
            }
        else:
            # 本地开发:不强制配代理,直接走 TUN/系统网络
            # 2026-07-29 不再 auto-detect 系统代理 —— 跟 TUN 模式冲突,见日志
            result["_proxy"] = None
            result["_proxy_warn"] = (
                "未配 LJ_PROXY_URL,本机依赖 TUN/全局模式(VPN 客户端的 OS 层劫持)。"
                "如果你的 VPN 是系统代理模式(Windows 设置了 127.0.0.1:xxx),需要显式配 LJ_PROXY_URL。"
                "部署 Railway 前必须显式配。"
            )

        with sync_playwright() as p:
            # 2026-07-28: 加 launch args 减少被 Cloudflare 识别为 headless bot
            # --disable-blink-features=AutomationControlled: 隐藏 navigator.webdriver
            # --disable-features=AutomationControlled: 同上(Chrome 96+ 需要)
            # 2026-07-29: 支持用系统 Chrome profile(LJ_USE_CHROME_PROFILE=1)
            # 借用用户的 Chrome 二进制 + profile(包括 cookies、扩展、历史)
            # → 浏览器指纹、TLS 指纹、cookies 全部一致,Cloudflare 认成「同一个人」
            # 前提:用户先关掉 Chrome(profile 被锁启动不了)
            #
            # 关键:Chrome 拒绝在「默认 profile 目录」上开 DevTools remote debugging,
            # 所以必须先把 profile 复制到独立目录
            use_chrome_profile = os.environ.get("LJ_USE_CHROME_PROFILE", "").strip().lower() in ("1", "true", "yes")
            chrome_user_data = None
            if use_chrome_profile:
                if sys.platform == "win32":
                    source_profile = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
                    target_profile = os.path.expandvars(r"%LOCALAPPDATA%\PlaywrightChromeProfile")
                elif sys.platform == "darwin":
                    source_profile = os.path.expanduser("~/Library/Application Support/Google/Chrome")
                    target_profile = os.path.expanduser("~/.playwright_chrome_profile")
                else:
                    source_profile = os.path.expanduser("~/.config/google-chrome")
                    target_profile = os.path.expanduser("~/.playwright_chrome_profile")

                # 允许通过 LJ_CHROME_PROFILE_DIR 覆盖 target
                env_target = os.environ.get("LJ_CHROME_PROFILE_DIR", "").strip()
                if env_target:
                    target_profile = env_target

                if not os.path.exists(source_profile):
                    result["_warn_chrome_profile"] = (
                        f"LJ_USE_CHROME_PROFILE=1 但找不到 Chrome source profile: {source_profile}"
                    )
                else:
                    # 如果 target 不存在,复制(排除缓存目录加速)
                    if not os.path.exists(target_profile):
                        try:
                            import shutil
                            result["_chrome_profile_copying"] = (
                                f"首次启动,正在复制 Chrome profile 到 {target_profile} ..."
                            )
                            ignore_patterns = shutil.ignore_patterns(
                                "Cache", "Code Cache", "Service Worker", "GPUCache",
                                "ShaderCache", "GraphiteDawnCache",
                                "optimization_guide_model_browser_process",
                            )
                            shutil.copytree(source_profile, target_profile, ignore=ignore_patterns)
                            result["_chrome_profile_copied"] = True
                        except Exception as e:
                            result["_warn_chrome_profile"] = (
                                f"复制 Chrome profile 失败: {type(e).__name__}: {e}"
                            )
                            target_profile = None
                    chrome_user_data = target_profile

            if chrome_user_data:
                # 用系统 Chrome + 用户的 profile(持久化 context,cookies 共享)
                # 2026-07-29 关键修复:ignore_default_args=["--enable-automation"]
                #   Playwright 默认会加 --enable-automation,这个 flag 直接把
                #   navigator.webdriver 设为 true,Cloudflare 第一眼就识破
                #   我们用 --disable-blink-features=AutomationControlled 掩盖只能骗
                #   简单检测,Cloudflare 这种高级 WAF 还是查得到启动参数
                context = p.chromium.launch_persistent_context(
                    user_data_dir=chrome_user_data,
                    channel="chrome",  # 用系统 Chrome,不是 bundled Chromium
                    headless=True,
                    no_viewport=True,
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    permissions=["geolocation", "notifications"],
                    proxy=proxy_config,
                    ignore_default_args=["--enable-automation"],
                )
                page = context.pages[0] if context.pages else context.new_page()
                result["_chrome_profile"] = chrome_user_data
                result["_no_enable_automation"] = True
                browser = None  # launch_persistent_context 已经管理生命周期
            else:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                    ],
                    ignore_default_args=["--enable-automation"],  # 2026-07-29: 关键
                    proxy=proxy_config,  # 显式代理(LJ_PROXY_URL 设了才用,否则 None = 走 TUN)
                )
                context = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    permissions=["geolocation", "notifications"],
                )

                # 兜底: 先用 context 级 init script 隐藏最显眼的自动化标志
                # (navigator.webdriver 一定要是 undefined,Cloudflare 第一眼查的)
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                """)

                page = context.new_page()

            # playwright-stealth: 全面伪装浏览器指纹(plugins / languages / chrome runtime / webgl 等)
            # v2.0+ API: Stealth().apply_stealth_sync(page)
            # v1.0 API: stealth_sync(page)
            # 持久化 Chrome 模式下不需要 stealth(已经是真 Chrome),但用也无害
            if HAS_STEALTH and not chrome_user_data:
                try:
                    if _STEALTH_NEW_API:
                        _StealthClass().apply_stealth_sync(page)
                    else:
                        stealth_sync(page)
                except Exception as e:
                    result["_warn_stealth"] = f"stealth apply 失败: {e}"

            try:

                # ============================================================
                # Step 1: 打开 booking/index 过 Cloudflare challenge
                # ============================================================
                try:
                    page.goto(WARMUP_URL, wait_until="domcontentloaded",
                              timeout=self.timeout * 1000)
                except PlaywrightTimeout:
                    result["_error"] = f"打开 {WARMUP_URL} 超时"
                    return result

                # 等 cf_clearance cookie 出现(Cloudflare 验证通过的标志)
                # stealth 后通常 3-8s,极端情况 30s+,给到 60s
                # Cloudflare 偶发需要二次刷新才放行,所以失败时再 reload 一次
                waited = 0
                max_wait = 60
                cf_cookie_found = False

                for attempt in (1, 2):  # 第 1 次正常等,失败 reload 再等
                    if attempt == 2:
                        try:
                            page.reload(wait_until="domcontentloaded", timeout=30000)
                        except Exception:
                            pass

                    waited = 0
                    while waited < max_wait:
                        cookies = context.cookies()
                        if any(c.get("name") == "cf_clearance" for c in cookies):
                            cf_cookie_found = True
                            break
                        page.wait_for_timeout(1000)
                        waited += 1

                    if cf_cookie_found:
                        result["_cf_attempts"] = attempt
                        result["_cf_wait_seconds"] = waited
                        break

                if not cf_cookie_found:
                    # 兜底: 看页面是不是被 challenge 页面挡住
                    title = page.title()
                    body_text = ""
                    try:
                        body_text = page.locator("body").inner_text()[:200]
                    except Exception:
                        pass
                    result["_error"] = (
                        f"未通过 Cloudflare 验证 (等了 {waited}s, title={title!r}, "
                        f"body={body_text!r})"
                    )
                    return result

                # ============================================================
                # Step 2: 等表单渲染(Cloudflare 过了之后 SPA 才挂 form)
                # ============================================================
                waited = 0
                max_form_wait = 30
                input_count = 0
                while waited < max_form_wait:
                    inputs = page.locator('input').all()
                    input_count = len(inputs)
                    if input_count >= 4:
                        break
                    page.wait_for_timeout(1000)
                    waited += 1
                result["_form_wait_seconds"] = waited
                result["_input_count"] = input_count

                if input_count < 4:
                    result["_error"] = (
                        f"表单未渲染(等了 {waited}s, 只找到 {input_count} 个 input, "
                        f"page_title={page.title()!r})"
                    )
                    try:
                        result["_html"] = page.content()[:2000]
                    except Exception:
                        pass
                    return result

                # ============================================================
                # Step 3: 真实填表 + 拦截 XHR 响应(2026-07-28 第三次重构)
                # ============================================================
                # 为什么不用 page.evaluate(fetch):
                #   Cloudflare 在页面加载后做行为分析,纯 XHR 没有"用户交互"轨迹(没鼠标/滚动/等待),
                #   直接 fetch 拿不到 cf_clearance 的完整信任,返回 403 + 拦截页
                # 为什么 form submit 有效:
                #   浏览器原生 form 提交是 Cloudflare 默认信任的"真人行为",配 XHR 是表单 onSubmit 触发,
                #   行为轨迹和真实用户 100% 一致
                # 拦截 on('response') 拿到 XHR 响应,避免解析 HTML 结果页

                # 监听 XHR 响应
                api_response_data = []
                def on_response(response):
                    if 'getReservationDetailJson' in response.url:
                        try:
                            req = response.request
                            api_response_data.append({
                                'status': response.status,
                                'text': response.text(),  # 同步 str (Playwright sync API)
                                'url': response.url,
                                'resource_type': req.resource_type,  # 'xhr' / 'fetch' / 'document'
                                'method': req.method,
                            })
                        except Exception as e:
                            api_response_data.append({'error': str(e), 'url': response.url})
                page.on('response', on_response)

                # 填表(用 keyboard.type 模拟真人打字,不是 fill() 直接 setValue)
                #   2026-07-29 关键: fill() 是 setValue + 1 个 input 事件,不像真人
                #   Cloudflare 行为分析能识别「200ms 内填完 4 字段+立刻点提交」= bot
                #   keyboard.type 每个字符间有真实 keydown/keyup/input 事件 + 间隔
                try:
                    inputs = page.locator('input').all()

                    # 模拟"读页面"的思考时间
                    page.wait_for_timeout(1500)

                    # 字段 1: PNR(大写字母)
                    inputs[0].click(timeout=5000)
                    page.wait_for_timeout(300)
                    page.keyboard.type(pnr, delay=80)  # 每字符 80ms
                    page.wait_for_timeout(500)

                    # 字段 2: 姓
                    inputs[1].click(timeout=5000)
                    page.wait_for_timeout(300)
                    page.keyboard.type(last_name, delay=80)
                    page.wait_for_timeout(500)

                    # 字段 3: 名
                    inputs[2].click(timeout=5000)
                    page.wait_for_timeout(300)
                    page.keyboard.type(first_name, delay=80)
                    page.wait_for_timeout(500)

                    # 字段 4: 出发日期(date 类型 input 也吃 type 事件,只是格式必须是 YYYY-MM-DD)
                    inputs[3].click(timeout=5000)
                    page.wait_for_timeout(300)
                    page.keyboard.type(depart_date, delay=60)
                    page.wait_for_timeout(1000)  # "看完再提交"的停顿

                    result["_fill_ok"] = True
                    result["_fill_method"] = "keyboard.type"
                except Exception as e:
                    result["_error"] = f"填表失败: {type(e).__name__}: {e}"
                    return result

                # 点提交(也用 mouse.move 模拟真实光标轨迹)
                try:
                    submit_btn = page.locator(
                        'button[type="submit"], button:has-text("查询"), a:has-text("查询")'
                    ).first
                    box = submit_btn.bounding_box()
                    if box:
                        # 从屏幕中心慢慢移动到按钮(分 5 步)
                        start_x, start_y = 640, 400
                        end_x = box["x"] + box["width"] / 2
                        end_y = box["y"] + box["height"] / 2
                        page.mouse.move(start_x, start_y)
                        for step in range(1, 6):
                            page.mouse.move(
                                start_x + (end_x - start_x) * step / 5,
                                start_y + (end_y - start_y) * step / 5,
                                steps=5,
                            )
                        page.wait_for_timeout(200)
                    submit_btn.click(timeout=5000)
                    result["_click_ok"] = True
                except Exception as e:
                    result["_error"] = f"点提交按钮失败: {type(e).__name__}: {e}"
                    return result

                # 等 API 响应
                waited = 0
                max_api_wait = 30
                while not api_response_data and waited < max_api_wait:
                    page.wait_for_timeout(1000)
                    waited += 1
                result["_api_wait_seconds"] = waited

                if not api_response_data:
                    result["_error"] = (
                        f"提交后未收到 API 响应 (等了 {waited}s, "
                        f"page_url={page.url!r})"
                    )
                    return result

                api_data = api_response_data[0]
                if api_data.get("error"):
                    result["_error"] = f"响应回调失败: {api_data['error']}"
                    return result

                status = api_data.get("status")
                text = api_data.get("text", "")
                resource_type = api_data.get("resource_type", "?")
                req_method = api_data.get("method", "?")
                result["_http_status"] = status
                result["_http_url"] = api_data.get("url", "")
                result["_http_resource_type"] = resource_type
                result["_http_method"] = req_method
                result["_http_text_preview"] = text[:500] if text else ""

                if status != 200:
                    # 区分: 是 Cloudflare 拦截页(<!DOCTYPE html>)还是真的 API 错误响应
                    is_cf_block = text.lstrip().startswith("<!DOCTYPE html>") or "Attention Required" in text[:2000]
                    block_type = "Cloudflare 拦截页" if is_cf_block else "API 错误"
                    result["_error"] = (
                        f"{block_type} (HTTP {status}, type={resource_type}, "
                        f"method={req_method}): {text[:300]}"
                    )
                    result["_is_cf_block"] = is_cf_block
                    return result

                # ============================================================
                # Step 3: 解析 JSON
                # ============================================================
                try:
                    data = json.loads(text)
                except json.JSONDecodeError as e:
                    result["_error"] = f"响应不是 JSON: {e} (前 200 字符: {text[:200]!r})"
                    return result

                result["_raw"] = data
                return result

            except Exception as e:
                import traceback
                result["_error"] = f"未捕获异常: {type(e).__name__}: {e}"
                result["_traceback"] = traceback.format_exc()[:1500]
                return result
            finally:
                try:
                    if browser is not None:
                        browser.close()
                    else:
                        # 持久化 context 模式:关掉 context
                        context.close()
                except Exception:
                    pass

    def _parse(self, raw) -> dict:
        if not isinstance(raw, dict):
            return {"success": False, "error": f"未获取到有效数据: {raw}"}

        if raw.get("_error"):
            return {"success": False, "error": raw["_error"]}

        data = raw.get("_raw")
        if not isinstance(data, dict):
            return {"success": False, "error": "无有效响应数据"}

        # 验证 PNR 匹配(API 返回的 PNR 应等于输入的 PNR)
        api_pnr = (data.get("pnrNumber") or "").strip().upper()
        input_pnr = (raw.get("pnr") or "").strip().upper()
        if api_pnr and api_pnr != input_pnr:
            return {
                "success": False,
                "error": f"API 返回的 PNR ({api_pnr}) 与输入 ({input_pnr}) 不符",
            }

        # 提取关键字段
        pax_list = data.get("paxDetailList") or []
        seg_list = data.get("segmentDetailList") or []
        flight_charge = data.get("flightCharge") or {}
        basic_charge = data.get("basicCharge") or {}
        fuel_charge = data.get("fuelCharge") or {}

        # 验证姓氏匹配(防止 PNR 撞库返回别人的数据)
        input_last = (raw.get("lastName") or "").strip().upper()
        input_first = (raw.get("firstName") or "").strip().upper()
        pax_surnames = [
            (p.get("displaySurName") or p.get("surName") or "").strip().upper()
            for p in pax_list
        ]
        pax_given = [
            (p.get("displayGivenName") or p.get("givenName") or "").strip().upper()
            for p in pax_list
        ]
        name_match = (
            input_last in pax_surnames if pax_surnames else True
        )
        first_name_warning = ""
        if pax_given and input_first not in pax_given:
            first_name_warning = (
                f"⚠️ 输入的名 ({input_first}) 不在乘客列表中 "
                f"({', '.join(pax_given)})"
            )

        try:
            output = []
            output.append("=" * 50)
            output.append("查询成功 (LJ Jin Air 韩国真航空)")
            output.append("=" * 50)
            output.append("")

            output.append("【订单信息】")
            output.append(f"预订号码: {api_pnr or 'N/A'}")
            output.append(f"创建时间: {data.get('creationDateAndTime', 'N/A')}")
            output.append(f"预订状态: {data.get('pnrStatusName', 'N/A')}")
            output.append(f"乘客数: {data.get('paxCount', 'N/A')}")
            if not name_match:
                output.append(f"⚠️ 姓氏校验: 输入 ({input_last}) 不在乘客列表 ({', '.join(pax_surnames)})")
            if first_name_warning:
                output.append(first_name_warning)

            # 乘客
            if pax_list:
                output.append("")
                output.append("【乘客信息】")
                for pax in pax_list:
                    name = f"{pax.get('displaySurName') or pax.get('surName', '')}/" \
                           f"{pax.get('displayGivenName') or pax.get('givenName', '')}"
                    output.append(
                        f"  • {name} | {pax.get('guestType', 'N/A')} | "
                        f"出生: {pax.get('dateOfBirth', 'N/A')} | "
                        f"性别: {pax.get('gender', 'N/A')}"
                    )

            # 行程
            if seg_list:
                output.append("")
                output.append("【行程信息】")
                for seg in seg_list:
                    flight = f"{seg.get('carrierCode', '')}{seg.get('flightNumber', '')}"
                    route = f"{seg.get('boardPoint', '')} → {seg.get('offPoint', '')}"
                    board = seg.get("boardPointName", "")
                    off = seg.get("offPointName", "")
                    route_full = f"{route} ({board} → {off})" if board else route
                    output.append(f"  ✈ {flight}  {route_full}")
                    output.append(f"    出发: {seg.get('departureDate', 'N/A')}")
                    output.append(f"    到达: {seg.get('arrivalDate', 'N/A')}")
                    output.append(f"    舱位: {seg.get('fareClass', 'N/A')}")
                    output.append(f"    状态: {seg.get('segmentStatus', 'N/A')} ({seg.get('segmentCheckIn', '')})")

            # 费用
            if flight_charge or basic_charge or fuel_charge:
                output.append("")
                output.append("【费用明细】")
                output.append(f"  货币: {data.get('currency', 'N/A')}")
                output.append(f"  票价税: {flight_charge.get('totalTax', 'N/A')}")
                output.append(f"  基础税: {basic_charge.get('totalTax', 'N/A')}")
                output.append(f"  燃油税: {fuel_charge.get('totalTax', 'N/A')}")
                # 简单求和(粗略)
                try:
                    total = (
                        (flight_charge.get("totalTax") or 0)
                        + (basic_charge.get("totalTax") or 0)
                        + (fuel_charge.get("totalTax") or 0)
                    )
                    if total > 0:
                        output.append(f"  税费合计: {total} {data.get('currency', '')}")
                except (TypeError, Exception):
                    pass

            # 支付信息(脱敏)
            payments = data.get("guestPaymentInfo") or []
            if payments:
                output.append("")
                output.append("【支付方式】")
                for pay in payments:
                    method = pay.get("paymentMethod", "N/A")
                    number = pay.get("paymentNumber", "N/A")
                    # 已经在响应里是脱敏的(486711XXXXXX9881),保留显示
                    output.append(f"  • {method} {number} | 金额: {pay.get('paymentAmount', 'N/A')} {pay.get('currency', '')}")

            return {
                "success": True,
                "data": "\n".join(output),
                "flight_info": {
                    "pnr": api_pnr,
                    "creationDate": data.get("creationDateAndTime"),
                    "status": data.get("pnrStatusName"),
                    "paxCount": data.get("paxCount"),
                    "pax": [
                        {
                            "name": f"{p.get('displaySurName') or p.get('surName', '')}/{p.get('displayGivenName') or p.get('givenName', '')}",
                            "type": p.get("guestType"),
                            "dob": p.get("dateOfBirth"),
                            "gender": p.get("gender"),
                        }
                        for p in pax_list
                    ],
                    "segments": [
                        {
                            "flight": f"{s.get('carrierCode', '')}{s.get('flightNumber', '')}",
                            "from": s.get("boardPoint"),
                            "fromName": s.get("boardPointName"),
                            "to": s.get("offPoint"),
                            "toName": s.get("offPointName"),
                            "depart": s.get("departureDate"),
                            "arrive": s.get("arrivalDate"),
                            "fareClass": s.get("fareClass"),
                            "status": s.get("segmentStatus"),
                        }
                        for s in seg_list
                    ],
                    "currency": data.get("currency"),
                    "totalTax": (flight_charge.get("totalTax") or 0)
                    + (basic_charge.get("totalTax") or 0)
                    + (fuel_charge.get("totalTax") or 0),
                    "payments": [
                        {
                            "method": p.get("paymentMethod"),
                            "number": p.get("paymentNumber"),
                            "amount": p.get("paymentAmount"),
                            "currency": p.get("currency"),
                        }
                        for p in payments
                    ],
                },
            }
        except Exception as e:
            import traceback
            return {
                "success": False,
                "error": f"解析失败: {type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[:1500],
            }
