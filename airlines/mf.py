"""MF 厦门航司适配器(2026-07-28 双模式升级)

支持两种验真模式:
- 模式 1 已知票号(原逻辑):调内网 API 172.18.247.238:32000/mf_app_verify
- 模式 2 只有订单号(2026-07-28 新增):调 xm_mf_verify 自动查票号 + 状态

字段使用约定(前端用户填表时):
- 填了 orderNo  → 走模式 2(自动验真),accountPhone 必填
- 没填 orderNo,只填了 ticketNo → 走模式 1(内网 API)
- 两个都填 → 优先模式 2(自动验真)

密码走环境变量 XM_MF_PWD_<phone> 设置,不进 API/DB
例: set XM_MF_PWD_16673220623=hmling33*

数据目录(2026-07-28 新增):
- 默认: verify-platform/data/xm_mf_verify/accounts.db(跟 verify-platform 自己的数据放一起)
- 可被环境变量 XM_MF_ACCOUNTS_DB / XM_MF_RESULTS_DB 覆盖
- 首次部署:从 xm-mf-ticket-verify/data/accounts.db 拷过来能复用 cookie
"""
import os
import sys
import requests
import traceback
from pathlib import Path
from .base import AirlineAdapter, FormField


# 让 mf.py 能 import 同级目录的 xm_mf_verify/(项目根/下)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ============================================================
# xm_mf_verify 数据目录(2026-07-28 新增,跟 verify-platform 数据隔离)
# ============================================================
_MF_DATA_DIR = Path(
    os.environ.get("XM_MF_DATA_DIR", "")
) or (_PROJECT_ROOT / "data" / "xm_mf_verify")
_MF_DATA_DIR.mkdir(parents=True, exist_ok=True)

_MF_ACCOUNTS_DB = os.environ.get(
    "XM_MF_ACCOUNTS_DB", str(_MF_DATA_DIR / "accounts.db")
)
_MF_RESULTS_DB = os.environ.get(
    "XM_MF_RESULTS_DB", str(_MF_DATA_DIR / "verify_results.db")
)

# 初始化 DB schema(Streamlit reload 时也会重跑,init_all 内部幂等)
try:
    from xm_mf_verify.db import init_all
    init_all(_MF_ACCOUNTS_DB, _MF_RESULTS_DB)
except Exception as _e:  # 首次部署可能 xm_mf_verify 还没装好
    print(f"[mf.py] 警告:init xm_mf_verify DB 失败: {_e}")


def _get_password_for_phone(phone: str) -> str:
    """从环境变量读白鹭会员密码(约定 XM_MF_PWD_<phone>)"""
    if not phone:
        return ""
    env_key = f"XM_MF_PWD_{phone}"
    return os.environ.get(env_key, "")


