"""DD 泰国皇雀航司适配器 (内网 172.18.247.238:32000)

成功判断: return_code == "SUCCEED"
嵌套结构: data.flights[].legs[].passengers[]
"""
import requests
from .base import AirlineAdapter, FormField


class DDAdapter(AirlineAdapter):
    code = "dd"
    name = "DD皇雀航空"
    api_type = "json_post"
    api_url = "http://172.18.247.238:32000/dd_gw_verify"

    form_fields = [
        FormField("ticketNo", label="票号", placeholder="如：B3BJ8Y"),
        FormField("passName", label="姓", placeholder="如：KHANANTHAI"),
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

            if return_code != "SUCCEED":
                return {"success": False, "error": return_msg or "查询失败"}

            data = raw.get("data", {})
            if not data:
                return {"success": False, "error": "未找到订单信息"}

            # 订单信息 (顶层)
            output.append("")
            output.append("【订单信息】")
            output.append(f"订单号(PNR): {data.get('confirmationNumber', 'N/A')}")
            output.append(f"姓: {data.get('bookingLastName', 'N/A')}")
            output.append(f"币种: {data.get('currency', 'N/A')}")
            if data.get("webBookingId"):
                output.append(f"系统订单ID: {data['webBookingId']}")

            flights = data.get("flights", [])

            # 乘客人信息 (嵌套 + 去重,每个 leg 都列一份同乘客)
            output.append("")
            output.append("【乘客人信息】")
            seen_pax = set()
            pax_count = 0
            for flight in flights:
                for leg in flight.get("legs", []):
                    for pax in leg.get("passengers", []):
                        pax_key = f"{pax.get('title', '')}|{pax.get('firstName', '')}|{pax.get('lastName', '')}"
                        if pax_key in seen_pax:
                            continue
                        seen_pax.add(pax_key)
                        pax_count += 1

                        title = pax.get("title", "")
                        first_name = pax.get("firstName", "N/A")
                        last_name = pax.get("lastName", "N/A")
                        output.append(f"{title} {first_name} {last_name}")
                        if pax.get("email"):
                            output.append(f"  邮箱: {pax['email']}")
                        if pax.get("contactNumber"):
                            output.append(f"  电话: {pax['contactNumber']}")
                        if pax.get("dateOfBirth"):
                            output.append(f"  出生日期: {str(pax['dateOfBirth'])[:10]}")
                        if pax.get("country"):
                            output.append(f"  国籍: {pax['country']}")
                        output.append(f"  乘客类型: {pax.get('passengerTypeCode', 'N/A')}")
                        if pax.get("frequentFlyerNumber"):
                            output.append(f"  会员卡号: {pax['frequentFlyerNumber']}")
                        if pax.get("fareCode"):
                            output.append(f"  票价代码: {pax['fareCode']}")

            if pax_count == 0:
                output.append("  (无乘客信息)")

            # 航班信息
            output.append("")
            output.append("【航班信息】")
            for flight in flights:
                carrier = flight.get("carrierCode", "DD")
                for leg in flight.get("legs", []):
                    flight_number = leg.get("flightNumber", "N/A")
                    leg_from = leg.get("from", {})
                    leg_to = leg.get("to", {})
                    from_code = leg_from.get("code", "N/A")
                    to_code = leg_to.get("code", "N/A")
                    from_name = leg_from.get("name", "")
                    to_name = leg_to.get("name", "")
                    dep_time = str(leg.get("departureDate", "")).replace("T", " ")[:16]
                    arr_time = str(leg.get("arrivalDate", "")).replace("T", " ")[:16]

                    # cabin 在 passengers[0] 里
                    cabin = "ECONOMY"
                    if leg.get("passengers"):
                        cabin = leg["passengers"][0].get("cabin", "ECONOMY")

                    output.append(f"航班: {carrier}{flight_number} {from_code} → {to_code}")
                    if from_name:
                        output.append(f"  出发机场: {from_name}")
                    if to_name:
                        output.append(f"  到达机场: {to_name}")
                    output.append(f"  出发: {dep_time}")
                    output.append(f"  到达: {arr_time}")
                    output.append(f"  飞行时长: {leg.get('flightTime', 'N/A')}分钟")
                    output.append(f"  舱位: {cabin}")
                    output.append(f"  国际: {'是' if flight.get('isInternational') else '否'}")
                    if flight.get("checkinOpensOn"):
                        output.append(f"  值机开放: {str(flight['checkinOpensOn'])[:19].replace('T', ' ')}")
                    if flight.get("checkinClosesOn"):
                        output.append(f"  值机截止: {str(flight['checkinClosesOn'])[:19].replace('T', ' ')}")
                    if flight.get("fareBasisCode"):
                        output.append(f"  票价基础: {flight['fareBasisCode']}")
                    output.append(f"  状态: {'已取消' if flight.get('cancelled') else '正常'}")

            # 费用明细 (从 pax.charges 提,去重)
            output.append("")
            output.append("【费用明细】")
            total = 0
            seen_charges = set()
            for flight in flights:
                for leg in flight.get("legs", []):
                    for pax in leg.get("passengers", []):
                        for ch in pax.get("charges", []):
                            ch_key = f"{ch.get('code', '')}|{ch.get('amount', 0)}|{ch.get('description', '')}"
                            if ch_key in seen_charges:
                                continue
                            seen_charges.add(ch_key)
                            code = ch.get("code", "N/A")
                            desc = ch.get("description", "N/A")
                            amt = ch.get("amount", 0)
                            currency = data.get("currency", "THB")
                            total += amt
                            output.append(f"  [{code}] {desc}: {amt} {currency}")
            if total > 0:
                output.append(f"  ---")
                output.append(f"  合计: {total} {data.get('currency', 'THB')}")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
