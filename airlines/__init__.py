"""航司适配器注册表"""
from typing import Dict, Type
from .base import AirlineAdapter, FormField
from .f9 import F9Adapter
from .ij import IJAdapter
from .mm import MMAdapter
from .ch import NineCAdapter
from .sl import SLAdapter
from .hx import HXAdapter
from .mf import MFAdapter
from .fr import FRAdapter
from .vj import VJAdapter
from .fy import FYAdapter
from .aq import AQAdapter
from .gq import GQAdapter
from .fivej import FiveJAdapter
from .dd import DDAdapter
from .od import ODAdapter

# 所有航司在这里注册。新增航司 = 新建一个 xxx.py + 加到 REGISTRY
REGISTRY: Dict[str, Type[AirlineAdapter]] = {
    "f9": F9Adapter,
    "ij": IJAdapter,
    "mm": MMAdapter,
    "9c": NineCAdapter,
    "sl": SLAdapter,
    "hx": HXAdapter,
    "mf": MFAdapter,
    "fr": FRAdapter,
    "vj": VJAdapter,
    "fy": FYAdapter,
    "aq": AQAdapter,
    "gq": GQAdapter,
    "5j": FiveJAdapter,
    "dd": DDAdapter,
    "od": ODAdapter,
}


def get_adapter(code: str):
    """通过航司代码获取适配器实例。找不到返回 None。"""
    cls = REGISTRY.get(code.lower())
    return cls() if cls else None


def list_airlines():
    """返回所有航司配置列表"""
    return [cls().get_config() for cls in REGISTRY.values()]


__all__ = ["REGISTRY", "get_adapter", "list_airlines", "AirlineAdapter", "FormField"]
