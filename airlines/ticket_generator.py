"""机票凭证 HTML 生成器

从航司查询结果 (flight_info) 提取乘客/航班信息,套模板生成 IATA 风格凭证 HTML。
覆盖 13 个航司的特殊字段差异(9C/MM/SL/MF/5J/GQ/F9/IJ/HX/FR/VJ/FY/AQ)。
"""
import re
from datetime import datetime


# ============================================
# 字段提取
# ============================================

def extract_field(data: dict, keys: list) -> str:
    """从数据中提取字段,兼容 13 个航司的字段差异"""
    if not isinstance(data, dict):
        return "N/A"
    for key in keys:
        if key in data:
            val = data[key]
            if isinstance(val, str) and val.strip():
                return val.strip()
        # 嵌套 flightCartResponse
        flight_cart = data.get("flightCartResponse", {})
        if isinstance(flight_cart, dict) and key in flight_cart:
            val = flight_cart[key]
            if isinstance(val, str) and val.strip():
                return val.strip()
        # 大小写不敏感
        for k, v in data.items():
            if isinstance(k, str) and k.lower() == key.lower() and isinstance(v, str):
                return v.strip()
        for k, v in (flight_cart.items() if isinstance(flight_cart, dict) else []):
            if isinstance(k, str) and k.lower() == key.lower() and isinstance(v, str):
                return v.strip()
        # MF 厦门: 从 flightInvoiceInfoList → psgTicket.ticketNo 拿票号
        if key in ["eTicketNo", "ticketNo"] and "data" in data:
            data_list = data.get("data", [])
            if data_list and isinstance(data_list, list) and len(data_list) > 0:
                flight_invoice = data_list[0].get("flightInvoiceInfoList", []) if isinstance(data_list[0], dict) else []
                if flight_invoice and isinstance(flight_invoice[0], dict):
                    psg_ticket = flight_invoice[0].get("psgTicket", {})
                    ticket_no = psg_ticket.get("ticketNo", "")
                    if ticket_no:
                        return ticket_no
        # 9C 春秋: 顶层 orderNo 兼容
        if key == "confirmationNumber" and "orderNo" in data:
            return data.get("orderNo", "N/A")
        if key in ["eTicketNo", "ticketNo"] and "orderNo" in data:
            return data.get("orderNo", "N/A")
        # 5J 宿务: 顶层 recordLocator 兼容
        if key == "confirmationNumber" and "recordLocator" in data:
            return data.get("recordLocator", "N/A")
        # OD 峇迪航空: data.confirmationRes.pnr / data.ticketIssueDt / data.confirmationRes.passengerInfos[0].ticketNumber
        nested = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        conf = nested.get("confirmationRes", {}) if isinstance(nested.get("confirmationRes"), dict) else {}
        if key in ["confirmationNumber", "bookingPNR", "airlinePNR", "recordLocator", "bookingPnr", "confirmation"]:
            if conf.get("pnr"):
                return conf["pnr"]
        if key in ["eTicketNo", "ticketNo"]:
            pax_infos = conf.get("passengerInfos", []) or []
            if pax_infos and isinstance(pax_infos[0], dict) and pax_infos[0].get("ticketNumber"):
                return pax_infos[0]["ticketNumber"]
        if key in ["issueDate", "bookingDate", "bookedDate"]:
            if nested.get("ticketIssueDt"):
                return str(nested["ticketIssueDt"])[:19].replace("T", " ")
        # VN 越南航空 (2026-08-11): data.data.reservation.pnrCode / issuedUtcDate
        vn_nested_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        vn_nested_res = vn_nested_data.get("reservation", {}) if isinstance(vn_nested_data.get("reservation"), dict) else {}
        if key in ["confirmationNumber", "bookingPNR", "airlinePNR", "recordLocator", "bookingPnr", "confirmation"]:
            if vn_nested_res.get("pnrCode"):
                return vn_nested_res["pnrCode"]
        if key in ["issueDate", "bookingDate", "bookedDate"]:
            if vn_nested_res.get("issuedUtcDate"):
                return str(vn_nested_res["issuedUtcDate"])[:19].replace("T", " ")
    return "N/A"


def _safe_first(items, default="N/A"):
    """取列表第一个,空则返回默认"""
    if items and isinstance(items, list) and len(items) > 0:
        return items[0]
    return default


def _get_nested(obj, *keys, default="N/A"):
    """嵌套取值"""
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur if cur else default


