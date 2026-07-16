"""HX 香港航司适配器（内网 172.18.247.238:32000）"""
import requests
from .base import AirlineAdapter, FormField


class HXAdapter(AirlineAdapter):
    code = "hx"
    name = "HX香港航司"
    api_type = "json_post"
    api_url = "http://172.18.247.238:32000/hx_gw_verify"

    form_fields = [
        FormField("ticketNo", label="票号", placeholder="如：851-2118256984"),
        FormField("passName", label="姓名", placeholder="如：ZHANG/SAN"),
    ]

    def _call_api(self, form_data: dict):
        payload = {
            "ticketNo": form_data.get("ticketNo", "").strip(),
            "passName": form_data.get("passName", "").strip().upper(),
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        resp = requests.post(self.api_url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _parse(self, raw) -> dict:
        try:
            if not raw:
                return {"success": False, "error": "未获取到有效数据"}

            output = ["=" * 50, "查询成功", "=" * 50]
            return_code = raw.get("return_code", "N/A")
            return_msg = raw.get("return_msg", "")
            output.append("")
            output.append(f"返回状态: {return_code}")
            if return_msg:
                output.append(f"消息: {return_msg}")

            data = raw.get("data", {})
            if not data:
                return {"success": False, "error": "未找到票务信息"}

            output.append("")
            output.append("【票号信息】")
            output.append(f"票号: {data.get('ticketNo', 'N/A')}")
            output.append(f"姓名: {data.get('name', 'N/A')}")
            output.append(f"出生日期: {data.get('birthDay', 'N/A')}")
            output.append(f"乘客类型: {data.get('peopleType', 'N/A')}")

            output.append("")
            output.append("【航班信息】")
            output.append(f"航班号: {data.get('flightNo', 'N/A')}")
            output.append(f"出发地: {data.get('flightFrom', 'N/A')}")
            output.append(f"目的地: {data.get('fromTo', 'N/A')}")
            output.append(f"出发时间: {data.get('startTime', 'N/A')}")
            output.append(f"到达时间: {data.get('endTime', 'N/A')}")

            output.append("")
            output.append("【状态信息】")
            output.append(f"机票状态: {data.get('ticketStatus', 'N/A')}")
            output.append(f"值机状态: {data.get('status', 'N/A')}")
            output.append(f"行程类型: {data.get('DirectionInd', 'N/A')}")
            output.append(f"行李件数: {data.get('baggagePieces', 'N/A')}")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
