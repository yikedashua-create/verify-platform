"""5J 宿务航司适配器（内网 172.18.247.238:32000）"""
import requests
from .base import AirlineAdapter, FormField


class FiveJAdapter(AirlineAdapter):
    code = "5j"
    name = "5J宿务航司"
    api_type = "json_post"
    api_url = "http://172.18.247.238:32000/5j_gw_verify"

    form_fields = [
        FormField("ticketNo", label="票号", placeholder="如：NJS8MJ"),
        FormField("passName", label="姓", placeholder="如：CHEN"),
    ]

    def _call_api(self, form_data: dict):
        payload = {
            "ticketNo": form_data.get("ticketNo", "").strip(),
            "passName": form_data.get("passName", "").strip(),
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

            if return_code != "SUCCEED":
                return {"success": False, "error": return_msg or "查询失败"}

            data = raw.get("data", {})
            if not data:
                return {"success": False, "error": "未找到订单信息"}

            output.append("")
            output.append("【订单信息】")
            output.append(f"订单号(PNR): {data.get('recordLocator', 'N/A')}")
            output.append(f"币种: {data.get('currencyCode', 'N/A')}")
            output.append(f"状态: {data.get('info', {}).get('status', 'N/A')}")

            passengers = data.get("passengers", [])
            if passengers:
                output.append("")
                output.append("【乘客信息】")
                for pax in passengers:
                    name = pax.get("name", {})
                    output.append(f"{name.get('title', '')} {name.get('first', 'N/A')} {name.get('last', 'N/A')}")
                    output.append(f"  类型: {pax.get('passengerTypeCode', 'N/A')}")
                    output.append(f"  性别: {pax.get('info', {}).get('gender', 'N/A')}")

            booking_summary = data.get("bookingSummary", {})
            journeys = booking_summary.get("journeys", [])
            if journeys:
                output.append("")
                output.append("【航班信息】")
                for journey in journeys:
                    for seg in journey.get("segments", []):
                        identifier = seg.get("identifier", {})
                        carrier = identifier.get("carrierCode", "N/A")
                        flight_no = identifier.get("identifier", "N/A")
                        seg_designator = seg.get("designator", {})
                        output.append(f"航班号: {carrier}{flight_no}")
                        output.append(f"出发地: {seg_designator.get('origin', 'N/A')} → 目的地: {seg_designator.get('destination', 'N/A')}")
                        dep = seg_designator.get("departure", "N/A")
                        arr = seg_designator.get("arrival", "N/A")
                        if "T" in str(dep):
                            dep = dep.split("T")[0] + " " + dep.split("T")[1][:8]
                        if "T" in str(arr):
                            arr = arr.split("T")[0] + " " + arr.split("T")[1][:8]
                        output.append(f"出发时间: {dep}")
                        output.append(f"到达时间: {arr}")
                        output.append(f"舱位: {seg.get('fareClass', 'N/A')}")
                        output.append(f"状态: {seg.get('status', 'N/A')}")

            return {"success": True, "data": "\n".join(output), "flight_info": data}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