def extract_passengers(data: dict) -> list:
    """提取乘客列表,统一成 {surname, givenName, idNumber, pax_type, eticketNo}"""
    if not isinstance(data, dict):
        return []

    # VN 越南航空: data.data.reservation.passengers[] (2026-08-11 新增)
    # VN adapter 的 flight_info 结构: {"success": true, "code": "0", "data": {"reservation": {..., "passengers": [...]}}}
    vn_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
    vn_res = vn_data.get("reservation", {}) if isinstance(vn_data.get("reservation"), dict) else {}
    if vn_res.get("passengers"):
        result = []
        for pax in vn_res["passengers"]:
            if not isinstance(pax, dict):
                continue
            ticket_doc = pax.get("ticketDocument") or {}
            eticket = pax.get("ticketNumber") or ticket_doc.get("ticketNumber") or "N/A"
            result.append({
                "surname": (pax.get("lastName") or "N/A").upper(),
                "givenName": (pax.get("firstName") or "N/A").upper(),
                "idNumber": pax.get("dateOfBirth") or "",  # VN 没 document 字段, 用 DOB 占位
                "pax_type": pax.get("passengerTypeCode", "ADT"),
                "eticketNo": eticket,
            })
        if result:
            return result

    # 9C 春秋: 顶层 uesrName 特殊
    if "uesrName" in data:
        uesr_name = data.get("uesrName", "")
        if "/" in uesr_name:
            parts = uesr_name.split("/")
            surname = parts[0] if len(parts) > 0 else "N/A"
            given_name = parts[-1] if len(parts) > 1 else surname
        else:
            parts = uesr_name.strip().split() if uesr_name.strip() else []
            surname = parts[0] if len(parts) > 0 else "N/A"
            given_name = parts[-1] if len(parts) > 1 else (parts[0] if len(parts) > 0 else "N/A")
        return [{
            "surname": surname.upper(),
            "givenName": given_name.upper(),
            "idNumber": data.get("cardNo", ""),
            "pax_type": "ADT",
            "eticketNo": data.get("orderNo", "N/A"),
        }]

    # 5J 宿务: passengers[].name.{first,last}
    if "passengers" in data and "bookingSummary" in data:
        result = []
        for pax in data.get("passengers", []):
            if not isinstance(pax, dict):
                continue
            name = pax.get("name", {})
            result.append({
                "surname": (name.get("last") or "N/A").upper(),
                "givenName": (name.get("first") or "N/A").upper(),
                "idNumber": "",
                "pax_type": pax.get("passengerTypeCode", "ADT"),
            })
        if result:
            return result

    # MF 厦门: data[].flightInvoiceInfoList[].psgTicket.psgName
    mf_data = data.get("data")
    if isinstance(mf_data, list) and mf_data and isinstance(mf_data[0], dict) and mf_data[0].get("flightInvoiceInfoList"):
        mf_passengers = []
        for item in mf_data:
            for flight_inv in item.get("flightInvoiceInfoList", []):
                psg_ticket = flight_inv.get("psgTicket", {})
                psg_name = psg_ticket.get("psgName", "")
                if psg_name and "/" in psg_name:
                    parts = psg_name.split("/")
                    surname = parts[0] if parts else "N/A"
                    given_name = parts[-1] if len(parts) > 1 else surname
                else:
                    surname = psg_name if psg_name else "N/A"
                    given_name = ""
                mf_passengers.append({
                    "surname": surname.upper(),
                    "givenName": given_name.upper(),
                    "idNumber": "",
                    "pax_type": flight_inv.get("psgType", "ADT"),
                    "eticketNo": psg_ticket.get("ticketNo", "N/A"),
                })
        if mf_passengers:
            return mf_passengers

    # 通用: 多种路径
    pax_list = None
    for path in [
        ["flightCartResponse", "passengerDisplayInfo"],
        ["flightCartResponse", "passengers"],
        ["passengerDisplayInfo"],
        ["passengers"],
        ["persons"],
        ["flightCartResponse", "persons"],
        ["data", "persons"],
        ["data", "passengers"],
        ["PassengerData", "passengers"],  # F9 边疆
        ["passengerData", "passengers"],
    ]:
        temp = data
        for key in path:
            if isinstance(temp, dict):
                temp = temp.get(key, {})
            else:
                temp = {}
                break
        if isinstance(temp, list) and len(temp) > 0:
            pax_list = temp
            break

    # DD 泰国皇雀: 嵌套 data.flights[].legs[].passengers[]
    if not pax_list:
        nested = []
        nested_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        for flight in nested_data.get("flights", []) or []:
            for leg in flight.get("legs", []) or []:
                for p in leg.get("passengers", []) or []:
                    if isinstance(p, dict):
                        nested.append(p)
        # 去重
        if nested:
            seen = set()
            unique = []
            for p in nested:
                key = f"{p.get('firstName', '')}|{p.get('lastName', '')}|{p.get('title', '')}"
                if key not in seen:
                    seen.add(key)
                    unique.append(p)
            pax_list = unique

    # OD 峇迪航空: data.confirmationRes.passengerInfos[]
    if not pax_list:
        nested_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
        conf = nested_data.get("confirmationRes", {}) if isinstance(nested_data.get("confirmationRes"), dict) else {}
        if isinstance(conf.get("passengerInfos"), list) and conf["passengerInfos"]:
            pax_list = conf["passengerInfos"]

    if not pax_list:
        return []

    passengers = []
    for pax in pax_list:
        if not isinstance(pax, dict):
            continue
        passenger_info = pax.get("passengerInfo", pax)
        # 大小写不敏感取 firstName/lastName/givenName/surname
        # 兼容 F9 (FirstName/LastName), OD 峇迪 (givenName/surname), 等
        first_name = ""
        last_name = ""
        for k, v in passenger_info.items():
            if not isinstance(v, str):
                continue
            kl = k.lower()
            if kl in ("firstname", "givenname") and not first_name:
                first_name = v
            elif kl in ("lastname", "surname") and not last_name:
                last_name = v

        if not first_name and not last_name:
            name_obj = passenger_info.get("name", {})
            if isinstance(name_obj, dict):
                first_name = name_obj.get("first", "") or ""
                last_name = name_obj.get("last", "") or ""
            elif isinstance(name_obj, str) and name_obj.strip():
                name_parts = name_obj.strip().split()
                first_name = name_parts[0] if name_parts else ""
                last_name = name_parts[-1] if len(name_parts) > 1 else first_name

        if not first_name and not last_name:
            full_name = passenger_info.get("name", passenger_info.get("psgName", ""))
            if "/" in full_name:
                parts = full_name.split("/")
                last_name = parts[0] if parts else ""
                first_name = parts[-1] if len(parts) > 1 else last_name

        name = f"{first_name} {last_name}".strip()
        name_parts = name.split() if name else ["N/A", "N/A"]
        given_name = name_parts[0] if name_parts else "N/A"
        surname = name_parts[-1] if len(name_parts) > 1 else given_name

        passengers.append({
            "surname": surname.upper(),
            "givenName": given_name.upper(),
            "idNumber": pax.get("documentNumber", ""),
            "pax_type": passenger_info.get("type", "ADT"),
        })
    return passengers


