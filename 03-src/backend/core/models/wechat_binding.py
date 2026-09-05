"""WechatBinding — 微信小程序「微信一键登录」openid 与账号的绑定。

一个账号可绑多个微信（朋友各自 openid 一行，共享同一账号的库——
articles 按 user_id 隔离，绑定即共享）。昵称/头像由用户在小程序端
通过官方「头像昵称填写能力」主动提交（wx.getUserProfile 已对新应用
回收，不存在静默获取），avatar 存完整 data URI（≤1MB）。
方案：02-docs/20260905_微信小程序微信登录方案.md
"""

from __future__ import annotations

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from backend.core.database import Base


class WechatBinding(Base):
    __tablename__ = "wechat_bindings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    openid = Column(String(64), unique=True, nullable=False, index=True)

    # 用户主动填写的资料（选填）
    nickname = Column(String(64), nullable=True)
    avatar = Column(Text, nullable=True)  # data:image/xxx;base64,...

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
