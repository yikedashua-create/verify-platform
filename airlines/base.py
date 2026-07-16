"""航司适配器基类。

约定:
  - 每航司一个文件 (如 f9.py),继承 AirlineAdapter
  - 必填: code / name / form_fields,以及 _call_api + _parse 两个方法
  - api_type: 标识调 API 风格,前端按需做特殊提示
    - "simple_post": 直接 POST 一个 URL,JSON 入参 JSON 出参
    - "session_get": 要先 GET 拿 cookie/session,再调业务接口 (F9 用)
    - "bearer": 要先登录拿 token,再调业务接口 (MM 用)
    - "custom": 自定义流程
"""
from abc import ABC, abstractmethod
from typing import List, Any
import traceback


class FormField:
    """表单字段定义,前端按这个渲染输入框"""

    def __init__(self, name: str, label: str = "", placeholder: str = "",
                 required: bool = True, field_type: str = "text", default: str = ""):
        self.name = name
        self.label = label or name
        self.placeholder = placeholder
        self.required = required
        self.field_type = field_type  # text | date | email | select
        self.default = default

    def to_dict(self):
        return {
            "name": self.name,
            "label": self.label,
            "placeholder": self.placeholder,
            "required": self.required,
            "field_type": self.field_type,
            "default": self.default,
        }


class AirlineAdapter(ABC):
    code: str = ""
    name: str = ""
    api_type: str = "custom"
    form_fields: List[FormField] = []
    timeout: int = 60

    def get_config(self) -> dict:
        # 按业务场景自动分类访问方式(给前端做标注用)
        if "172.18.247.238" in self.api_url:
            access_type = "内网网关"
        elif self.api_type == "bearer":
            access_type = "需登录"
        elif self.api_type in ("session_get",):
            access_type = "需登录态"
        else:
            access_type = "公网 API"

        # 官方验真网址 (用户维护在 _official_urls.py)
        from ._official_urls import OFFICIAL_VERIFY_URLS
        verify_url = OFFICIAL_VERIFY_URLS.get(self.code, "")

        return {
            "code": self.code,
            "name": self.name,
            "api_type": self.api_type,
            "access_type": access_type,
            "verify_url": verify_url,
            "form_fields": [f.to_dict() for f in self.form_fields],
        }

    def query(self, form_data: dict) -> dict:
        """对外统一入口: 调 API + 解析,捕获所有异常"""
        try:
            raw = self._call_api(form_data)
            parsed = self._parse(raw)
            # 自动补查询时间戳(老 GUI 行为兼容)
            if parsed.get("success") and "query_time" not in parsed:
                from datetime import datetime
                parsed["query_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return parsed
        except Exception as e:
            return {
                "success": False,
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
            }

    @abstractmethod
    def _call_api(self, form_data: dict) -> Any:
        """调 API,返回原始结果(结构由子类自己定义)"""
        raise NotImplementedError

    @abstractmethod
    def _parse(self, raw: Any) -> dict:
        """把原始结果转成 {success, data, ...}

        data 一般是字符串(GUI 老格式),前端直接展示。
        """
        raise NotImplementedError
