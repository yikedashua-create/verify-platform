"""VJ 越捷航司适配器（内网 172.18.247.238:32000）"""
import requests
from .base import AirlineAdapter, FormField


class VJAdapter(AirlineAdapter):
    code = "vj"
    name = "VJ越捷航司"
    api_type = "json_post"
    api_url = "http://172.18.247.238:32000/vj_app_verify"

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

            output.append("")
            output.append("【订单信息】")
            booking_info = data.get("bookingInformation", {})
            if booking_info:
                currency = booking_info.get("currency", {})
                output.append(f"订单号: {data.get('number', 'N/A')}")
                output.append(f"本地定位: {data.get('locator', 'N/A')}")
                output.append(f"币种: {currency.get('code', 'N/A') if currency else 'N/A'}")
                creation = booking_info.get("creation", {})
                if creation:
                    output.append(f"创建时间: {creation.get('time', 'N/A')}")
                agency = booking_info.get("agency", {})
                if agency:
                    output.append(f"代理商: {agency.get('name', 'N/A')}")
                contact = booking_info.get("contactInformation", {})
                if contact:
                    output.append(f"联系人: {contact.get('name', 'N/A')}")
                    output.append(f"邮箱: {contact.get('email', 'N/A')}")
                    output.append(f"电话: {contact.get('phoneNumber', 'N/A')}")

            passengers = data.get("passengers", [])
            if passengers:
                output.append("")
                output.append("【乘客人信息】")
                for pax in passengers:
                    profile = pax.get("reservationProfile", {})
                    if profile:
                        last_name = profile.get("lastName", "N/A")
                        first_name = profile.get("firstName", "N/A")
                        title = profile.get("title", "")
                        gender = profile.get("gender", "N/A")
                        birth_date = profile.get("birthDate", "N/A")
                        output.append(f"{title} {first_name} {last_name}")
                        output.append(f"  性别: {gender}")
                        output.append(f"  出生日期: {birth_date}")
                        personal_contact = profile.get("personalContactInformation", {})
                        if personal_contact:
                            output.append(f"  邮箱: {personal_contact.get('email', 'N/A')}")
                            output.append(f"  电话: {personal_contact.get('phoneNumber', 'N/A')}")
                    pax_type_code = pax.get("passengerTypeCode", {})
                    output.append(f"  乘客类型: {pax_type_code.get('code', 'N/A') if pax_type_code else 'N/A'}")
                    res_status = pax.get("reservationStatus", {})
                    confirmed = res_status.get("confirmed", False)
                    cancelled = res_status.get("cancelled", False)
                    status_str = "已确认" if confirmed else ("已取消" if cancelled else "未知")
                    output.append(f"  状态: {status_str}")

            journeys = data.get("journeys", [])
            if journeys:
                output.append("")
                output.append("【航班信息】")
                for journey in journeys:
                    departure = journey.get("departure", {})
                    airport = departure.get("airport", {})
                    output.append(f"航班: {journey.get('flt', 'N/A')}")
                    output.append(f"  出发: {airport.get('name', 'N/A')} ({airport.get('code', 'N/A')}) - {departure.get('localScheduledTime', 'N/A')}")
                    for seg in journey.get("segments", []):
                        flight = seg.get("flight", {})
                        flight_no = flight.get("flightNumber", "N/A")
                        dep_seg = seg.get("departure", {})
                        arr_seg = seg.get("arrival", {})
                        dep_airport = dep_seg.get("airport", {})
                        arr_airport = arr_seg.get("airport", {})
                        model = flight.get("aircraftModel", {})
                        aircraft = model.get("identifier", "N/A") if model else "N/A"
                        output.append(f"  [航段] {flight_no}: {dep_airport.get('code', 'N/A')} → {arr_airport.get('code', 'N/A')}")
                        output.append(f"       起飞: {dep_seg.get('localScheduledTime', 'N/A')}")
                        output.append(f"       到达: {arr_seg.get('localScheduledTime', 'N/A')}")
                        output.append(f"       机型: {aircraft}")
                        res_status = seg.get("reservationStatus", {})
                        cancelled = res_status.get("cancelled", False)
                        open_stat = res_status.get("open", False)
                        status_str = "已取消" if cancelled else ("开放" if open_stat else "正常")
                        output.append(f"       状态: {status_str}")

            charges = data.get("charges", [])
            if charges:
                output.append("")
                output.append("【费用明细】")
                total = 0
                for charge in charges:
                    desc = charge.get("description", "N/A")
                    for ca in charge.get("currencyAmounts", []):
                        amt = ca.get("totalAmount", 0)
                        curr = ca.get("currency", {})
                        curr_code = curr.get("code", "N/A") if curr else "N/A"
                        total += amt
                        output.append(f"  {desc}: {amt:,.0f} {curr_code}")
                output.append(f"  ---")
                output.append(f"  合计: {total:,.0f} VND")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