def extract_flights(data: dict) -> list:
    """提取航班列表,统一成 {flightNumber, airlineCode, origin, destination, departureDate, departureTime, arrivalTime, cabin, status}"""
    if not isinstance(data, dict):
        return []

    flights = []

    # 9C 春秋: 顶层平铺
    if "flightNo" in data and "data" not in data and "bookingSummary" not in data:
        flt_no = data.get("flightNo", "N/A")
        dpt_time = data.get("dptTime", "")
        arr_time = data.get("arrTime", "")
        if "T" in str(dpt_time):
            dep_date = dpt_time.split("T")[0]
            dep_time = dpt_time.split("T")[1][:5] if len(dpt_time.split("T")) > 1 else ""
        else:
            dep_date = str(dpt_time)[:10] if dpt_time else "N/A"
            dep_time = str(dpt_time)[11:16] if len(str(dpt_time)) > 11 else ""
        if "T" in str(arr_time):
            arr_time_str = arr_time.split("T")[1][:5] if len(arr_time.split("T")) > 1 else ""
        else:
            arr_time_str = str(arr_time)[11:16] if len(str(arr_time)) > 11 else ""
        flights.append({
            "flightNumber": flt_no,
            "airlineCode": "",
            "origin": data.get("dptName", "N/A"),
            "destination": data.get("arrName", "N/A"),
            "departureDate": dep_date,
            "departureTime": dep_time,
            "arrivalTime": arr_time_str,
            "cabin": "经济舱",
            "status": "OK",
        })
        return flights

    # 5J 宿务: bookingSummary.journeys[].segments[]
    if "bookingSummary" in data:
        booking_summary = data.get("bookingSummary", {})
        for journey in booking_summary.get("journeys", []):
            for seg in journey.get("segments", []):
                identifier = seg.get("identifier", {})
                carrier = identifier.get("carrierCode", "5J")
                flight_no = identifier.get("identifier", "N/A")
                seg_designator = seg.get("designator", {})
                dep_time = seg_designator.get("departure", "")
                arr_time = seg_designator.get("arrival", "")
                dep_date = dep_time.split("T")[0] if "T" in str(dep_time) else str(dep_time)[:10]
                dep_time_str = dep_time.split("T")[1][:5] if "T" in str(dep_time) else ""
                arr_time_str = arr_time.split("T")[1][:5] if "T" in str(arr_time) else ""
                flights.append({
                    "flightNumber": flight_no,
                    "airlineCode": carrier,
                    "origin": seg_designator.get("origin", "N/A"),
                    "destination": seg_designator.get("destination", "N/A"),
                    "departureDate": dep_date,
                    "departureTime": dep_time_str,
                    "arrivalTime": arr_time_str,
                    "cabin": seg.get("fareClass", "N/A"),
                    "status": "OK",
                })
        return flights

    # VN 越南航空: data.data.reservation.originDestinationOptions[].flightSegments[] (2026-08-11 新增)
    vn_flights_data = data.get("data", {}) if isinstance(data.get("data"), dict) else {}
    vn_res = vn_flights_data.get("reservation", {}) if isinstance(vn_flights_data.get("reservation"), dict) else {}
    if vn_res.get("originDestinationOptions"):
        for opt in vn_res["originDestinationOptions"]:
            for seg in opt.get("flightSegments", []):
                if not isinstance(seg, dict):
                    continue
                dep_dt = str(seg.get("departureDateTime", ""))
                arr_dt = str(seg.get("arrivalDateTime", ""))
                dep_date = dep_dt.split("T")[0] if "T" in dep_dt else dep_dt[:10]
                dep_time = dep_dt.split("T")[1][:5] if "T" in dep_dt else ""
                arr_time = arr_dt.split("T")[1][:5] if "T" in arr_dt else ""
                flights.append({
                    "flightNumber": seg.get("flightNumber", "N/A"),
                    "airlineCode": seg.get("marketingAirlineCode", "VN"),
                    "origin": seg.get("departureLocationCode", "N/A"),
                    "destination": seg.get("arrivalLocationCode", "N/A"),
                    "departureDate": dep_date,
                    "departureTime": dep_time,
                    "arrivalTime": arr_time,
                    "cabin": seg.get("classOfService", "N/A"),
                    "status": "USED" if seg.get("flown") or seg.get("segmentUsed") else "OK",
                })
        if flights:
            return flights

    # DD 泰国皇雀: data.flights[].legs[] (carrierCode/flightNumber 在 flight 顶层,cabin 在 passengers)
    if isinstance(data.get("data"), dict) and data["data"].get("flights"):
        for flight in data["data"].get("flights", []):
            if not isinstance(flight, dict):
                continue
            carrier = flight.get("carrierCode", "")
            for leg in flight.get("legs", []):
                if not isinstance(leg, dict):
                    continue
                # flightNumber 优先取 leg 自己的,fallback 到 flight
                flight_no = leg.get("flightNumber") or flight.get("flightNumber", "N/A")
                dep_time = leg.get("departureDate", "")
                arr_time = leg.get("arrivalDate", "")
                # cabin 在 leg.passengers[0]
                cabin = "ECONOMY"
                if leg.get("passengers"):
                    cabin = leg["passengers"][0].get("cabin", "ECONOMY")
                flights.append({
                    "flightNumber": flight_no,
                    "airlineCode": carrier,
                    "origin": leg.get("from", {}).get("code", "N/A"),
                    "destination": leg.get("to", {}).get("code", "N/A"),
                    "departureDate": dep_time.split("T")[0] if "T" in str(dep_time) else dep_time,
                    "departureTime": _split_time(dep_time),
                    "arrivalTime": _split_time(arr_time),
                    "cabin": cabin,
                    "status": "CANCELLED" if flight.get("cancelled") else "OK",
                })
        if flights:
            return flights

    # OD 峇迪航空: data.confirmationRes.fares[].flight[].flightSeg
    if isinstance(data.get("data"), dict) and isinstance(data["data"].get("confirmationRes"), dict):
        conf = data["data"]["confirmationRes"]
        for fare in conf.get("fares", []) or []:
            if not isinstance(fare, dict):
                continue
            for flight in fare.get("flight", []) or []:
                seg = flight.get("flightSeg", {}) if isinstance(flight, dict) else {}
                if not isinstance(seg, dict):
                    continue
                carrier = seg.get("carrier", {}) if isinstance(seg.get("carrier"), dict) else {}
                air_code = carrier.get("airCode", "OD")
                flight_no = seg.get("flightNo", "N/A")
                dep_date = seg.get("depDate", "")
                arr_date = seg.get("arrDate", "")
                cabin = seg.get("bookingClass", "ECONOMY")
                flights.append({
                    "flightNumber": str(flight_no),
                    "airlineCode": air_code,
                    "origin": seg.get("depPort", fare.get("depPort", "N/A")),
                    "destination": seg.get("arrPort", fare.get("arrPort", "N/A")),
                    "departureDate": dep_date.split("T")[0] if "T" in str(dep_date) else dep_date,
                    "departureTime": _split_time(dep_date),
                    "arrivalTime": _split_time(arr_date),
                    "cabin": cabin,
                    "status": seg.get("couponStatus", "OK"),
                })
        if flights:
            return flights

    # 尝试多种路径获取航班数据
    flight_data = None
    for path in [
        ["flightCartResponse", "selectedFares"],
        ["selectedFares"],
        ["flights"],
        ["flightCartResponse", "flights"],
        ["data", "flights"],
        ["logicalFlights"],
        ["data"],
        ["FlightData", "Flights"],  # F9 边疆
        ["flightData", "Flights"],
        ["flightData", "flights"],
    ]:
        temp = data
        for key in path:
            if isinstance(temp, dict):
                temp = temp.get(key, {})
            else:
                temp = {}
                break
        if isinstance(temp, list) and len(temp) > 0:
            flight_data = temp
            break

    if not flight_data:
        return flights

    # SL selectedFares 格式
    if flight_data and isinstance(flight_data[0], dict) and "flightGroups" in flight_data[0]:
        for fare in flight_data:
            for fg in fare.get("flightGroups", []):
                for fl in fg.get("flights", []):
                    dep_time = fl.get("departureDateTime", fl.get("departureDate", ""))
                    arr_time = fl.get("arrivalDateTime", fl.get("arrivalDate", ""))
                    marketing_airline = fl.get("marketingAirline", {})
                    airline_code = marketing_airline.get("code", fare.get("carrier", ""))
                    flights.append({
                        "flightNumber": fl.get("flightNumber", "N/A"),
                        "airlineCode": airline_code,
                        "origin": fl.get("departureAirport", "N/A"),
                        "destination": fl.get("arrivalAirport", "N/A"),
                        "departureDate": dep_time.split("T")[0] if "T" in str(dep_time) else dep_time,
                        "departureTime": _split_time(dep_time),
                        "arrivalTime": _split_time(arr_time),
                        "cabin": fl.get("travelClass", fl.get("cabin", "Economy")),
                        "status": fl.get("status", "OK"),
                    })
    # logicalFlights 格式 (MM 乐桃)
    elif flight_data and isinstance(flight_data[0], dict) and "flightInvoiceInfoList" not in flight_data[0]:
        for fl in flight_data:
            if not isinstance(fl, dict):
                continue
            dep_time_str = fl.get("departureTime", "")
            arr_time_str = fl.get("arrivaltime", "") or fl.get("arrivalTime", "")
            flight_number = "N/A"
            airline_code = "MM"
            physical_flights = data.get("physicalFlights", [])
            for pf in physical_flights:
                if isinstance(pf, dict) and pf.get("logicalFlightId") == fl.get("logicalFlightId"):
                    flight_number = pf.get("flightNumber", "N/A")
                    break
            if ":" in str(dep_time_str):
                dep_time = ":".join(dep_time_str.split(":")[:2])
                dep_date = fl.get("departureDate", "")
            else:
                dep_date = dep_time_str.split("T")[0] if "T" in str(dep_time_str) else dep_time_str
                dep_time = _split_time(dep_time_str)
            if ":" in str(arr_time_str):
                arr_time = ":".join(arr_time_str.split(":")[:2])
            else:
                arr_time = _split_time(arr_time_str)
            origin = fl.get("origin", fl.get("originAirport", fl.get("departureAirport", "N/A")))
            destination = fl.get("destination", fl.get("destinationAirport", fl.get("arrivalAirport", "N/A")))
            dep_date = fl.get("departureDate", "")
            if isinstance(dep_date, str) and "T" in dep_date:
                dep_date = dep_date.split("T")[0]
            flights.append({
                "flightNumber": flight_number,
                "airlineCode": airline_code,
                "origin": origin,
                "destination": destination,
                "departureDate": dep_date,
                "departureTime": dep_time,
                "arrivalTime": arr_time,
                "cabin": fl.get("fareClassCode", fl.get("cabin", "Economy")),
                "status": fl.get("status", "OK"),
            })
    # MF 厦门: data[].flightInvoiceInfoList[].segmentInfoList[]
    elif flight_data and isinstance(flight_data[0], dict) and "flightInvoiceInfoList" in flight_data[0]:
        for item in flight_data:
            for flight_inv in item.get("flightInvoiceInfoList", []):
                for seg in flight_inv.get("segmentInfoList", []):
                    flt_no = seg.get("fltNo", "N/A")
                    if len(flt_no) >= 3 and flt_no[:2].isalpha():
                        airline_code = flt_no[:2]
                        flight_number = flt_no[2:] if flt_no[2:].isdigit() else flt_no
                    else:
                        airline_code = "MF"
                        flight_number = flt_no
                    flights.append({
                        "flightNumber": flight_number,
                        "airlineCode": airline_code,
                        "origin": seg.get("deptAirport3code", "N/A"),
                        "destination": seg.get("arrivalAirport3code", "N/A"),
                        "departureDate": seg.get("fltDate", "N/A"),
                        "departureTime": "N/A",
                        "arrivalTime": "N/A",
                        "cabin": "经济舱",
                        "status": "OK",
                    })
    # 顶层 flights (GQ/5J/HX 等)
    else:
        for fl in flight_data:
            if not isinstance(fl, dict):
                continue
            legs = fl.get("legs", [])
            if legs:
                for leg in legs:
                    if not isinstance(leg, dict):
                        continue
                    dep_time = leg.get("departureDate", "")
                    arr_time = leg.get("arrivalDate", "")
                    identifier = leg.get("identifier", {})
                    carrier = identifier.get("carrierCode", fl.get("carrierCode", ""))
                    flights.append({
                        "flightNumber": carrier + identifier.get("identifier", fl.get("flightNumber", "N/A")),
                        "airlineCode": carrier,
                        "origin": _get_nested(leg, "from", "code", default=fl.get("origin", "N/A")),
                        "destination": _get_nested(leg, "to", "code", default=fl.get("destination", "N/A")),
                        "departureDate": dep_time.split("T")[0] if "T" in str(dep_time) else dep_time,
                        "departureTime": _split_time(dep_time),
                        "arrivalTime": _split_time(arr_time),
                        "cabin": fl.get("cabin", "Economy"),
                        "status": "OK" if not fl.get("isCancelled") else "CANCELLED",
                    })
                    break
            else:
                dep_time = fl.get("departureDate", fl.get("DepartureDateLocalFormatted", ""))
                arr_time = fl.get("arrivalDate", "")
                flights.append({
                    "flightNumber": fl.get("flightNumber", "N/A"),
                    "airlineCode": fl.get("carrierCode", ""),
                    "origin": _get_nested(fl, "from", "code", default=fl.get("origin", fl.get("FromStateAirportCode", "N/A"))),
                    "destination": _get_nested(fl, "to", "code", default=fl.get("destination", fl.get("ToStateAirportCode", "N/A"))),
                    "departureDate": dep_time.split("T")[0] if "T" in str(dep_time) else dep_time,
                    "departureTime": _split_time(dep_time),
                    "arrivalTime": _split_time(arr_time),
                    "cabin": fl.get("cabin", "Economy"),
                    "status": "OK",
                })

    return flights


