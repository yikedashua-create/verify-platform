"""MM 乐桃航司适配器

API: bearer 流程
1. POST login_url 拿 access_token
2. POST api_url 带 Bearer token 拿订单
"""
import requests
from .base import AirlineAdapter, FormField


class MMAdapter(AirlineAdapter):
    code = "mm"
    name = "MM乐桃航司"
    api_type = "bearer"
    login_url = "https://api.flypeach.com/manage/api/mmb/auth/login"
    api_url = "https://api.flypeach.com/manage/api/mmb/reservation/{confirmationNumber}"
    client_id = "29222978338458925777954627887837"
    client_secret = "hEP9YY4hH8xAWVQ4ZC54CbdSUtX9nqUbh6xEkJ9kxAqeDqWeGE92jCpzpmHJvzxW"

    form_fields = [
        FormField("confirmationNumber", label="票号", placeholder="如：ABC123"),
        FormField("lastName", label="姓", placeholder="如：ZHANG/SAN"),
    ]

    def _call_api(self, form_data: dict):
        login_payload = {
            "clientId": self.client_id,
            "clientSecret": self.client_secret,
            "confirmationNumber": form_data.get("confirmationNumber", ""),
            "grantType": "reservation",
            "lastName": form_data.get("lastName", ""),
            "scope": "*",
        }
        login_headers = {"Content-Type": "application/json"}

        try:
            login_resp = requests.post(self.login_url, json=login_payload,
                                       headers=login_headers, timeout=self.timeout)
            login_resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            return {"_error": f"登录失败: {e}\n\n请检查票号和姓是否正确"}

        login_result = login_resp.json()
        access_token = login_result.get("accessToken")
        if not access_token:
            return {"_error": "获取访问令牌失败"}

        api_url = self.api_url.format(confirmationNumber=form_data.get("confirmationNumber", ""))
        reservation_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

        try:
            reservation_resp = requests.post(
                api_url,
                headers=reservation_headers,
                json={"confirmationNumber": form_data.get("confirmationNumber", "")},
                timeout=self.timeout,
            )
            reservation_resp.raise_for_status()
            return reservation_resp.json()
        except requests.exceptions.HTTPError as e:
            return {"_error": f"查询失败: {e}\n\n请检查票号和姓是否正确"}

    def _parse(self, raw) -> dict:
        if isinstance(raw, dict) and raw.get("_error"):
            return {"success": False, "error": raw["_error"]}

        try:
            data = raw if isinstance(raw, dict) else {}
            output = []
            output.append("=" * 50)
            output.append("查询成功")
            output.append("=" * 50)
            output.append("")
            output.append("【订单信息】")
            output.append(f"订单号: {data.get('confirmationNumber', 'N/A')}")
            output.append(f"币种: {data.get('reservationCurrency', 'N/A')}")
            output.append(f"余额: {data.get('reservationBalance', 'N/A')}")
            output.append(f"预订时间: {data.get('bookDate', 'N/A')}")
            output.append(f"最后更新: {data.get('lastModified', 'N/A')}")

            logical_flights = data.get("logicalFlights", [])
            physical_flights = data.get("physicalFlights", [])
            if logical_flights:
                output.append("")
                output.append("【航班信息】")
                for i, flight in enumerate(logical_flights):
                    flight_no = "N/A"
                    for pf in physical_flights:
                        if pf.get("logicalFlightId") == flight.get("logicalFlightId"):
                            flight_no = pf.get("flightNumber", "N/A")
                            break

                    dep_time = flight.get("departureTime", "")
                    arr_time = flight.get("arrivaltime", "")
                    if "T" in dep_time:
                        dep_time = dep_time.split("T")[1].split("+")[0] if "+" in dep_time else dep_time.split("T")[1]
                    if "T" in arr_time:
                        arr_time = arr_time.split("T")[1].split("+")[0] if "+" in arr_time else arr_time.split("T")[1]

                    output.append(f"航班{i+1}: {flight.get('origin', 'N/A')} → {flight.get('destination', 'N/A')}")
                    output.append(f"  航班号: {flight_no}")
                    output.append(f"  日期: {flight.get('departureDate', 'N/A')[:10] if flight.get('departureDate') else 'N/A'}")
                    output.append(f"  时间: {dep_time} - {arr_time}")
                    output.append(f"  舱位: {flight.get('fareClassCode', 'N/A')}")
                    output.append(f"  状态: {flight.get('status', 'N/A')}")

            persons = data.get("persons", [])
            if persons:
                output.append("")
                output.append("【乘客信息】")
                for person in persons:
                    title = person.get("title", "")
                    gender = "男" if person.get("gender") == "M" else "女"
                    output.append(f"{title} {person.get('firstName', 'N/A')} {person.get('lastName', 'N/A')}")
                    output.append(f"  性别: {gender}")
                    output.append(f"  出生日期: {person.get('dob', 'N/A')}")
                    output.append(f"  邮箱: {person.get('email', 'N/A')}")

            payments = data.get("payments", [])
            if payments:
                output.append("")
                output.append("【付款信息】")
                for p in payments:
                    output.append(f"金额: {p.get('paymentAmount', 'N/A')} {data.get('reservationCurrency', 'JPY')}")
                    output.append(f"方式: {p.get('paymentMethod', 'N/A')}")
                    output.append(f"状态: {p.get('status', 'N/A')}")

            charges = data.get("charges", [])
            if charges:
                output.append("")
                output.append("【费用明细】")
                total = 0
                for c in charges:
                    desc = c.get("description", c.get("codeType", ""))
                    amount = c.get("amount", 0)
                    currency = c.get("currency", "JPY")
                    total += amount
                    if desc:
                        output.append(f"  {desc}: {amount} {currency}")
                    else:
                        output.append(f"  {c.get('codeType', 'N/A')}: {amount} {currency}")
                output.append(f"  ---")
                output.append(f"  合计: {total} {data.get('reservationCurrency', 'JPY')}")

            flight_ssrs = data.get("flightSsrs", [])
            if flight_ssrs:
                ssrs_by_category = {}
                for ssr in flight_ssrs:
                    cat = ssr.get("category", "other")
                    ssrs_by_category.setdefault(cat, []).append(ssr)

                category_names = {
                    "baggage": "行李", "seat": "座位", "insurance": "保险",
                    "sport": "运动装备", "support": "特殊协助", "other": "其他",
                }

                output.append("")
                output.append("【可购买服务】")
                for cat, ssrs in ssrs_by_category.items():
                    cat_name = category_names.get(cat, cat)
                    output.append(f"  [{cat_name}]")
                    for ssr in ssrs:
                        desc = ssr.get("description", ssr.get("ssrCode", ""))
                        amount = ssr.get("amount", 0)
                        if amount > 0:
                            output.append(f"    {desc}: {amount} JPY")
                        else:
                            output.append(f"    {desc}")

            return {"success": True, "data": "\n".join(output), "flight_info": data}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
