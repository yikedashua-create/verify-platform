"""F9 边疆航司适配器

流程: GET init 拿 cookie -> GET booking edit 拿 HTML -> 正则提数据
失败 fallback: GetCart 拿 JSON
"""
import re
import time
import json
import requests
import urllib3

from .base import AirlineAdapter, FormField

# 关掉 verify=False 的 warning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class F9Adapter(AirlineAdapter):
    code = "f9"
    name = "F9边疆航司"
    api_type = "session_get"
    api_url = "https://booking.flyfrontier.com/Booking/Edit?st=payment"
    form_fields = [
        FormField("confirmationCode", label="票号", placeholder="如：ABC123"),
        FormField("lastName", label="姓", placeholder="如：ZHANG/SAN"),
    ]

    def _call_api(self, form_data: dict):
        confirmation_code = form_data.get("confirmationCode", "").upper()
        last_name = form_data.get("lastName", "").upper()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.flyfrontier.com/travel/my-trips/manage-trip/",
            "X-Requested-With": "XMLHttpRequest",
        }

        session = requests.Session()
        init_url = "https://www.flyfrontier.com/travel/my-trips/manage-trip/"
        session.get(init_url, headers=headers, timeout=self.timeout, verify=False)

        api_url = f"https://booking.flyfrontier.com/Booking/Edit?st=payment&ln={last_name}&rl={confirmation_code}"
        edit_resp = session.get(api_url, headers=headers, timeout=self.timeout,
                                verify=False, allow_redirects=True)
        text = edit_resp.text

        data = {}
        patterns = {
            "BookingRecordLocator": r'"BookingRecordLocator"\s*:\s*"([^"]+)"',
            "BookingCurrencyCode": r'"BookingCurrencyCode"\s*:\s*"([^"]+)"',
            "From": r'"From"\s*:\s*"([^"]+)"',
            "To": r'"To"\s*:\s*"([^"]+)"',
            "Price": r'"Price"\s*:\s*([0-9.]+)',
            "FirstName": r'"FirstName"\s*:\s*"([^"]+)"',
            "LastName": r'"LastName"\s*:\s*"([^"]+)"',
            "DepartureDateLocal": r'"DepartureDateLocal"\s*:\s*"([^"]+)"',
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                data[key] = match.group(1) if key != "Price" else float(match.group(1))

        if data.get("BookingRecordLocator"):
            # 主路径: HTML 提数据
            return {
                "BookingRecordLocator": data.get("BookingRecordLocator"),
                "BookingCurrencyCode": data.get("BookingCurrencyCode", "USD"),
                "FlightData": {
                    "Flights": [{
                        "FromStateAirportCode": data.get("From", "N/A"),
                        "ToStateAirportCode": data.get("To", "N/A"),
                        "Price": data.get("Price", 0),
                        "DepartureDateLocalFormatted": (
                            data.get("DepartureDateLocal", "").replace("T", " ").split("+")[0]
                            if data.get("DepartureDateLocal") else "N/A"
                        ),
                    }]
                },
                "PassengerData": {
                    "passengers": [{
                        "FirstName": data.get("FirstName", "N/A"),
                        "LastName": data.get("LastName", "N/A"),
                    }]
                },
            }

        # fallback: GetCart
        cart_url = f"https://booking.flyfrontier.com/Cart/GetCart?pageUrl=/Booking/Index&_={int(time.time() * 1000)}"
        cart_resp = session.get(cart_url, headers=headers, timeout=self.timeout,
                                verify=False, allow_redirects=False)
        text = cart_resp.text

        if not text or len(text) < 50:
            return {"_error": "未获取到数据，请检查票号和姓"}

        try:
            return json.loads(text)
        except Exception:
            return {"_error": f"数据解析失败: {text[:200]}..."}

    def _parse(self, raw) -> dict:
        # raw 可能是 dict(成功) 或 {"_error": "..."}(失败)
        if isinstance(raw, dict) and raw.get("_error"):
            return {"success": False, "error": raw["_error"]}

        try:
            if not raw:
                return {"success": False, "error": "未获取到有效数据"}

            output = []
            output.append("=" * 50)
            output.append("查询成功")
            output.append("=" * 50)

            # 订单信息
            output.append("")
            output.append("【订单信息】")
            output.append(f"订单号: {raw.get('BookingRecordLocator', raw.get('confirmationNumber', 'N/A'))}")
            output.append(f"币种: {raw.get('BookingCurrencyCode', 'USD')}")

            # 航班信息
            flight_data = raw.get("FlightData") or raw.get("flightData") or {}
            if isinstance(flight_data, str):
                flight_data = {}
            flights = flight_data.get("Flights", []) or flight_data.get("flights", [])
            if not flights and isinstance(flight_data, list):
                flights = flight_data

            if flights:
                output.append("")
                output.append("【航班信息】")
                for flight in flights:
                    if isinstance(flight, dict):
                        from_airport = flight.get('FromStateAirportCode', flight.get('from', 'N/A'))
                        to_airport = flight.get('ToStateAirportCode', flight.get('to', 'N/A'))
                        output.append(f"航线: {from_airport} → {to_airport}")

                        info_share = flight.get('FlightsInfoCodeShare', [])
                        if info_share and isinstance(info_share, list):
                            flight_no = info_share[0].get('FlightNumber', 'N/A') if isinstance(info_share[0], dict) else 'N/A'
                        else:
                            flight_no = flight.get('flightNumber', 'N/A')
                        output.append(f"航班号: {flight_no}")

                        output.append(f"日期: {flight.get('DepartureDateLocalFormatted', 'N/A')}")
                        output.append(f"价格: ${flight.get('Price', 0)}")

            # 乘客信息
            passenger_data = raw.get("PassengerData") or raw.get("passengerData", {})
            if isinstance(passenger_data, str):
                passenger_data = {}
            passengers = passenger_data.get("passengers", []) or passenger_data.get("Passengers", [])
            if not passengers and isinstance(passenger_data, list):
                passengers = passenger_data

            if passengers:
                output.append("")
                output.append("【乘客信息】")
                for p in passengers:
                    if isinstance(p, dict):
                        output.append(f"{p.get('FirstName', 'N/A')} {p.get('LastName', 'N/A')}")

            # 行李信息
            bags_data = raw.get("BagsData") or raw.get("bagsData", {})
            if isinstance(bags_data, str):
                bags_data = {}
            if bags_data:
                output.append("")
                output.append("【行李信息】")
                journeys = bags_data.get("Journeys", [])
                for journey in journeys:
                    if isinstance(journey, dict):
                        output.append(f"{journey.get('DepartStation', 'N/A')} → {journey.get('ArrivalStation', 'N/A')}")
                        for passenger in journey.get("Passengers", []):
                            if isinstance(passenger, dict):
                                carryon = passenger.get("CarryOnBags")
                                checked = passenger.get("CheckedBags")
                                carryon_str = f"{carryon}件" if carryon else "无"
                                checked_str = f"{checked}件" if checked else "无"
                                output.append(f"  {passenger.get('Name', 'N/A')}: 随身 {carryon_str}, 托运 {checked_str}")

            # 座位信息
            seats_data = raw.get("SeatsData") or raw.get("seatsData", {})
            if isinstance(seats_data, str):
                seats_data = {}
            if seats_data:
                output.append("")
                output.append("【座位信息】")
                for journey in seats_data.get("Journeys", []):
                    if isinstance(journey, dict):
                        for seat in journey.get("Seats", []):
                            if isinstance(seat, dict):
                                output.append(
                                    f"{seat.get('FirstName', 'N/A')} {seat.get('LastName', 'N/A')}: "
                                    f"座位 {seat.get('SeatNumber', '未选')}"
                                )

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": __import__("traceback").format_exc(),
            }