def _split_time(time_str) -> str:
    """从 ISO 时间字符串提 HH:MM"""
    if not time_str or time_str == "N/A":
        return ""
    s = str(time_str)
    if "T" in s:
        t = s.split("T")[1]
        t = t.split("+")[0].split(".")[0]  # 去时区/毫秒
        return t[:5] if len(t) >= 5 else t
    if ":" in s:
        return ":".join(s.split(":")[:2])
    return ""


# ============================================
# 格式化
# ============================================

def format_flight_number(flight_number, airline_code="") -> str:
    if not flight_number or flight_number == "N/A":
        return "N/A"
    fn = flight_number.upper()
    if len(fn) >= 3 and fn[0].isalpha() and fn[1].isalpha():
        return fn
    if airline_code:
        prefix = airline_code.upper()
        if fn.startswith(prefix):
            return fn
        return prefix + fn
    return fn


def format_date(date_str) -> str:
    if not date_str or date_str == "N/A":
        return "N/A"
    if re.match(r'\d{4}-\d{2}-\d{2}', str(date_str)):
        return date_str
    if 'T' in str(date_str):
        return str(date_str).split('T')[0]
    try:
        return datetime.strptime(str(date_str), "%Y%m%d").strftime("%Y-%m-%d")
    except Exception:
        return str(date_str)[:10] if len(str(date_str)) >= 10 else str(date_str)


