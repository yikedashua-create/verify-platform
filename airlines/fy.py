"""FY 飞萤航司适配器（内网 172.18.247.238:32000）"""
import requests
from .base import AirlineAdapter, FormField


class FYAdapter(AirlineAdapter):
    code = "fy"
    name = "FY飞萤航司"
    api_type = "json_post"
    api_url = "http://172.18.247.238:32000/fy_app_verify"

    form_fields = [
        FormField("ticketNo", label="票号", placeholder="如：XXX123"),
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
                return {"success": False, "error": "未找到订单信息"}

            status = data.get("Status", "N/A")
            output.append("")
            output.append(f"状态: {status}")

            booking_list = data.get("BookingDataList", [])
            if not booking_list:
                return {"success": False, "error": "未找到预订信息"}

            for idx, booking in enumerate(booking_list):
                output.append("")
                output.append(f"【预订信息 {idx + 1}】")
                output.append(f"订单号: {booking.get('RecordLocator', 'N/A')}")
                output.append(f"出发地: {booking.get('DepartureStation', 'N/A')} - {booking.get('DepartureStationName', 'N/A')}")
                output.append(f"目的地: {booking.get('ArrivalStation', 'N/A')} - {booking.get('ArrivalStationName', 'N/A')}")
                output.append(f"出发日期: {booking.get('DepartureDate', 'N/A')}")
                output.append(f"状态: {booking.get('Status', 'N/A')}")
                output.append(f"邮箱: {booking.get('Email', 'N/A')}")
                expired = booking.get("ExpiredDate", "")
                if expired:
                    output.append(f"过期日期: {expired}")
                estimated = booking.get("EstimatedLastDate", "")
                if estimated:
                    output.append(f"最晚时间: {estimated}")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
