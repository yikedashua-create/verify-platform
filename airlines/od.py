"""OD 峇迪航空适配器 (内网 172.18.247.238:32000)

成功判断: return_code == "SUCCEED"
嵌套结构: data.confirmationRes.{pnr, passengerInfos, fares[].flight[].flightSeg}
"""
import requests
from .base import AirlineAdapter, FormField


class ODAdapter(AirlineAdapter):
    code = "od"
    name = "OD峇迪航空"
    api_type = "json_post"
    api_url = "http://172.18.247.238:32000/od_gw_verify"

    form_fields = [
        FormField("ticketNo", label="票号", placeholder="如：GZOMVG"),
        FormField("passName", label="姓名", placeholder="如：HONG/KAILAN"),
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

            conf = data.get("confirmationRes", {})
            if not conf:
                return {"success": False, "error": "未找到订单确认信息"}

            # 订单信息
            output.append("")
            output.append("【订单信息】")
            output.append(f"订单号(PNR): {conf.get('pnr', 'N/A')}")
            if conf.get("bookingReference"):
                output.append(f"预订参考: {conf['bookingReference']}")
            if data.get("ticketIssueDt"):
                output.append(f"出票时间: {str(data['ticketIssueDt'])[:19].replace('T', ' ')}")
            if data.get("pos"):
                pos = data["pos"]
                if pos.get("pseudoCityCode"):
                    output.append(f"销售点: {pos['pseudoCityCode']}")
                if pos.get("pnrCreationTimestamp"):
                    output.append(f"PNR 创建时间: {str(pos['pnrCreationTimestamp'])[:19].replace('T', ' ')}")
                if pos.get("agentSine"):
                    output.append(f"代理: {pos['agentSine']}")

            # 乘客人信息 (在 confirmationRes.passengerInfos[])
            output.append("")
            output.append("【乘客人信息】")
            for pax in conf.get("passengerInfos", []):
                title = pax.get("title", "")
                given = pax.get("givenName", "N/A")
                surname = pax.get("surname", "N/A")
                output.append(f"{title} {given} {surname}")
                if pax.get("ticketNumber"):
                    output.append(f"  票号: {pax['ticketNumber']}")
                output.append(f"  乘客类型: {pax.get('paxType', 'N/A')}")
                if pax.get("paxRefNo"):
                    output.append(f"  乘客引用: {pax['paxRefNo']}")
                if pax.get("gender") is not None:
                    gender = "男" if pax["gender"] == 0 else "女"
                    output.append(f"  性别: {gender}")
                if pax.get("nationality"):
                    output.append(f"  国籍: {pax['nationality']}")
                if pax.get("birthDate"):
                    output.append(f"  出生日期: {str(pax['birthDate'])[:10]}")

            # 联系信息
            contact = conf.get("contactInfo", {})
            if contact:
                output.append("")
                output.append("【联系信息】")
                if contact.get("email"):
                    output.append(f"邮箱: {contact['email']}")
                phone = contact.get("phone", {})
                if phone and phone.get("number"):
                    cc = phone.get("countryCode", "")
                    num = phone["number"]
                    output.append(f"电话: +{cc}{num}")

            # 航班信息 (fares[].flight[].flightSeg)
            output.append("")
            output.append("【航班信息】")
            for fare in conf.get("fares", []):
                dep_port_fare = fare.get("depPort", "N/A")
                arr_port_fare = fare.get("arrPort", "N/A")
                if fare.get("brandLabel"):
                    output.append(f"品牌类型: {fare['brandLabel']}")

                for flight in fare.get("flight", []):
                    seg = flight.get("flightSeg", {})
                    if not seg:
                        continue
                    carrier = seg.get("carrier", {})
                    air_code = carrier.get("airCode", "OD")
                    flight_no = seg.get("flightNo", "N/A")
                    dep_port = seg.get("depPort", dep_port_fare)
                    arr_port = seg.get("arrPort", arr_port_fare)
                    dep_date = str(seg.get("depDate", "")).replace("T", " ")[:16]
                    arr_date = str(seg.get("arrDate", "")).replace("T", " ")[:16]
                    equipment = seg.get("equipment", "N/A")
                    booking_class = seg.get("bookingClass", "N/A")
                    coupon = seg.get("couponNumber", "")
                    coupon_status = seg.get("couponStatus", "OK")
                    op_air = carrier.get("opAirCode", air_code)
                    op_flight_no = carrier.get("opAirFlightNo", flight_no)

                    output.append(f"航班: {air_code}{flight_no} {dep_port} → {arr_port}")
                    if op_air != air_code or str(op_flight_no) != str(flight_no):
                        output.append(f"  实际承运: {op_air}{op_flight_no}")
                    output.append(f"  出发: {dep_date}")
                    output.append(f"  到达: {arr_date}")
                    output.append(f"  机型: {equipment}")
                    output.append(f"  舱位: {booking_class}")
                    if coupon:
                        output.append(f"  联票号: {coupon} ({coupon_status})")
                    if seg.get("fareBasis"):
                        output.append(f"  票价基础: {seg['fareBasis']}")
                    if seg.get("flightMiles"):
                        output.append(f"  飞行里程: {seg['flightMiles']}英里")

                    # 附加服务 (per pax)
                    for anc in flight.get("flightAncillaries", []):
                        pax_name = anc.get("name", "")
                        seat = anc.get("seat")
                        free_bag = anc.get("freeBaggage", {})
                        bag_qty = free_bag.get("quantity") if free_bag else None
                        if pax_name:
                            extra = []
                            if seat:
                                extra.append(f"座位 {seat}")
                            if bag_qty:
                                extra.append(f"免费行李 {bag_qty}件")
                            if extra:
                                output.append(f"  [{pax_name}] {', '.join(extra)}")

            # 费用明细
            output.append("")
            output.append("【费用明细】")
            payment = conf.get("paymentDetails", {})
            currency = payment.get("currency", "MYR")
            pax_fare_costs = conf.get("paxFareCost", [])
            if pax_fare_costs:
                total = 0
                for i, pfc in enumerate(pax_fare_costs, 1):
                    fb = pfc.get("fareBreakDown", {})
                    base_fare = fb.get("baseFare", 0)
                    total_fare = fb.get("totalFare", 0)
                    tax = fb.get("tax", {}).get("totalTax", 0)
                    curr = pfc.get("currency", currency)
                    total += total_fare
                    output.append(f"  乘客{i} ({fb.get('paxType', 'ADT')}):")
                    output.append(f"    基础票价: {base_fare} {curr}")
                    output.append(f"    税费: {tax} {curr}")
                    output.append(f"    合计: {total_fare} {curr}")
                output.append(f"  ---")
                output.append(f"  总合计: {total} {currency}")
            else:
                output.append("  (无费用信息)")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
