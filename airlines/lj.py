"""LJ Jin Air 韩国真航空适配器 (2026-07-28 第三版: Playwright 拿 Cloudflare cookie + 直调 JSON API)

查票方式: PNR + 姓 + 名 + 出发日期
- Cloudflare 反爬: 先用 Playwright 打开 booking/index 过 challenge 拿 cf_clearance
- 数据接口: POST https://www.jinair.com/mypage/getReservationDetailJson?pnrNumber=<PNR>
  - 响应是完整 JSON (含 pnrStatusName/paxDetailList/segmentDetailList/flightCharge 等)
  - 2026-07-28 由用户 DevTools 实测确认 URL/格式
- 不再走填表,避免 Cloudflare 一直卡 0 inputs 的死循环
"""
import json
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

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
            "_method": "json_api",
            "_raw": None,
        }

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="zh-CN",
                )
                page = context.new_page()

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
                # 通常 3-5s,极少数情况 30s+
                waited = 0
                max_wait = 45
                cf_cookie_found = False
                while waited < max_wait:
                    cookies = context.cookies()
                    if any(c.get("name") == "cf_clearance" for c in cookies):
                        cf_cookie_found = True
                        break
                    page.wait_for_timeout(1000)
                    waited += 1

                result["_cf_wait_seconds"] = waited
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
                # Step 2: 用 context.request 调 JSON API(带 cf_clearance cookie)
                # ============================================================
                # URL 走 query string,body 空(JSON 格式),参考用户 DevTools 截图
                request_url = f"{API_URL}?pnrNumber={pnr}"
                try:
                    api_resp = context.request.post(
                        request_url,
                        headers={
                            "Accept": "application/json, text/plain, */*",
                            "Content-Type": "application/json",
                            "X-Requested-With": "XMLHttpRequest",
                        },
                        data="{}",  # 空 JSON body
                        timeout=self.timeout * 1000,
                    )
                    status = api_resp.status
                    text = api_resp.text()
                except PlaywrightTimeout:
                    result["_error"] = f"调 {API_URL} 超时 ({self.timeout}s)"
                    return result
                except Exception as e:
                    result["_error"] = f"调 {API_URL} 失败: {type(e).__name__}: {e}"
                    return result

                result["_http_status"] = status
                result["_http_url"] = request_url
                result["_http_text_preview"] = text[:500] if text else ""

                if status != 200:
                    result["_error"] = f"API 返回 HTTP {status}: {text[:300]}"
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
                    browser.close()
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
