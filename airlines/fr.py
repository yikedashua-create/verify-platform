"""FR 瑞安航司适配器（内网 172.18.247.238:32000）"""
import requests
from .base import AirlineAdapter, FormField


class FRAdapter(AirlineAdapter):
    code = "fr"
    name = "FR瑞安航司"
    api_type = "json_post"
    api_url = "http://172.18.247.238:32000/fr_gw_verify"

    form_fields = [
        FormField("ticketNo", label="票号", placeholder="如：XXX123"),
        FormField("email", label="邮箱", placeholder="如：test@163.com"),
    ]

    def _call_api(self, form_data: dict):
        payload = {
            "ticketNo": form_data.get("ticketNo", "").strip(),
            "email": form_data.get("email", "").strip(),
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
            booking = data.get("getBookingByReservationNumber", {}) if data else {}
            if not booking:
                return {"success": False, "error": "未找到订单信息"}

            output.append("")
            output.append("【订单信息】")
            info = booking.get("info", {})
            output.append(f"订单号(PNR): {info.get('pnr', 'N/A')}")
            output.append(f"状态: {info.get('status', 'N/A')}")
            output.append(f"币种: {info.get('curr', 'N/A')}")
            output.append(f"订单金额: {info.get('balanceDue', 0)}")
            output.append(f"订单创建时间: {info.get('createdUtcDate', 'N/A')}")

            passengers = booking.get("passengers", [])
            if passengers:
                output.append("")
                output.append("【乘客人信息】")
                for pax in passengers:
                    name = pax.get("name", {})
                    first_name = name.get("first", "N/A")
                    last_name = name.get("last", "N/A")
                    title = name.get("title", "")
                    pax_type = pax.get("type", "N/A")
                    dob = pax.get("dateOfBirth") or pax.get("doB", "N/A")
                    output.append(f"{title} {first_name} {last_name}")
                    output.append(f"  类型: {pax_type}")
                    if dob and dob != "N/A":
                        output.append(f"  出生日期: {dob}")

            journeys = booking.get("journeys", [])
            if journeys:
                output.append("")
                output.append("【航班信息】")
                for journey in journeys:
                    output.append(f"航班: {journey.get('flt', 'N/A')}")
                    output.append(f"  出发: {journey.get('orig', 'N/A')} → 到达: {journey.get('dest', 'N/A')}")
                    output.append(f"  出发时间: {journey.get('depart', 'N/A')}")
                    output.append(f"  到达时间: {journey.get('arrive', 'N/A')}")
                    output.append(f"  飞行时长: {journey.get('duration', 'N/A')}")
                    output.append(f"  舱位: {journey.get('fareClass', 'N/A')}")
                    for seg in journey.get("segments", []):
                        output.append(f"  [航段] {seg.get('flt', 'N/A')}: {seg.get('orig', 'N/A')} → {seg.get('dest', 'N/A')}")
                        output.append(f"       起飞: {seg.get('depart', 'N/A')} / 到达: {seg.get('arrive', 'N/A')}")
                        output.append(f"       机型: {seg.get('aircraft', 'N/A')}")

            contacts = booking.get("contacts", [])
            if contacts:
                output.append("")
                output.append("【联系信息】")
                for contact in contacts:
                    name = contact.get("name", {})
                    output.append(f"姓名: {name.get('title', '')} {name.get('first', '')} {name.get('last', '')}")
                    output.append(f"邮箱: {contact.get('email', 'N/A')}")

            payments = booking.get("payments", [])
            if payments:
                output.append("")
                output.append("【付款信息】")
                for payment in payments:
                    output.append(f"金额: {payment.get('amt', 0)} {payment.get('currency', 'N/A')}")
                    output.append(f"方式: {payment.get('code', 'N/A')}")
                    output.append(f"状态: {payment.get('status', 'N/A')}")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