def format_time(time_str) -> str:
    if not time_str or time_str == "N/A":
        return "N/A"
    s = str(time_str)
    if 'T' in s:
        parts = s.split('T')
        if len(parts) >= 2:
            time_part = parts[1].split('+')[0].split('.')[0].split(':')
            return f"{time_part[0]}:{time_part[1]}" if len(time_part) >= 2 else s
    if ':' in s:
        parts = s.split(':')
        return f"{parts[0]}:{parts[1]}" if len(parts) >= 2 else s
    if re.match(r'\d{2}:\d{2}', s):
        return s
    return s[:5] if len(s) >= 5 else s


def format_cabin(cabin) -> str:
    if not cabin or cabin == "N/A":
        return "经济舱"
    cu = str(cabin).upper()
    if cu in ["Y", "ECO", "ECONOMY", "经济舱"]:
        return "经济舱"
    if cu in ["C", "BUS", "BUSINESS", "商务舱"]:
        return "商务舱"
    if cu in ["F", "FIRST", "头等舱"]:
        return "头等舱"
    if cu in ["W", "PREMIUM_ECONOMY", "超级经济舱"]:
        return "超级经济舱"
    return "经济舱"


def safe_filename(fn: str) -> str:
    invalid = '/\\:*?"<>|'
    for c in invalid:
        fn = fn.replace(c, "_")
    if fn in ["N/A", ""]:
        return "UNKNOWN"
    return fn


