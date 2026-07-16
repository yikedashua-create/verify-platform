"""SL 泰国狮航适配器"""
import requests
from .base import AirlineAdapter, FormField


class SLAdapter(AirlineAdapter):
    code = "sl"
    name = "SL泰国狮航"
    api_type = "json_post"
    api_url = "https://api2-ibe.bookcabin.com/managebooking/api/LoginManageBooking/LoginManageBookingNew"

    form_fields = [
        FormField("bookingPnr", label="订单号(PNR)", placeholder="如：ABC123"),
        FormField("lastName", label="姓", placeholder="如：KAMMUNGKUN"),
    ]

    def _call_api(self, form_data: dict):
        payload = {
            "airlineCode": "SL",
            "bookingPnr": form_data.get("bookingPnr", "").strip().upper(),
            "productType": "Flight",
            "lastName": form_data.get("lastName", "").strip().upper(),
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.bookcabin.com/",
        }
        resp = requests.post(self.api_url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _parse(self, raw) -> dict:
        try:
            if not raw:
                return {"success": False, "error": "未获取到有效数据"}

            output = []
            output.append("=" * 50)
            output.append("查询成功")
            output.append("=" * 50)

            booking_status = raw.get("bookingStatus", "N/A")
            error = raw.get("error", None)
            output.append("")
            output.append(f"预订状态: {booking_status}")
            if error:
                output.append(f"错误: {error}")

            if booking_status != 2:
                return {"success": False, "error": "查询未成功，请检查订单号和姓名"}

            flight_cart = raw.get("flightCartResponse", {})
            if not flight_cart:
                return {"success": False, "error": "未找到订单信息"}

            output.append("")
            output.append("【订单信息】")
            output.append(f"订单号(PNR): {flight_cart.get('bookingPNR', 'N/A')}")
            output.append(f"航司PNR: {flight_cart.get('airlinePNR', 'N/A')}")
            output.append(f"开具时间: {flight_cart.get('issueDate', 'N/A')}")
            output.append(f"Cart ID: {flight_cart.get('cartId', 'N/A')}")

            passenger_display_info = flight_cart.get("passengerDisplayInfo", [])
            if passenger_display_info:
                output.append("")
                output.append("【乘客人信息】")
                for pax_info in passenger_display_info:
                    passenger = pax_info.get("passengerInfo", {})
                    title = passenger.get("title", "")
                    first_name = passenger.get("firstName", "N/A")
                    last_name = passenger.get("lastName", "N/A")
                    pax_code = passenger.get("paxCode", "N/A")
                    is_travelling = passenger.get("isTravelling", False)
                    output.append(f"{title} {first_name} {last_name}")
                    output.append(f"  乘客类型: {pax_code}")
                    output.append(f"  是否出行: {'是' if is_travelling else '否'}")
                    output.append(f"  电子客票号: {pax_info.get('eTicketNo', 'N/A')}")
                    output.append(f"  免费行李额: {'有' if pax_info.get('hasFreeBaggage') else '无'}")
                    output.append(f"  保险: {'已包含' if pax_info.get('insuranceIncluded') else '未包含'}")

            selected_fares = flight_cart.get("selectedFares", [])
            if selected_fares:
                output.append("")
                output.append("【航班信息】")
                for fare in selected_fares:
                    cabin = fare.get("cabin", "N/A")
                    carrier = fare.get("carrier", "N/A")
                    for fg in fare.get("flightGroups", []):
                        segment_type = fg.get("segmentType", "N/A")
                        elapsed_time = fg.get("elapsedTime", 0)
                        stops = fg.get("numberOfStops", 0)
                        output.append(f"航段类型: {segment_type}")
                        output.append(f"飞行时长: {elapsed_time}分钟")
                        output.append(f"经停次数: {stops}")
                        for fl in fg.get("flights", []):
                            flight_number = fl.get("flightNumber", "N/A")
                            marketing_airline = fl.get("marketingAirline", {})
                            airline_code = marketing_airline.get("code", carrier)
                            airline_name = marketing_airline.get("name", "N/A")
                            dep_airport = fl.get("departureAirport", "N/A")
                            dep_airport_name = fl.get("departureAirportName", "N/A")
                            arr_airport = fl.get("arrivalAirport", "N/A")
                            arr_airport_name = fl.get("arrivalAirportName", "N/A")
                            dep_terminal = fl.get("departureTerminal", "N/A")
                            arr_terminal = fl.get("arrivalTerminal", "N/A")
                            travel_class = fl.get("travelClass", "N/A")
                            status = fl.get("status", "N/A")
                            flight_duration = fl.get("flightDuration", "N/A")

                            output.append(f"航班号: {flight_number}")
                            output.append(f"航司: {airline_code} ({airline_name})")
                            output.append(f"出发: {dep_airport} ({dep_airport_name}) {dep_terminal}")
                            output.append(f"到达: {arr_airport} ({arr_airport_name}) {arr_terminal}")
                            output.append(f"出发时间: {fl.get('departureDateTime', 'N/A')}")
                            output.append(f"到达时间: {fl.get('arrivalDateTime', 'N/A')}")
                            output.append(f"舱位: {travel_class} ({cabin})")
                            output.append(f"状态: {status}")
                            output.append(f"飞行时长: {flight_duration}分钟")

            flight_booking_items = flight_cart.get("flightsBookingItemReferences", [])
            if flight_booking_items:
                output.append("")
                output.append("【航班引用信息】")
                for item in flight_booking_items:
                    output.append(f"航班号: {item.get('flightNumber', 'N/A')}")
                    output.append(f"航司代码: {item.get('carrierCode', 'N/A')}")
                    output.append(f"提供商: {item.get('provider', 'N/A')}")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
