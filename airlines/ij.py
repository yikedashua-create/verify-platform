"""IJ 春秋航司适配器

API: form-urlencoded POST 到 jp.ch.com/Service/GetAncillaryData
姓名格式: 姓/名 (如 PHAN/THITHUHUONG)
"""
import json
import requests
from datetime import datetime
from .base import AirlineAdapter, FormField


def _parse_date(date_str):
    if not date_str:
        return None
    s = date_str.strip()
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


class IJAdapter(AirlineAdapter):
    code = "ij"
    name = "IJ春秋航司"
    api_type = "form_post"
    api_url = "https://jp.ch.com/Service/GetAncillaryData"
    form_fields = [
        FormField("fullName", label="姓名", placeholder="如：ZHANG/SAN"),
        FormField("FlightNo", label="航班号", placeholder="如：IJ123"),
        FormField("FlightStartDate", label="航班日期", placeholder="YYYY-MM-DD", field_type="date"),
        FormField("Gender", label="性别", placeholder="1=男 2=女", default="1"),
        FormField("Birthday", label="出生日期", placeholder="YYYY-MM-DD", field_type="date"),
        FormField("Email", label="邮箱", placeholder="如：test@163.com"),
    ]

    def _call_api(self, form_data: dict):
        # 拆姓名: 姓/名
        full_name = form_data.get("fullName", "").strip().upper()
        if "/" in full_name:
            parts = full_name.split("/", 1)
            name = parts[0].strip()
            second_name = parts[1].strip() if len(parts) > 1 else ""
        else:
            name = full_name
            second_name = ""

        payload = {
            "FlightStartDate": _parse_date(form_data.get("FlightStartDate", "")),
            "FlightNo": form_data.get("FlightNo", "").upper(),
            "Name": name,
            "SecondName": second_name,
            "Gender": form_data.get("Gender", "1"),
            "Lang": "ja",
            "Birthday": _parse_date(form_data.get("Birthday", "")),
            "IsInternational": "false",
            "Email": form_data.get("Email", ""),
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Origin": "https://jp.ch.com",
            "Referer": "https://jp.ch.com/Service/ancillary",
        }

        resp = requests.post(self.api_url, data=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()

        text = resp.text
        # IJ 接口会返回 HTML + <script> 段,只取前面的 JSON
        json_end = text.find("<script")
        if json_end != -1:
            text = text[:json_end].strip()
        return json.loads(text)

    def _parse(self, raw) -> dict:
        if raw.get("Code") != "0":
            return {"success": False, "error": raw.get("ErrorMessage", raw.get("Message", "查询失败"))}

        data_list = raw.get("Data", [])
        if not data_list:
            return {"success": False, "error": "未查询到数据"}

        f = data_list[0]
        output = []
        output.append("=" * 40)
        output.append("查询成功")
        output.append("=" * 40)
        output.append("")
        output.append("【航班信息】")
        output.append(f"航班号: {f.get('FlightNo', 'N/A')}")
        output.append(f"航班日期: {f.get('FlightDate', 'N/A')}")
        output.append(f"出发地: {f.get('OriCity', f.get('OriAirport', 'N/A'))}")
        output.append(f"目的地: {f.get('DesCity', f.get('DesAirport', 'N/A'))}")
        output.append(f"舱位: {f.get('SeatsName', 'N/A')}")
        output.append("")

        unPaid = f.get("UnPaidProducts", [])
        paid = f.get("PaidProducts", [])
        if unPaid or paid:
            output.append("【附加服务产品】")
            for item in paid:
                output.append(f"  [已购买] {item.get('Name', 'N/A')} - {item.get('Price', 'N/A')}")
            for item in unPaid:
                output.append(f"  [未购买] {item.get('Name', 'N/A')} - {item.get('Price', 'N/A')}")
        else:
            output.append("【附加服务产品】")
            output.append("  暂无附加服务产品")

        return {"success": True, "data": "\n".join(output), "flight_info": f}