# ============================================
# HTML 模板 + 生成
# ============================================

BUILTIN_TEMPLATE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>航空客票凭证</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; color: #000 !important; }
        body { font-family: "SimSun", "Microsoft YaHei", "Courier New", monospace; width: 180mm; margin: 0; padding: 15px 20px; line-height: 1.6; background: #fff; }
        .ticket { width: 100%; padding: 30px 40px; }
        .header-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; }
        .iata-logo { width: 60px; height: 60px; }
        .divider { border-top: 1px solid #999; margin: 15px 0; }
        .title { text-align: center; font-size: 24px; font-weight: bold; margin: 25px 0; text-transform: uppercase; letter-spacing: 1px; }
        .info-section { display: flex; justify-content: space-between; margin-bottom: 25px; font-size: 16px; }
        .info-left, .info-right { width: 48%; }
        table { width: 100%; border-collapse: collapse; margin: 25px 0; }
        th, td { border: 1px solid #000; padding: 12px 8px; text-align: center; font-size: 14px; line-height: 1.6; }
        .notice { margin-top: 30px; border-top: 1px solid #999; padding-top: 20px; font-size: 14px; }
        .notice p { font-weight: bold; margin-bottom: 8px; }
        .notice ul { list-style-type: disc; padding-left: 25px; line-height: 1.8; }
    </style>
</head>
<body>
    <div class="ticket" id="ticket"></div>
    <script>
        document.getElementById("ticket").innerHTML = `
            <div class="header-top">
                <div class="iata-logo"><svg width="60" height="60" viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="none" stroke="black" stroke-width="2"/><text x="50" y="60" text-anchor="middle" font-size="20" font-weight="bold">IATA</text></svg></div>
            </div>
            <div class="divider"></div>
            <div class="title">ITINERARY</div>
            <div class="divider"></div>
            <div class="info-section">
                <div class="info-left">
                    <p>航空公司记录编号/AIRLINE PNR : {{airlinePnr}}</p>
                    <p>旅客姓/SURNAME : {{surname}}</p>
                    <p>身份识别代码/ID NUMBER : {{idNumber}}</p>
                </div>
                <div class="info-right">
                    <p>电子票号/ETKT NBR : {{eticketNo}}</p>
                    <p>旅客名/GIVEN NAME : {{givenName}}</p>
                    <p>出票日期/DATE OF ISSUE : {{issueDate}}</p>
                </div>
            </div>
            <div class="divider"></div>
            <table>
                <tr>
                    <th>ORIGIN/DES<br>起飞机场/抵达机场</th>
                    <th>FLIGHT<br>航班号</th>
                    <th>CLASS<br>舱位等级</th>
                    <th>DATE<br>出发日期</th>
                    <th>DEPARTURE TIME<br>起飞时间</th>
                    <th>ARRIVAL TIME<br>抵达时间</th>
                    <th>STATUS<br>状态</th>
                </tr>
                {{flightRows}}
            </table>
            <div class="notice">
                <p>NOTICE:</p>
                <ul>
                    <li>PLEASE ARRIVE AT THE AIRPORT BEFORE THE CHECK-IN TIME SPECIFIED BY THE AIRLINE.</li>
                    <li>DURING CHECK-IN, PLEASE PRODUCE YOUR VALID ID CARD USED WHEN YOU PURCHASE THE TICKET.</li>
                    <li>TO FIND OUT MORE ABOUT THE REGULATIONS OF OTHER AIRLINES, PLEASE REFER TO THE RELEVANT AIRLINES OR AGENTS FOR MORE INFORMATION.</li>
                </ul>
            </div>
        `;
    </script>
</body>
</html>'''


def _safe_str(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if s in ("N/A", r"N\/A"):
        return ""
    return s


def generate_ticket_html(
    airline_pnr: str, surname: str, given_name: str, id_number: str,
    eticket_no: str, issue_date: str,
    origin: str, destination: str, flight_number: str, cabin_class: str,
    departure_date: str, departure_time: str, arrival_time: str, status: str,
    template: str = None,
) -> str:
    """生成单张机票凭证 HTML"""
    template = template or BUILTIN_TEMPLATE

    flight_row = f"""<tr>
        <td>{_safe_str(origin)}/{_safe_str(destination)}</td>
        <td>{_safe_str(flight_number)}</td>
        <td>{_safe_str(cabin_class)}</td>
        <td>{_safe_str(departure_date)}</td>
        <td>{_safe_str(departure_time)}</td>
        <td>{_safe_str(arrival_time)}</td>
        <td>{_safe_str(status)}</td>
    </tr>"""

    html = template.replace("{{airlinePnr}}", _safe_str(airline_pnr))
    html = html.replace("{{surname}}", _safe_str(surname))
    html = html.replace("{{idNumber}}", _safe_str(id_number))
    html = html.replace("{{eticketNo}}", _safe_str(eticket_no))
    html = html.replace("{{givenName}}", _safe_str(given_name))
    html = html.replace("{{issueDate}}", _safe_str(issue_date))
    html = html.replace("{{flightRows}}", flight_row)
    html = html.replace("{{TICKET_DATA}}", "null")
    return html


# ============================================
# 主入口: 接收 flight_info + airline_code, 生成所有凭证
# ============================================

def generate_tickets(airline_code: str, flight_info: dict, flight_schedule: str = "") -> dict:
    """从查询结果生成所有乘客×航班的凭证

    返回: {
        success: bool,
        tickets: [{ file_name, html, pax_name }],
        error: str
    }
    """
    try:
        if not flight_info or not isinstance(flight_info, dict):
            return {"success": False, "error": "未找到有效的航班数据"}

        airline_pnr = extract_field(flight_info, [
            "bookingPNR", "airlinePNR", "confirmationNumber",
            "recordLocator", "bookingPnr", "confirmation",
            "BookingRecordLocator",  # F9 边疆
        ])
        eticket_no = extract_field(flight_info, [
            "eTicketNo", "ticketNo", "电子票号",
            "bookingPNR", "confirmationNumber", "confirmation",
            "BookingRecordLocator",  # F9 边疆
        ])
        # 兜底: 如果 eticket_no 没拿到,用 PNR 当文件名
        if eticket_no == "N/A" and airline_pnr != "N/A":
            eticket_no = airline_pnr
        issue_date = extract_field(flight_info, [
            "issueDate", "bookingDate", "bookedDate",
            "出票日期", "reservationDate",
        ])

        passengers = extract_passengers(flight_info)
        if not passengers:
            return {"success": False, "error": "未找到乘客信息"}

        flights = extract_flights(flight_info)
        if not flights:
            return {"success": False, "error": "未找到航班信息"}

        # MF 厦门: 从 flightSchedule 提时间
        dep_time_input = ""
        arr_time_input = ""
        if airline_code == "mf" and flight_schedule:
            parts = flight_schedule.split(" ")
            if len(parts) >= 2:
                time_part = parts[-1]
                time_parts = time_part.split("-")
                if len(time_parts) >= 2:
                    dep_time_input = time_parts[0].strip()
                    arr_time_input = time_parts[1].strip()

        tickets = []
        for pax_idx, pax in enumerate(passengers):
            for fl in flights:
                departure_time = dep_time_input if airline_code == "mf" else format_time(fl.get("departureTime", "N/A"))
                arrival_time = arr_time_input if airline_code == "mf" else format_time(fl.get("arrivalTime", "N/A"))

                html = generate_ticket_html(
                    airline_pnr=airline_pnr,
                    surname=pax.get("surname", "N/A"),
                    given_name=pax.get("givenName", "N/A"),
                    id_number=pax.get("idNumber", "N/A"),
                    eticket_no=eticket_no,
                    issue_date=format_date(issue_date),
                    origin=fl.get("origin", "N/A"),
                    destination=fl.get("destination", "N/A"),
                    flight_number=format_flight_number(fl.get("flightNumber", "N/A"), fl.get("airlineCode", "")),
                    cabin_class=format_cabin(fl.get("cabin", "")),
                    departure_date=format_date(fl.get("departureDate", "N/A")),
                    departure_time=departure_time,
                    arrival_time=arrival_time,
                    status="OK",
                )

                surname = safe_filename(pax.get("surname", "PAX"))
                given_name_raw = pax.get("givenName", "")
                given_name = safe_filename(given_name_raw)
                if given_name and given_name not in ["UNKNOWN", ""]:
                    pax_suffix = f"{surname}_{given_name}_{pax_idx+1}"
                else:
                    pax_suffix = f"{surname}_{pax_idx+1}"
                file_name = f"{pax_suffix}.html"

                tickets.append({
                    "file_name": file_name,
                    "html": html,
                    "pax_name": f"{pax.get('surname', 'N/A')}/{pax.get('givenName', 'N/A')}",
                })

        return {"success": True, "tickets": tickets, "count": len(tickets)}
    except Exception as e:
        import traceback
        return {"success": False, "error": f"生成失败: {type(e).__name__}: {e}\n{traceback.format_exc()}"}


# ============================================
# HTML → PNG (Playwright headless)
# ============================================

def _render_htmls_to_pngs(htmls: list, width: int = 800, height: int = 1100) -> list:
    """批量 HTML → PNG bytes。一次启 browser,避免重复启动开销。

    只截 .ticket 元素,避免整页大量空白。
    返回与 htmls 等长的 PNG bytes 列表。
    """
    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            for html in htmls:
                page.set_content(html, wait_until="domcontentloaded")
                # 等字体加载 + 模板里的 JS 跑完
                page.wait_for_timeout(300)
                # 只截 .ticket 元素,避开整页空白
                try:
                    png_bytes = page.locator('.ticket').first.screenshot(type="png")
                except Exception:
                    # 兜底:截整页
                    png_bytes = page.screenshot(full_page=True, type="png")
                results.append(png_bytes)
        finally:
            browser.close()
    return results


def generate_ticket_images(airline_code: str, flight_info: dict, flight_schedule: str = "") -> dict:
    """生成凭证 PNG 图片。直接给前端 download_button 用。

    返回: {
        success: bool,
        tickets: [{ file_name, png_base64, pax_name }],
        count: int,
        error: str
    }
    """
    import base64
    # 先生成 HTML
    tickets_result = generate_tickets(airline_code, flight_info, flight_schedule)
    if not tickets_result.get("success"):
        return tickets_result

    tickets = tickets_result.get("tickets", [])
    if not tickets:
        return {"success": False, "error": "无凭证可生成"}

    try:
        htmls = [t["html"] for t in tickets]
        png_bytes_list = _render_htmls_to_pngs(htmls)

        for ticket, png_bytes in zip(tickets, png_bytes_list):
            # base64 编码方便走 JSON
            ticket["png_base64"] = base64.b64encode(png_bytes).decode("ascii")
            # 文件名改 .png
            ticket["file_name"] = ticket["file_name"].replace(".html", ".png")
            # 不需要再回传 HTML, 减小 payload
            ticket.pop("html", None)

        return tickets_result
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": f"图片渲染失败: {type(e).__name__}: {e}\n{traceback.format_exc()}",
        }
