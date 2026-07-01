"""WechatCallbackQueue — tracks pending image-card push-backs to WeChat users.

Lifecycle:
    pending   → pipeline still running (run_index not yet complete)
    ready     → run_index finished; callback_loop will pick up and render
    rendering → card_renderer called; in-flight LLM + playwright
    sent      → image delivered via ilink sendmessage
    failed    → rendering or send error (error column has details)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.core.database import Base


class WechatCallbackQueue(Base):
    __tablename__ = "wechat_callback_queue"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # NULL when article already existed (no new IngestJob was created)
    job_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    # Delivery metadata
    wechat_account_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    sender_id = Column(Text, nullable=False)       # ilink to_user_id
    context_token = Column(Text, nullable=True)    # ilink context_token

    # Lifecycle
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )
    # pending | ready | rendering | sent | failed

    card_path = Column(Text, nullable=True)        # absolute path to PNG after render
    error = Column(Text, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    sent_at = Column(DateTime(timezone=True), nullable=True)
