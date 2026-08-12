"""VN 越南航空适配器 (Vietnam Airlines) - Playwright 真填表路线

页面: https://www.vietnamairlines.com/cn/zh/buy-tickets-other-products/booking-and-manage-bookings/reservation-management

流程 (2026-08-11 实测):
  1. 打开管理预订页面,过 Cloudflare (__cf_bm cookie)
  2. 隐藏 OneTrust cookie 同意弹窗遮罩 (否则拦截点击)
  3. 等 PNR + 姓 input 渲染
  4. 真实填表:用 nativeInputValueSetter 触发 React onChange (否则前端校验说"必填项")
  5. 点击 <span class="label">搜寻</span> 触发 SPA 表单提交
  6. 拦截 on('response') 拿 GET /api/v1/public/reservation/pnr/{PNR}?lastName={LASTNAME} 的 JSON
  7. 解析 + 返回 (参考 sample JSON)

关键约束:
  - 国内能正常打开,不需要代理
  - 浏览器要带真实 UA + locale=zh-CN,避免被识别为 headless bot
  - 提交流程是 React 受控表单,必须用 nativeInputValueSetter
  - 提交按钮是 <span> 不是 <button>,事件委托到根节点

API 返回 JSON 结构 (来自用户提供的 sample):
  {
    "success": true,
    "code": "0",
    "data": {
      "reservation": {
        "pnrCode": "FBXT35",
        "alreadyTicketed": true,
        "passengers": [
          { "firstName", "lastName", "title", "dateOfBirth", "gender",
            "ticketNumber", "ticketDocument": { ..., "coupons": [...] } }
        ],
        "originDestinationOptions": [ { "flightSegments": [...] } ]
      }
    }
  }

票状态判定:
  - hasRefundedCoupon=true       -> 已退票
  - hasExchangedCoupon=true      -> 已改期
  - 所有 coupon segmentUsed=true -> 已使用
  - otherwise + alreadyTicketed  -> 已开票/未使用
  - alreadyTicketed=false        -> 未出票
"""
import os
import sys
from playwright.sync_api import sync_playwright


from .base import AirlineAdapter, FormField


WARMUP_URL = "https://www.vietnamairlines.com/cn/zh/buy-tickets-other-products/booking-and-manage-bookings/reservation-management"
# 拦截 API: GET /api/v1/public/reservation/pnr/{PNR}?lastName={LASTNAME}
API_URL_PATTERN = "/api/v1/public/reservation/pnr/"


# 隐藏 OneTrust cookie 同意弹窗遮罩
HIDE_OT_JS = r"""
() => {
    const ot = document.getElementById('onetrust-consent-sdk');
    if (ot) ot.remove();
    document.querySelectorAll('.onetrust-pc-dark-filter, [id*="onetrust"]').forEach(el => el.remove());
    // 隐藏其他可能遮罩
    document.querySelectorAll('[class*="cookie-consent"], [class*="cmp-cookie"], [id*="cookie"]').forEach(el => {
        if (el.offsetParent !== null) {
            try { el.style.display = 'none'; } catch(e) {}
        }
    });
}
"""