class MFAdapter(AirlineAdapter):
    code = "mf"
    name = "MF厦门航司"
    api_type = "custom"  # 双模式,前端按 custom 处理
    api_url = "http://172.18.247.238:32000/mf_app_verify"  # 内网 API(模式 1 兜底)

    # ⚠️ required 全 False:用户按情况选填模式
    # 业务约束(在 _call_api / _call_xm_mf_verify 里校验):
    # - 模式 1: ticketNo 必填
    # - 模式 2: orderNo + accountPhone 必填
    form_fields = [
        # 模式 2:只有订单号(2026-07-28 新增)
        FormField("orderNo", label="订单号(只有订单号时填)", placeholder="如:202607271326379366", required=False),
        FormField("accountPhone", label="白鹭会员手机号", placeholder="如:16673220623", required=False),
        # 模式 1:已知票号(原逻辑)
        FormField("ticketNo", label="票号", placeholder="如:731XXXXXXXX", required=False),
        FormField("passName", label="姓名", placeholder="如:ZHANG/SAN", required=False),
        FormField("flightNo", label="航班号", placeholder="如:MF1234", required=False),
        FormField("flightSchedule", label="航班时刻", placeholder="如:2026-06-06 22:35-23:35", required=False),
    ]

    def _call_api(self, form_data: dict) -> dict:
        """智能分流:有 orderNo → 调 xm_mf_verify;只有 ticketNo → 调内网 API"""
        order_no = form_data.get("orderNo", "").strip()
        ticket_no = form_data.get("ticketNo", "").strip()

        if order_no:
            return self._call_xm_mf_verify(form_data)
        if ticket_no:
            return self._call_internal_api(form_data)
        return {
            "return_code": "FAIL",
            "return_msg": "请至少填 订单号 或 票号 其中一项",
        }

    # ============================================================
    # 模式 2:订单号 → xm_mf_verify 自动验真
    # ============================================================

    def _call_xm_mf_verify(self, form_data: dict) -> dict:
        """调 xm-mf-ticket-verify 项目,完成 OAuth2 登录 + 抓订单详情"""
        from xm_mf_verify.xiamenair import verify_ticket
        from xm_mf_verify.config import AppConfig, XiamenairConfig, PlaywrightConfig, DbConfig

        order_no = form_data.get("orderNo", "").strip()
        account_phone = form_data.get("accountPhone", "").strip()

        if not account_phone:
            return {
                "return_code": "FAIL",
                "return_msg": "订单号模式必须填白鹭会员手机号(accountPhone)",
            }

        password = _get_password_for_phone(account_phone)
        if not password:
            return {
                "return_code": "FAIL",
                "return_msg": (
                    f"未配置白鹭会员 {account_phone} 密码的环境变量 XM_MF_PWD_{account_phone}。\n"
                    f"PowerShell: $env:XM_MF_PWD_{account_phone} = 'your_password'"
                ),
            }

        try:
            # 自己 build cfg(2026-07-28):不依赖 config.yaml,行为可控
            # - headless=True:verify-platform 跑 MF 自动验真,后台跑不弹浏览器
            # - accounts_db / results_db:用 verify-platform 自己的 data 目录
            screenshots_dir = _MF_DATA_DIR / "screenshots"
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            cfg = AppConfig(
                xiamenair=XiamenairConfig(
                    login_url="https://ecipuia.xiamenair.com/api/v1/oauth2/authorize?uia_type=st&lang=zh-ww&client_id=uiaweb_client&redirect_uri=https%3A%2F%2Fwww.xiamenair.com%2Fzh-ww%2F",
                    home_url="https://www.xiamenair.com/zh-ww/",
                    booking_url_template="https://int-et.xiamenair.com/bookingManagement/displayBooking/list/{order_no}",
                ),
                playwright=PlaywrightConfig(
                    headless=True,  # 平台内调,headless 跑
                    screenshot_on_error=True,
                    screenshot_dir=str(screenshots_dir),
                ),
                db=DbConfig(
                    accounts_db=_MF_ACCOUNTS_DB,
                    results_db=_MF_RESULTS_DB,
                ),
            )
            # 验证码 solver:用 DdddocrSolver(纯自动,2026-07-28 实测 100% 准)
            # 不传 → verify_ticket 用 ManualSolver 默认,会卡 5 分钟等用户
            from xm_mf_verify.captcha import DdddocrSolver
            result = verify_ticket(
                order_no=order_no,
                ticket_no=form_data.get("ticketNo", "").strip(),
                account_phone=account_phone,
                account_password=password,
                cfg=cfg,
                accounts_db=_MF_ACCOUNTS_DB,
                captcha_solver=DdddocrSolver(),
            )
            return self._convert_xm_mf_result(result)
        except Exception as e:
            return {
                "return_code": "FAIL",
                "return_msg": f"xm-mf-ticket-verify 异常: {type(e).__name__}: {e}",
                "_traceback": traceback.format_exc(),
            }

    def _convert_xm_mf_result(self, result) -> dict:
        """把 xm-mf-ticket-verify 的 VerifyResult 转成 mf 适配器 raw 格式"""
        status = result.status.value if hasattr(result.status, "value") else str(result.status)
        xm_mf = {
            "ticket_no": result.ticket_no,
            "order_no": result.order_no,
            "status": status,
            "raw_status": result.raw_status,
            "queried_at": result.queried_at.isoformat() if hasattr(result.queried_at, "isoformat") else str(result.queried_at),
            "account_phone": result.account_phone,
            "took_ms": result.took_ms,
            "error": result.error,
        }
        if result.error:
            return {
                "return_code": "FAIL",
                "return_msg": result.error,
                "_xm_mf_result": xm_mf,
            }
        # 成功:包装成类似内网 API 的 data 结构(让 _parse 复用)
        return {
            "return_code": "SUCCESS",
            "return_msg": "OK",
            "data": [{
                "flightInvoiceInfoList": [{
                    "psgTicket": {"ticketNo": result.ticket_no},
                    "psgType": "ADT",
                    "issueTime": str(result.queried_at),
                    "ticketInvoiceStatus": status,
                    "segmentInfoList": [],
                }],
            }],
            "_xm_mf_result": xm_mf,
        }

    # ============================================================
    # 模式 1:已知票号 → 内网 API(原逻辑,完整保留)
    # ============================================================

    def _call_internal_api(self, form_data: dict) -> dict:
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
        if flight_schedule and isinstance(result, dict):
            result["flightSchedule"] = flight_schedule
        return result

    # ============================================================
    # 解析(自动验真模式单独走 _parse_xm_mf_result,内网 API 走原逻辑)
    # ============================================================

    def _parse(self, raw) -> dict:
        # 优先:自动验真模式
        xm_mf = raw.get("_xm_mf_result") if isinstance(raw, dict) else None
        if xm_mf is not None:
            return self._parse_xm_mf_result(xm_mf)

        # 兜底:内网 API 模式(原逻辑,完全保留)
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
            return {"success": False, "error": str(e) + "\n" + traceback.format_exc()}

    def _parse_xm_mf_result(self, xm_mf: dict) -> dict:
        """把 xm_mf_result 渲染成 mf 适配器的展示格式"""
        error = xm_mf.get("error", "")
        if error:
            return {
                "success": False,
                "error": f"xm-mf-ticket-verify 失败: {error}",
                "flight_info": xm_mf,
            }
        output = [
            "=" * 50,
            "查询成功 (xm-mf-ticket-verify 自动验真)",
            "=" * 50,
            "",
            f"订单号:     {xm_mf.get('order_no', 'N/A')}",
            f"票号:       {xm_mf.get('ticket_no', 'N/A')}",
            f"票状态:     {xm_mf.get('status', 'N/A')}",
            f"原始状态:   {xm_mf.get('raw_status', 'N/A')}",
            f"查询账号:   {xm_mf.get('account_phone', 'N/A')}",
            f"查询时间:   {xm_mf.get('queried_at', 'N/A')}",
            f"耗时:       {xm_mf.get('took_ms', 0)} ms",
        ]
        return {
            "success": True,
            "data": "\n".join(output),
            "flight_info": xm_mf,
        }
