"""9C 春秋航司适配器"""
import requests
from .base import AirlineAdapter, FormField


class NineCAdapter(AirlineAdapter):
    code = "9c"
    name = "9C春秋航司"
    api_type = "json_post"
    api_url = "http://120.24.148.171:30225/ch/baggageVerification"

    form_fields = [
        FormField("passengerName", label="乘客姓名", placeholder="如：ZHANG/SAN"),
        FormField("cardNo", label="证件号", placeholder="如：身份证号"),
        FormField("flightDate", label="航班日期", placeholder="YYYY-MM-DD", field_type="date"),
        FormField("flightNo", label="航班号", placeholder="如：9C7259"),
    ]

    def _call_api(self, form_data: dict):
        payload = {
            "passengerName": form_data.get("passengerName", "").strip().upper(),
            "cardNo": form_data.get("cardNo", "").strip(),
            "flightDate": form_data.get("flightDate", "").strip(),
            "flightNo": form_data.get("flightNo", "").strip().upper(),
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

            output = []
            output.append("=" * 50)
            output.append("查询成功")
            output.append("=" * 50)

            code = raw.get("code", "N/A")
            msg = raw.get("msg", "")
            output.append("")
            output.append(f"返回码: {code}")
            output.append(f"消息: {msg}")

            if code != 1 and code != "1":
                output.append("查询未成功，请检查输入信息")
                return {"success": False, "error": msg or "查询未成功"}

            output.append("")
            output.append("【订单信息】")
            output.append(f"订单号: {raw.get('orderNo', 'N/A')}")
            output.append(f"乘客姓名: {raw.get('uesrName', 'N/A')}")
            output.append(f"证件号: {raw.get('cardNo', 'N/A')}")

            output.append("")
            output.append("【航班信息】")
            output.append(f"航班号: {raw.get('flightNo', 'N/A')}")
            output.append(f"出发地: {raw.get('dptName', 'N/A')}")
            output.append(f"目的地: {raw.get('arrName', 'N/A')}")
            output.append(f"出发时间: {raw.get('dptTime', 'N/A')}")
            output.append(f"到达时间: {raw.get('arrTime', 'N/A')}")
            output.append(f"舱位: {raw.get('cain', 'N/A')}")

            output.append("")
            output.append("【行李信息】")
            output.append(f"行李额度: {raw.get('baggageValue', 'N/A')}")
            output.append(f"票价: {raw.get('price', 'N/A')} 元")

            output.append("")
            output.append("【其他信息】")
            output.append(f"出票日期: {raw.get('returnDate', 'N/A')}")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