class VNAdapter(AirlineAdapter):
    code = "vn"
    name = "VN越南航空"
    api_type = "custom"  # Playwright + 自定义 JSON API
    api_url = WARMUP_URL

    form_fields = [
        FormField("pnr", label="预定代码(PNR) / 电子票号", placeholder="如：FBXT35 / 7382422836952"),
        FormField("lastName", label="姓", placeholder="如：PHAM (大写)"),
    ]

    def _call_api(self, form_data: dict):
        pnr = form_data.get("pnr", "").strip().upper()
        last_name = form_data.get("lastName", "").strip().upper()
        if not pnr or not last_name:
            return {"_error": "请填写完整的 PNR/电子票号 + 姓"}

        result = {
            "pnr": pnr,
            "lastName": last_name,
            "_raw": None,
        }

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
                ignore_default_args=["--enable-automation"],
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
            )
            # 隐藏 webdriver 标志
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)

            # 拦截 XHR 响应
            api_responses = []
            def on_response(response):
                try:
                    if API_URL_PATTERN in response.url:
                        api_responses.append({
                            "status": response.status,
                            "text": response.text(),
                            "url": response.url,
                        })
                except Exception as e:
                    pass
            page = context.new_page()
            page.on("response", on_response)

            try:
                # Step 1: 打开管理预订页
                page.goto(WARMUP_URL, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                page.wait_for_timeout(3000)
                page.evaluate(HIDE_OT_JS)
                page.wait_for_timeout(1000)

                # Step 2: 等表单渲染 (2 个 input.booking-input)
                waited = 0
                while waited < 30:
                    inputs = page.locator("input.booking-input").all()
                    if len(inputs) >= 2:
                        break
                    page.wait_for_timeout(1000)
                    waited += 1
                if len(inputs) < 2:
                    return {"_error": f"表单渲染超时 ({waited}s)"}

                # Step 3: 真实填表 (React 兼容: nativeInputValueSetter 触发 onChange)
                # 用 evaluate 一次性填完两个字段 + 触发 React state 同步
                filled = page.evaluate(r"""
                    (args) => {
                        const [pnr, lastname] = args;
                        const inputs = document.querySelectorAll('input.booking-input');
                        if (inputs.length < 2) return {ok: false, reason: 'inputs not found'};
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        // PNR
                        inputs[0].focus();
                        setter.call(inputs[0], pnr);
                        inputs[0].dispatchEvent(new Event('input', {bubbles: true}));
                        inputs[0].dispatchEvent(new Event('change', {bubbles: true}));
                        // 姓
                        inputs[1].focus();
                        setter.call(inputs[1], lastname);
                        inputs[1].dispatchEvent(new Event('input', {bubbles: true}));
                        inputs[1].dispatchEvent(new Event('change', {bubbles: true}));
                        // 再次清理 OneTrust (可能在填表过程中弹了)
                        document.querySelectorAll('[id*="onetrust"], [class*="onetrust"]').forEach(el => el.remove());
                        return {ok: true, pnrValue: inputs[0].value, lastnameValue: inputs[1].value};
                    }
                """, [pnr, last_name])
                if not filled or not filled.get("ok"):
                    return {"_error": f"填表失败: {filled}"}

                # Step 4: 点 <span class="label">搜寻</span> 触发 React 表单提交
                # 关键: React 不监听 dispatchEvent 派发的 synthetic event, 必须用真实 mouse click
                try:
                    label_locator = page.locator('span.label').filter(has_text='搜寻').first
                    # 用真实 Playwright click (CDP mouse event), 触发 React onClick
                    label_locator.click(timeout=5000, force=True)
                    clicked = {"ok": True, "method": "page.locator click"}
                except Exception as e:
                    clicked = {"ok": False, "reason": f"locator click failed: {e}"}
                if not clicked.get("ok"):
                    return {"_error": f"点击搜寻失败: {clicked}"}

                # 兜底: 也 dispatch 一个 synthetic event (有些 SPA 同时绑了 native handler)
                try:
                    page.evaluate(r"""
                        () => {
                            const label = Array.from(document.querySelectorAll('span.label')).find(s => s.textContent.trim() === '搜寻');
                            if (!label) return false;
                            const rect = label.getBoundingClientRect();
                            const evt = new MouseEvent('click', {bubbles: true, cancelable: true, view: window, clientX: rect.x + rect.width/2, clientY: rect.y + rect.height/2});
                            label.dispatchEvent(evt);
                            return true;
                        }
                    """)
                except Exception:
                    pass

                # Step 5: 等 XHR 响应 (VN 反应慢, 给 30s)
                waited = 0
                while waited < 30:
                    if api_responses:
                        break
                    page.wait_for_timeout(1000)
                    waited += 1

                if not api_responses:
                    # 看页面状态变化 (错误提示可能直接显示在页面)
                    body = page.evaluate("() => document.body.innerText.slice(0, 500)")
                    return {"_error": f"提交后未收到 API 响应 (等了 {waited}s), body: {body}"}

                # 取第一个 2xx 响应
                for resp in api_responses:
                    if 200 <= resp["status"] < 300:
                        try:
                            result["_raw"] = resp["text"]  # str
                            return result
                        except Exception as e:
                            return {"_error": f"解析响应失败: {e}"}

                # 全部非 2xx
                return {"_error": f"API 返回非 2xx: {[(r['status'], r['url'][:80]) for r in api_responses]}"}

            except Exception as e:
                return {"_error": f"{type(e).__name__}: {e}"}
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

        return result

    def _parse(self, raw) -> dict:
        try:
            if isinstance(raw, dict) and raw.get("_error"):
                return {"success": False, "error": raw["_error"]}

            # raw 是 Playwright 拿到的 str (response.text())
            import json
            if isinstance(raw, str):
                data = json.loads(raw)
            elif isinstance(raw, dict) and "_raw" in raw and isinstance(raw["_raw"], str):
                data = json.loads(raw["_raw"])
            elif isinstance(raw, dict):
                data = raw
            else:
                return {"success": False, "error": f"无法解析的响应类型: {type(raw)}"}

            if not data.get("success"):
                msg = data.get("message") or data.get("msg") or "查询失败"
                return {"success": False, "error": f"VN API 返回失败: {msg}"}

            reservation = data.get("data", {}).get("reservation", {})
            if not reservation:
                return {"success": False, "error": "未找到订单信息"}

            output = []
            output.append("=" * 55)
            output.append("VN 越南航空 - 客票验真")
            output.append("=" * 55)

            # ===== 订单信息 =====
            output.append("")
            output.append("【订单信息】")
            output.append(f"PNR (预定代码): {reservation.get('pnrCode', 'N/A')}")
            output.append(f"渠道: {reservation.get('oidChannel', 'N/A')} ({reservation.get('oidSource', 'N/A')})")
            output.append(f"票台: {reservation.get('bookedOnPcc', 'N/A')}")
            output.append(f"出票 PCC: {reservation.get('issuedOnPcc', 'N/A')}")
            output.append(f"订票时间(UTC): {str(reservation.get('bookedUtcDate', ''))[:19].replace('T', ' ')}")
            output.append(f"出票时间(UTC): {str(reservation.get('issuedUtcDate', ''))[:19].replace('T', ' ')}")
            output.append(f"航程类型: {reservation.get('tripTypeCode', 'N/A')} ({'单程' if reservation.get('tripTypeCode') == 'OW' else '往返' if reservation.get('tripTypeCode') == 'RT' else '其他'})")
            output.append(f"支付方式: {', '.join(reservation.get('bookingPaymentTypes', []))}")
            output.append(f"总价: {reservation.get('totalAmount', 'N/A')} {reservation.get('currencyCode', '')}")
            output.append(f"已开票: {'是' if reservation.get('alreadyTicketed') else '否'}")

            contact_emails = reservation.get("contactEmails", [])
            contact_phones = reservation.get("contactPhoneNumbers", [])
            if contact_emails or contact_phones:
                output.append("联系人:")
                for e in contact_emails:
                    output.append(f"  邮箱: {e}")
                for p in contact_phones:
                    output.append(f"  电话: {p}")

            # ===== 乘客信息 =====
            passengers = reservation.get("passengers", [])
            output.append("")
            output.append(f"【乘客人信息】(共 {len(passengers)} 人)")
            for idx, pax in enumerate(passengers, 1):
                title = pax.get("title", "")
                first = pax.get("firstName", "")
                last = pax.get("lastName", "")
                pax_name = f"{title} {first} {last}".strip()
                output.append(f"  [{idx}] {pax_name}")
                output.append(f"      类型: {pax.get('passengerTypeCode', 'N/A')}")
                if pax.get("dateOfBirth"):
                    output.append(f"      出生日期: {pax['dateOfBirth']}")
                if pax.get("gender"):
                    output.append(f"      性别: {pax['gender']}")
                ticket_no = pax.get("ticketNumber") or (pax.get("ticketDocument", {}) or {}).get("ticketNumber")
                if ticket_no:
                    output.append(f"      票号: {ticket_no}")

            # ===== 航班段信息 =====
            output.append("")
            output.append("【航班信息】")
            origin_opts = reservation.get("originDestinationOptions", [])
            if not origin_opts:
                output.append("  (无航班信息)")
            else:
                for opt in origin_opts:
                    for seg in opt.get("flightSegments", []):
                        airline = seg.get("marketingAirlineCode", "VN")
                        flight_no = seg.get("flightNumber", "N/A")
                        dep = seg.get("departureLocationCode", "N/A")
                        arr = seg.get("arrivalLocationCode", "N/A")
                        dep_dt = str(seg.get("departureDateTime", "")).replace("T", " ")[:16]
                        arr_dt = str(seg.get("arrivalDateTime", "")).replace("T", " ")[:16]
                        cabin = seg.get("classOfService", "N/A")
                        aircraft = seg.get("airEquipmentCode", "")
                        flight_time = seg.get("flightTime", "")

                        line = f"  {airline}{flight_no} {dep} → {arr}"
                        output.append(line)
                        output.append(f"      出发: {dep_dt} | 到达: {arr_dt}")
                        output.append(f"      舱位: {cabin}" + (f" | 机型: {aircraft}" if aircraft else ""))
                        if flight_time:
                            output.append(f"      飞行时长: {flight_time} 分钟")
                        if seg.get("arrivalTerminalName"):
                            output.append(f"      到达航站楼: {seg['arrivalTerminalName']}")

            # ===== 票号详细状态 (核心: 出票状态 / 已使用 / 已退) =====
            output.append("")
            output.append("【票号状态详情】")
            for idx, pax in enumerate(passengers, 1):
                title = pax.get("title", "")
                first = pax.get("firstName", "")
                last = pax.get("lastName", "")
                pax_name = f"{title} {first} {last}".strip()
                ticket_doc = pax.get("ticketDocument") or {}
                ticket_no = ticket_doc.get("ticketNumber") or pax.get("ticketNumber")

                if not ticket_no:
                    output.append(f"  [{idx}] {pax_name}: 未出票")
                    continue

                # 汇总状态
                has_refunded = ticket_doc.get("hasRefundedCoupon", False)
                has_exchanged = ticket_doc.get("hasExchangedCoupon", False)
                coupons = ticket_doc.get("coupons", [])

                if has_refunded:
                    pax_status = "已退票"
                elif has_exchanged:
                    pax_status = "已改期"
                elif coupons and all(c.get("segmentUsed") for c in coupons):
                    pax_status = "已使用"
                elif not all(c.get("segmentUsed", True) for c in coupons):
                    pax_status = "已开票/未使用"
                else:
                    pax_status = "已开票"

                output.append(f"  [{idx}] {pax_name} 票号: {ticket_no} → {pax_status}")

                # 每个 coupon 单独列出
                for c in coupons:
                    c_status = self._coupon_status_text(c)
                    c_flight = f"{c.get('airlineCode', 'VN')}{c.get('flightNumber', '')}"
                    c_route = f"{c.get('departureLocationCode', '')}→{c.get('arrivalLocationCode', '')}"
                    c_dt = str(c.get("departureDateTime", "")).replace("T", " ")[:16]
                    c_cabin = c.get("classOfService", "")
                    c_fare = c.get("fareBasisCode", "")
                    seg_used = "已用" if c.get("segmentUsed") else "未用"
                    c_refunded = " | 已退" if c.get("couponRefunded") else ""
                    output.append(f"      {c_flight} {c_route} {c_dt} {c_cabin} {seg_used} ({c_status}){c_refunded}")
                    if c_fare:
                        output.append(f"        票价基础: {c_fare}")

                # 票务其他信息
                if ticket_doc.get("endorsementText"):
                    output.append(f"      Endorsement: {ticket_doc['endorsementText']}")
                if ticket_doc.get("fareCalculation"):
                    output.append(f"      Fare Calc: {ticket_doc['fareCalculation']}")
                if ticket_doc.get("formOfPayment"):
                    output.append(f"      支付: {ticket_doc['formOfPayment']}")
                if ticket_doc.get("issueAt"):
                    output.append(f"      出票地: {ticket_doc['issueAt']}")

            return {
                "success": True,
                "data": "\n".join(output),
                "flight_info": data,
            }
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}

    @staticmethod
    def _coupon_status_text(coupon: dict) -> str:
        """把 couponStatusCode 转成中文标签"""
        code = (coupon.get("couponStatusCode") or "").upper()
        mapping = {
            "I": "已开票(Issued)",
            "O": "开放(Open/未用)",
            "C": "已使用(Closed/Flown)",
            "R": "已退(Refunded)",
            "E": "已换(Exchanged)",
            "V": "已作废(Voided)",
            "A": "已登机(Boarded)",
        }
        return mapping.get(code, code or "未知")
