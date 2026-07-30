"""
数据模型 + 票状态枚举(半自动版)

设计原则(2026-07-27 更新):
- 不再做账号池轮训,每次 verify 由 CLI 指定 account
- 账号只用来"保存最近一次 cookie,避免 30 分钟内重复输验证码"
- 业务核心:输入 (ticket_no, account_phone) → 输出 (status, raw_status)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ============================================================
# 票状态枚举
# ============================================================

class TicketStatus(str, Enum):
    """MF 厦航"我的订单"页显示的票状态枚举(业务归一化)"""

    UNUSED = "未使用"
    USED = "已使用"
    REFUNDED = "已退票"
    CHANGED = "已改期"
    UNKNOWN = "未知"

    @classmethod
    def from_raw(cls, raw: str) -> "TicketStatus":
        """把页面上的原始状态字符串归一化

        匹配规则(优先级从高到低):
        - 已使用类:已使用 / 已乘机 / 已出行 / 已飞 / 已登机
        - 已退票类:已退票 / 全退 / 部分退票 / 退票中 / 申请退 / 已退
        - 已改期类:已改期 / 已改签 / 改期中 / 已变更 / 改签成功 / 已改
        - 未使用类(优先级最低):未使用 / 未出行 / 未乘机 / 已出票 / 可使用 / 出票完成 / 出票成功 / 待出票
        - 其他 → UNKNOWN
        """
        if not raw:
            return cls.UNKNOWN

        s = raw.strip()

        if any(k in s for k in ["已使用", "已乘机", "已出行", "已飞", "已登机"]):
            return cls.USED

        if any(k in s for k in ["已退票", "全退", "部分退", "退票中", "申请退", "已退", "退票成功"]):
            return cls.REFUNDED

        if any(k in s for k in ["已改期", "已改签", "改期中", "已变更", "改签成功", "已改"]):
            return cls.CHANGED

        if any(k in s for k in ["未使用", "未出行", "未乘机", "已出票", "可使用", "出票完成", "出票成功", "待出票"]):
            return cls.UNUSED

        return cls.UNKNOWN


# ============================================================
# 账号(简化版:只为 cookie 缓存,不做池管理)
# ============================================================

class Account(BaseModel):
    """账号(半自动版:只存 cookie + 状态,不做池管理)

    字段说明:
    - phone: 白鹭会员手机号(主键,verify 时必传)
    - cookie_json: 上次登录后的 Playwright storage_state(避免 30 分钟内重复输码)
    - cookie_expires_at: cookie 预计失效时间(默认登录后 7 天,只是估算)
    - last_login_at: 上次登录时间
    - last_used_at: 上次 verify 时间
    - note: 备注(可选,出票员名、采购时间等)
    """

    phone: str
    cookie_json: Optional[str] = None
    cookie_expires_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    note: str = ""

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, v: str) -> str:
        v = v.strip()
        if not v or not v.isdigit() or len(v) < 11:
            raise ValueError(f"phone 必须为 11 位以上数字,实际: {v!r}")
        return v

    @property
    def has_valid_cookie(self) -> bool:
        """cookie 是否还有效(简化判断:有 JSON 就算有效,真实验证看登录后是否被踢)"""
        return bool(self.cookie_json)


# ============================================================
# 验真结果
# ============================================================

class VerifyResult(BaseModel):
    """单次验真结果(API 返回格式)"""

    ticket_no: str = Field("", description="第一个票号(731 开头,多人订单时)")
    ticket_nos: list[str] = Field(default_factory=list, description="全部票号(2026-07-29 加,多人订单)")
    order_no: str = Field("", description="订单号(查订单详情用)")
    status: TicketStatus = Field(..., description="归一化后的票状态")
    raw_status: str = Field("", description="页面原始状态字符串")
    # 2026-07-30 加:从 /tRetailAPISolution/order/extract/ JSON API 拿到的完整数据
    raw_json: Optional[dict] = Field(default=None, description="完整 JSON 响应(订单/乘客/航段/支付等)")
    passengers: list[dict] = Field(default_factory=list, description="乘机人列表 [{name, ticket_no, ticket_status, ...}]")
    segments: list[dict] = Field(default_factory=list, description="航段列表")
    pnr: str = Field("", description="PNR / 订座记录号 (reservationId)")
    contact_name: str = Field("", description="联系人姓名")
    contact_phone: str = Field("", description="联系人电话")
    booking_id: str = Field("", description="bookingId (UUID, XiamenAir 内部用)")
    queried_at: datetime = Field(default_factory=datetime.now, description="查询时间")
    account_phone: str = Field("", description="使用的白鹭会员账号手机号")
    took_ms: int = Field(0, description="查询耗时(毫秒)")
    error: str = Field("", description="错误信息(成功时为空)")

    class Config:
        use_enum_values = True
