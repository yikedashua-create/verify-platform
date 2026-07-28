"""LJ Jin Air 韩国真航空适配器(2026-07-28 第二版:换 Playwright)

查票方式: PNR + 姓 + 名 + 出发日期
- URL: https://www.jinair.com/booking/index
- Cloudflare 反爬,cloudscraper/curl_cffi 都过不了,改用 Playwright 真实浏览器
- 2026-07-28 第一版用 cloudscraper,被 Cloudflare 403,换 Playwright
"""
import re
import json
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

from .base import AirlineAdapter, FormField


class LJAdapter(AirlineAdapter):
    code = "lj"
    name = "LJ真航空"
    api_type = "custom"  # 用 Playwright 不属于 4 种标准类型,标 custom
    api_url = "https://www.jinair.com/booking/index"

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

        # 把 YYYY-MM-DD 转为页面需要的格式(截图里是 YYYY.MM.DD)
        depart_date_dotted = depart_date.replace("-", ".")

        result = {
            "pnr": pnr,
            "lastName": last_name,
            "firstName": first_name,
            "departDate": depart_date,
            "_html": "",
            "_method": "",
        }

        with sync_playwright() as p:
            # headless=True 部署到 Railway 必须,Dockerfile 已装 chromium
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

                # Step 1: GET booking/index(过 Cloudflare 验证 + 拿页面)
                page.goto(self.api_url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
                # 等 JS 加载完(Cloudflare 验证通常 3-5s)
                page.wait_for_load_state("networkidle", timeout=self.timeout * 1000)

                # Step 2: 找输入框 + 填表单
                # 截图里输入框顺序: PNR / 姓 / 名 / 出发日期
                # 用 nth(0..3) 按位置填,简单粗暴
                try:
                    inputs = page.locator('input').all()
                    input_count = len(inputs)
                    result["_input_count"] = input_count  # 排查用

                    if input_count < 4:
                        result["_error"] = f"输入框数量不足(只找到 {input_count} 个,需要 4 个)"
                        result["_html"] = page.content()[:3000]
                        return result

                    # 按截图顺序: PNR / 姓 / 名 / 日期
                    inputs[0].fill(pnr, timeout=5000)
                    inputs[1].fill(last_name, timeout=5000)
                    inputs[2].fill(first_name, timeout=5000)
                    # 日期输入框可能是 date 类型,直接 fill YYYY-MM-DD
                    inputs[3].fill(depart_date, timeout=5000)
                except Exception as e:
                    result["_error"] = f"填表失败: {type(e).__name__}: {e}"
                    result["_html"] = page.content()[:3000]
                    return result

                # Step 3: 点查询按钮
                try:
                    # 截图里按钮是"查询"
                    page.locator('button:has-text("查询"), button[type="submit"]').first.click(timeout=5000)
                    # 等结果加载
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception as e:
                    result["_error"] = f"点查询按钮失败: {type(e).__name__}: {e}"
                    result["_html"] = page.content()[:3000]
                    return result

                # Step 4: 等结果页面
                page.wait_for_timeout(2000)

                html = page.content()
                result["_html"] = html[:5000]  # 截 5000 字符,排查用
                result["_url"] = page.url

                # Step 5: 提取关键信息
                # 预订状态(中文"确定"=已确认)
                status_match = re.search(r"预订状态[\s\S]{0,30}?([\u4e00-\u9fa5]{1,6})", html)
                if status_match:
                    result["status"] = status_match.group(1).strip()

                # 航班号(LJ + 数字)
                flight_match = re.search(r"\b(LJ\s*\d{2,4})\b", html)
                if flight_match:
                    result["flightNo"] = flight_match.group(1).replace(" ", "")

                # 乘客姓名
                pax_match = re.search(r"姓名[\s\S]{0,30}?([A-Z]+/[A-Z]+)", html)
                if pax_match:
                    result["passenger"] = pax_match.group(1)

                # 行程
                route_match = re.search(r"([A-Z]{3,4})\s+([\u4e00-\u9fa5]+)\s*([→\->]+)\s*([A-Z]{3,4})", html)
                if route_match:
                    result["from"] = route_match.group(1)
                    result["fromCity"] = route_match.group(2)
                    result["to"] = route_match.group(4)

                # 出发时间(HH:MM)
                time_match = re.search(r"(\d{2}:\d{2})\s*[\u4e00-\u9fa5]+\s*(\d{2}:\d{2})", html)
                if time_match:
                    result["departTime"] = time_match.group(1)
                    result["arriveTime"] = time_match.group(2)

                return result
            except PlaywrightTimeout as e:
                result["_error"] = f"Playwright 超时: {type(e).__name__}: {e}"
                try:
                    result["_html"] = page.content()[:2000]
                except Exception:
                    pass
                return result
            except Exception as e:
                result["_error"] = f"Playwright 错误: {type(e).__name__}: {e}"
                try:
                    result["_html"] = page.content()[:2000]
                except Exception:
                    pass
                return result
            finally:
                browser.close()

    def _parse(self, raw) -> dict:
        if isinstance(raw, dict) and raw.get("_error"):
            return {"success": False, "error": raw["_error"]}

        if not isinstance(raw, dict):
            return {"success": False, "error": f"未获取到有效数据: {raw}"}

        try:
            output = []
            output.append("=" * 50)
            output.append("查询成功 (LJ Jin Air)")
            output.append("=" * 50)
            output.append("")

            output.append("【订单信息】")
            output.append(f"预订号码: {raw.get('pnr', 'N/A')}")
            output.append(f"出发日期: {raw.get('departDate', 'N/A')}")
            output.append(f"预订状态: {raw.get('status', 'N/A')}")

            if raw.get("passenger"):
                output.append("")
                output.append("【乘客信息】")
                output.append(f"姓名: {raw.get('passenger')}")

            if raw.get("flightNo"):
                output.append("")
                output.append("【行程信息】")
                if raw.get("from") and raw.get("to"):
                    output.append(f"航线: {raw.get('from')} → {raw.get('to')}")
                output.append(f"航班号: {raw.get('flightNo')}")
                if raw.get("departTime") and raw.get("arriveTime"):
                    output.append(f"时间: {raw.get('departTime')} → {raw.get('arriveTime')}")

            # 原始 HTML(失败排查用)
            output.append("")
            output.append("【URL】")
            output.append(raw.get("_url", "N/A"))

            return {
                "success": True,
                "data": "\n".join(output),
                "flight_info": raw,
            }
        except Exception as e:
            import traceback
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
            }
