"""MF 厦门航司适配器（内网 172.18.247.238:32000）"""
import requests
from .base import AirlineAdapter, FormField


class MFAdapter(AirlineAdapter):
    code = "mf"
    name = "MF厦门航司"
    api_type = "json_post"
    api_url = "http://172.18.247.238:32000/mf_app_verify"

    form_fields = [
        FormField("ticketNo", label="票号", placeholder="如：731XXXXXXXX"),
        FormField("passName", label="姓名", placeholder="如：ZHANG/SAN"),
        FormField("flightNo", label="航班号", placeholder="如：MF1234"),
        FormField("flightSchedule", label="航班时刻", placeholder="如：2026-06-06 22:35-23:35"),
    ]

    def _call_api(self, form_data: dict):
        flight_schedule = form_data.get("flightSchedule", "").strip()
        payload = {
            "ticketNo": form_data.get("ticketNo", "").strip(),
            "passName": form_data.get("passName", "").strip().upper(),
            "flightNo": form_data.get("flightNo", "").strip().upper(),
        }
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        resp = requests.post(self.api_url, json=payload, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        result = resp.json()
        # 把航班时刻附加到结果,生成凭证要用
        if flight_schedule and isinstance(result, dict):
            result["flightSchedule"] = flight_schedule
        return result

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

            data_list = raw.get("data", [])
            if not data_list:
                return {"success": False, "error": "未找到发票信息"}

            for idx, item in enumerate(data_list):
                output.append("")
                output.append(f"【发票信息 {idx + 1}】")
                flight_invoice_list = item.get("flightInvoiceInfoList", [])
                for flight_inv in flight_invoice_list:
                    psg_ticket = flight_inv.get("psgTicket", {})
                    output.append(f"票号: {psg_ticket.get('ticketNo', 'N/A')}")
                    output.append(f"乘客姓名: {psg_ticket.get('psgName', 'N/A')}")
                    output.append(f"乘客类型: {flight_inv.get('psgType', 'N/A')}")
                    output.append(f"开票时间: {flight_inv.get('issueTime', 'N/A')}")
                    output.append(f"办公室代码: {flight_inv.get('officeCode', 'N/A')}")
                    output.append(f"产品类型: {flight_inv.get('productTypeName', 'N/A')}")
                    output.append(f"发票状态: {flight_inv.get('ticketInvoiceStatus', 'N/A')}")
                    output.append(f"区域代码: {flight_inv.get('regionCode', 'N/A')}")

                    for seg in flight_inv.get("segmentInfoList", []):
                        output.append("")
                        output.append("  【航段信息】")
                        output.append(f"  航班号: {seg.get('fltNo', 'N/A')}")
                        output.append(f"  出发地: {seg.get('deptCityName', 'N/A')} ({seg.get('deptAirport3code', 'N/A')})")
                        output.append(f"  目的地: {seg.get('arrivalCityName', 'N/A')} ({seg.get('arrivalAirport3code', 'N/A')})")
                        output.append(f"  航班日期: {seg.get('fltDate', 'N/A')}")
                        output.append(f"  乘客状态: {seg.get('paxStatus', 'N/A')}")

                refund_invoice_list = item.get("refundInvoiceInfoList", [])
                if refund_invoice_list:
                    output.append("")
                    output.append("  【退款信息】")
                    for refund in refund_invoice_list:
                        output.append(f"    票号: {refund.get('ticketNo', 'N/A')}")

                emd_invoice_list = item.get("emdInvoiceInfoList", [])
                if emd_invoice_list:
                    output.append("")
                    output.append("  【EMD信息】")
                    for emd in emd_invoice_list:
                        output.append(f"    票号: {emd.get('ticketNo', 'N/A')}")

            return {"success": True, "data": "\n".join(output), "flight_info": raw}
        except Exception as e:
            import traceback
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}
