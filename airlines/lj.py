"""LJ Jin Air 韩国真航空适配器(2026-07-28 新增)

查票方式: PNR + 姓 + 名 + 出发日期
- URL: https://www.jinair.com/booking/index
- 走 cloudscraper 绕过 Cloudflare 反爬
- 表单 POST 提交,返回 HTML,正则提取
"""
import re
import cloudscraper
import urllib3

from .base import AirlineAdapter, FormField

# 关掉 verify=False 的 warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class LJAdapter(AirlineAdapter):
    code = "lj"
    name = "LJ真航空"
    api_type = "simple_post"  # 公网 POST(用 cloudscraper 绕 Cloudflare)
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

        # cloudscraper 自带 Cloudflare 绕过能力
        scraper = cloudscraper.create_scraper(
            browser={
                "browser": "chrome",
                "platform": "windows",
                "desktop": True,
            }
        )

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://www.jinair.com/booking/index",
            "Origin": "https://www.jinair.com",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Step 1: GET booking/index 拿 cookie + cf_clearance
        try:
            init_resp = scraper.get(
                "https://www.jinair.com/booking/index",
                headers=headers,
                timeout=self.timeout,
            )
            init_resp.raise_for_status()
        except Exception as e:
            return {"_error": f"GET booking/index 失败: {type(e).__name__}: {e}"}

        # Step 2: POST 表单提交查询
        # 注: 字段名要根据实际页面表单调整,这里先按猜测
        payload = {
            "pnr": pnr,
            "lastName": last_name,
            "firstName": first_name,
            "departDate": depart_date,
        }

        try:
            search_resp = scraper.post(
                self.api_url,
                data=payload,
                headers=headers,
                timeout=self.timeout,
                allow_redirects=True,
            )
            search_resp.raise_for_status()
        except Exception as e:
            return {"_error": f"POST 查票失败: {type(e).__name__}: {e}"}

        text = search_resp.text

        # Step 3: 正则提取关键信息(从截图看,Jin Air 查票结果页含预订状态、航班号、乘客等)
        result = {
            "_html": text,  # 保留原始 HTML,失败时排查用
            "pnr": pnr,
            "lastName": last_name,
            "firstName": first_name,
            "departDate": depart_date,
        }

        # 提取预订状态(中文"确定"=已确认 / "已出票" / "未出票" 等)
        # 截图里: 预订状态 = "确定"
        status_match = re.search(r"预订状态[\s\S]{0,30}?([\u4e00-\u9fa5A-Z]+)", text)
        if status_match:
            result["status"] = status_match.group(1).strip()

        # 提取航班号(LJ + 数字)
        flight_match = re.search(r"\b(LJ\s*\d{2,4})\b", text)
        if flight_match:
            result["flightNo"] = flight_match.group(1).replace(" ", "")

        # 提取乘客信息(姓/名)
        pax_match = re.search(r"姓名[\s\S]{0,30}?([A-Z]+/[A-Z]+)", text)
        if pax_match:
            result["passenger"] = pax_match.group(1)

        # 提取行程(出发机场 → 到达机场)
        route_match = re.search(r"([A-Z]{3,4})\s*[\u4e00-\u9fa5]+\s*[→\->]+\s*([A-Z]{3,4})", text)
        if route_match:
            result["from"] = route_match.group(1)
            result["to"] = route_match.group(2)

        return result

    def _parse(self, raw) -> dict:
        # raw 可能是 dict(成功) 或 {"_error": "..."}(失败)
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

            if raw.get("from") and raw.get("to"):
                output.append("")
                output.append("【行程信息】")
                output.append(f"航线: {raw.get('from')} → {raw.get('to')}")
                if raw.get("flightNo"):
                    output.append(f"航班号: {raw.get('flightNo')}")

            output.append("")
            output.append("【原始 HTML 片段(排查用)】")
            html = raw.get("_html", "")
            if html:
                # 输出关键片段
                output.append(html[:500] + ("..." if len(html) > 500 else ""))

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
