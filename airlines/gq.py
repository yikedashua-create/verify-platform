"""GQ 天空航司适配器（公网 Sabre 接口）"""
import os
import requests
from .base import AirlineAdapter, FormField


class GQAdapter(AirlineAdapter):
    code = "gq"
    name = "GQ天空航司"
    api_type = "json_post"
    api_url = "https://skyexpress-api-ew3.ezycommerce.sabre.com/api/v1/Booking/Get"

    form_fields = [
        FormField("confirmationNumber", label="订单号(PNR)", placeholder="如：VGEFEZ"),
        FormField("bookingLastName", label="姓", placeholder="如：LIU"),
    ]

    # GQ 接口需要特殊 header (tenant + client version + user identifier)
    # 2026-08-04 改: 凭证走环境变量,过期只改 env var 不用改代码
    #   GQ_TENANT_IDENTIFIER
    #   GQ_USER_IDENTIFIER
    #   GQ_CLIENT_VERSION  (默认 0.5.4016)
    # 旧硬编码值作为兜底(代码里保留,凭证失效时只换 env var)
    DEFAULT_EXTRA_HEADERS = {
        "Accept": "text/plain",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Origin": "https://flights.skyexpress.gr",
        "Referer": "https://flights.skyexpress.gr/",
        "User-Agent": "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36",
        "tenant-identifier": "WEC2oAjZr7TwNkK1irsCDbWxXtmGVK312f0h3fHfx0e7TwHqaEvR1oPKA1zwNKr6",
        "x-clientversion": "0.5.4016",
        "x-useridentifier": "Lj6GYPaCPdRZggFWMqJitl6iUPsu7S",
    }

    def _get_extra_headers(self) -> dict:
        """从环境变量读凭证,缺则用默认值(2026-08-04 加)"""
        env_tenant = os.environ.get("GQ_TENANT_IDENTIFIER", "").strip()
        env_user = os.environ.get("GQ_USER_IDENTIFIER", "").strip()
        env_client_ver = os.environ.get("GQ_CLIENT_VERSION", "").strip()
        headers = dict(self.DEFAULT_EXTRA_HEADERS)
        if env_tenant:
            headers["tenant-identifier"] = env_tenant
        if env_user:
            headers["x-useridentifier"] = env_user
        if env_client_ver:
            headers["x-clientversion"] = env_client_ver
        return headers

    def _call_api(self, form_data: dict):
        payload = {
            "confirmationNumber": form_data.get("confirmationNumber", "").strip().upper(),
            "bookingLastName": form_data.get("bookingLastName", "").strip().upper(),
            "languageCode": "en-us",
        }
        headers = {
            "Content-Type": "application/json",
            **self._get_extra_headers(),
        }
        try:
            resp = requests.post(self.api_url, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            # 2026-08-04 加: 401/403 时给明确错误,告诉用户凭证过期要换 env var
            if resp.status_code in (401, 403):
                return {
                    "_error": (
                        f"GQ 接口返回 {resp.status_code} Unauthorized — tenant-identifier / x-useridentifier 凭证过期\n"
                        f"💡 修法: 找 IT 或 Sky Express 代理拿新凭证,设置环境变量:\n"
                        f"   $env:GQ_TENANT_IDENTIFIER = '新值'\n"
                        f"   $env:GQ_USER_IDENTIFIER  = '新值'\n"
                        f"   $env:GQ_CLIENT_VERSION  = '新值'\n"
                        f"或 Railway Variables 加同名 env var。"
                    ),
                    "_status": resp.status_code,
                    "_body": resp.text[:500],
                }
            raise

    def _parse(self, raw) -> dict:
        # 2026-08-04 加: 处理 _call_api 返回的错误 dict(401/403 等)
        if isinstance(raw, dict) and raw.get("_error"):
            return {
                "success": False,
                "error": raw["_error"],
                "flight_info": raw,
            }
        try:
            if not raw:
                return {"success": False, "error": "未获取到有效数据"}

            output = ["=" * 50, "查询成功", "=" * 50]
            output.append("")
            output.append("【订单信息】")
            output.append(f"订单号(PNR): {raw.get('confirmationNumber', 'N/A')}")
            output.append(f"姓: {raw.get('bookingLastName', 'N/A')}")
            output.append(f"预订日期: {raw.get('bookingDate', 'N/A')}")
            output.append(f"币种: {raw.get('currency', 'N/A')}")
            output.append(f"状态: {'已取消' if raw.get('cancelled') else '正常'}")
            output.append(f"渠道: {raw.get('channel', 'N/A')}")
            output.append(f"IATA: {raw.get('iataCode', 'N/A')}")

            contact = raw.get("contact", {})
            if contact:
                output.append("")
                output.append("【联系信息】")
                output.append(f"姓名: {contact.get('firstName', 'N/A')} {contact.get('lastName', 'N/A')}")
                output.append(f"邮箱: {contact.get('email', 'N/A')}")
                output.append(f"电话: {contact.get('mobile', 'N/A')}")
                output.append(f"城市: {contact.get('city', 'N/A')}")
                output.append(f"国家: {contact.get('countryCode', 'N/A')}")

            passengers = raw.get("passengers", [])
            if passengers:
                output.append("")
                output.append("【乘客人信息】")
                for pax in passengers:
                    output.append(f"{pax.get('title', '')} {pax.get('firstName', 'N/A')} {pax.get('lastName', 'N/A')}")
                    output.append(f"  性别: {pax.get('gender', 'N/A')}")
                    output.append(f"  出生日期: {pax.get('dateOfBirth', 'N/A')}")
                    output.append(f"  国籍: {pax.get('nationality', 'N/A')}")
                    output.append(f"  乘客类型: {pax.get('passengerTypeCode', 'N/A')}")
                    group = pax.get("group", {})
                    if group:
                        output.append(f"  订单号: {group.get('checkInLocator', 'N/A')}")

                    for fl in pax.get("flights", []):
                        from_info = fl.get("from", {})
                        to_info = fl.get("to", {})
                        output.append("  航班信息:")
                        output.append(f"    航班号: {fl.get('flightNumber', 'N/A')}")
                        output.append(f"    舱位: {fl.get('cabin', 'N/A')}")
                        output.append(f"    出发: {from_info.get('name', 'N/A')} ({from_info.get('code', 'N/A')})")
                        output.append(f"    到达: {to_info.get('name', 'N/A')} ({to_info.get('code', 'N/A')})")
                        output.append(f"    出发时间: {fl.get('departureDate', 'N/A')}")
                        output.append(f"    到达时间: {fl.get('arrivalDate', 'N/A')}")
                        output.append(f"    飞行时长: {fl.get('flightTime', 'N/A')}分钟")

                        for svc in fl.get("services", []):
                            desc = svc.get("description", "N/A")
                            code = svc.get("code", "N/A")
                            price = svc.get("price", 0)
                            is_bundled = svc.get("isBundled", False)
                            price_str = f"{price} {svc.get('currency', 'EUR')}" if price > 0 else "已包含"
                            bundled_str = " (套餐包)" if is_bundled else ""
                            output.append(f"    附加服务: {code}: {desc} - {price_str}{bundled_str}")

            flights = raw.get("flights", [])
            if flights:
                output.append("")
                output.append("【航班信息】")
                for fl in flights:
                    carrier = fl.get("carrierCode", "N/A")
                    flight_num = fl.get("flightNumber", "N/A")
                    from_info = fl.get("from", {})
                    to_info = fl.get("to", {})
                    output.append(f"航班号: {carrier}{flight_num}")
                    output.append(f"舱位: {fl.get('cabin', 'N/A')}")
                    output.append(f"fareBasis: {fl.get('fareBasis', 'N/A')}")
                    output.append(f"出发: {from_info.get('name', 'N/A')} ({from_info.get('code', 'N/A')})")
                    output.append(f"到达: {to_info.get('name', 'N/A')} ({to_info.get('code', 'N/A')})")
                    output.append(f"出发时间: {fl.get('departureDate', 'N/A')}")
                    output.append(f"到达时间: {fl.get('arrivalDate', 'N/A')}")
                    output.append(f"飞行时长: {fl.get('flightTime', 'N/A')}分钟")
                    output.append(f"状态: {'已取消' if fl.get('isCancelled') else '正常'}")

                    for leg in fl.get("legs", []):
                        leg_from = leg.get("from", {})
                        leg_to = leg.get("to", {})
                        output.append(f"  [航段] {leg.get('flightNumber', 'N/A')}: {leg_from.get('code', 'N/A')} → {leg_to.get('code', 'N/A')}")
                        output.append(f"       起飞: {leg.get('departureDate', 'N/A')}")
                        output.append(f"       到达: {leg.get('arrivalDate', 'N/A')}")
                        output.append(f"       机型: {leg.get('equipmentType', 'N/A')}")
                        output.append(f"       状态: {leg.get('passengerSegmentStatus', 'N/A')}")

            charges = raw.get("charges", [])
            if charges:
                output.append("")
                output.append("【费用明细】")
                total = 0
                for ch in charges:
                    code = ch.get("code", "N/A")
                    desc = ch.get("description", "N/A")
                    amt = ch.get("amount", 0)
                    is_tax = ch.get("isTax", False)
                    is_ssr = ch.get("isSsr", False)
                    total += amt
                    type_str = "税" if is_tax else ("服务" if is_ssr else "票价")
                    output.append(f"  [{type_str}] {code}: {desc} - {amt}")
                output.append(f"  ---")
                output.append(f"  合计: {total} {raw.get('currency', 'EUR')}")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
