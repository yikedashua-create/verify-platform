"""AQ 九元航司适配器（内网 172.18.247.238:32000）"""
import requests
from .base import AirlineAdapter, FormField


class AQAdapter(AirlineAdapter):
    code = "aq"
    name = "AQ九元航司"
    api_type = "json_post"
    api_url = "http://172.18.247.238:32000/aq_wx_verify"

    form_fields = [
        FormField("name", label="姓名", placeholder="如：ZHANG/SAN"),
        FormField("cardNo", label="证件号", placeholder="如：身份证号"),
        FormField("ticketNumber", label="票号", placeholder="如：902XXXXXXXXX"),
    ]

    def _call_api(self, form_data: dict):
        payload = {
            "name": form_data.get("name", "").strip().upper(),
            "cardNo": form_data.get("cardNo", "").strip(),
            "ticketNumber": form_data.get("ticketNumber", "").strip(),
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

            if return_code != 0 and return_code != "0":
                return {"success": False, "error": return_msg or "查询未成功"}

            data = raw.get("data", {})
            if not data:
                return {"success": False, "error": "未找到订单信息"}

            flight_info = data.get("flightInfo", {})
            if flight_info:
                output.append("")
                output.append("【航班信息】")
                output.append(f"航班号: {flight_info.get('fltId', 'N/A')}")
                output.append(f"航班号2: {flight_info.get('flightNum', 'N/A')}")
                output.append(f"出发地: {flight_info.get('deptApt', 'N/A')} ({flight_info.get('fltOrgCity', 'N/A')})")
                output.append(f"目的地: {flight_info.get('destApt', 'N/A')} ({flight_info.get('fltDstCity', 'N/A')})")
                output.append(f"出发机场: {flight_info.get('orgAptName', 'N/A')}")
                output.append(f"到达机场: {flight_info.get('destAptName', 'N/A')}")
                output.append(f"航班日期: {flight_info.get('flightDate', 'N/A')}")
                output.append(f"计划出发时间: {flight_info.get('planDeptDate', 'N/A')}")
                output.append(f"计划到达时间: {flight_info.get('planArrDate', 'N/A')}")

            output.append("")
            output.append("【订单信息】")
            output.append(f"订单号: {data.get('orderNo', 'N/A')}")
            output.append(f"票号: {data.get('ticketNo', 'N/A')}")

            output.append("")
            output.append("【乘客信息】")
            output.append(f"姓名: {data.get('fullName', 'N/A')}")
            psg_ticket_info = data.get("psgTicketInfo", {})
            if psg_ticket_info:
                output.append(f"乘客类型: {psg_ticket_info.get('psgType', 'N/A')}")
                output.append(f"证件类型: {psg_ticket_info.get('idType', 'N/A')}")
                output.append(f"证件号: {psg_ticket_info.get('idNo', 'N/A')}")
                output.append(f"产品名称: {psg_ticket_info.get('productName', 'N/A')}")
                output.append(f"票价: {psg_ticket_info.get('ticketFare', 'N/A')}")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
