"""Review schedule API — user-facing self-service for periodic knowledge digest."""
"""Review schedule API — user-facing self-service for periodic knowledge digest.

⚠️ 未启用：本 router 不挂载（保留现状，不修不动）。生成/调度逻辑由
原 extensions/review/service.py 并入本文件；send_wechat 已迁 services/wechat_push.py。
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.dependencies import get_current_user
from backend.core.models import Article, ReviewSchedule, User, WechatAccount

logger = logging.getLogger(__name__)

SHANGHAI = ZoneInfo("Asia/Shanghai")


# ── Review content generation（原 extensions/review/service.py 并入）─────────
async def _list_articles_since(db: AsyncSession, user_id: UUID, since: datetime) -> List[Article]:
    """User's articles created since `since` (timezone-aware)."""
    r = await db.execute(
        select(Article)
        .where(Article.user_id == user_id, Article.created_at >= since)
        .order_by(Article.created_at.desc())
        .limit(50)
    )
    return list(r.scalars().all())


async def generate_review_text(
    db: AsyncSession, user_id: UUID, since: datetime, freq_days: int
) -> Tuple[Optional[str], List[dict]]:
    """Build the review text + citation map.

    Returns (text_with_markers, cite_map) where:
    - text_with_markers may contain [[N]] tokens that frontends can replace
      with clickable links to article id at index N
    - cite_map is a list of {"idx": N, "id": "<uuid>", "title": "..."}

    Returns (None, []) when there's nothing to review.
    """
    articles = await _list_articles_since(db, user_id, since)
    if not articles:
        return None, []

    # Build numbered article list for the LLM. The same N becomes the [[N]] citation.
    lines = []
    cite_map: List[dict] = []
    for i, a in enumerate(articles[:30], 1):
        platform = a.source_platform or "web"
        title = (a.title or "Untitled").strip()
        summary_head = (a.summary or "").strip().replace("\n", " ")[:80]
        lines.append(f"{i}. [{platform}] {title[:60]}" + (f" — {summary_head}" if summary_head else ""))
        cite_map.append({"idx": i, "id": str(a.id), "title": title[:60]})
    articles_block = "\n".join(lines)

    from backend.core.shared.ai_service import llm_service
    system_prompt = (
        "你是用户的个人知识助理。基于用户最近收藏的文章，生成一份精炼的知识回顾，"
        "用于在微信里推送给用户回看。输出纯文本（不要 markdown 符号），"
        "总长度控制在 350 字以内。"
    )
    freq_label = "这一天" if freq_days <= 1 else (f"过去 {freq_days} 天")
    user_prompt = f"""请基于以下 {len(articles)} 篇用户最近收藏的文章，生成{freq_label}的知识回顾：

{articles_block}

回顾要求：
1. 开头一句话总览（"{freq_label}你收藏了 {len(articles)} 篇，主要关注 X / Y / Z"，主题从内容里归纳）
2. 按主题聚类列出 2-3 个重点，每个 1-2 句概括（用「」括出主题名）
3. 推荐 1 篇最值得重读的——**必须用 [[N]] 标记文章编号**（N 是上方编号），例如 [[3]]，方便前端转链接
4. 结尾一句简短鼓励

直接返回正文，不要任何前缀/标题/markdown。"""
    try:
        text = await llm_service._chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.5,
        )
        return text.strip(), cite_map
    except Exception as e:
        logger.exception(f"review LLM failed for user {user_id}: {e}")
        return None, cite_map


# ── Schedule lifecycle helpers ─────────────────────────────────────────
def compute_next_send_at(freq_days: int, time_of_day: str, ref: Optional[datetime] = None) -> datetime:
    """Compute the next send time in UTC.

    Uses Asia/Shanghai for the time_of_day field. If `ref` is given, start from
    ref+freq_days; otherwise from "today" (or tomorrow if today's time has already passed).
    """
    hh, mm = (int(x) for x in time_of_day.split(":"))
    now_sh = datetime.now(SHANGHAI)
    if ref is None:
        candidate = now_sh.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if candidate <= now_sh:
            candidate += timedelta(days=1)
    else:
        ref_sh = ref.astimezone(SHANGHAI)
        candidate = (ref_sh + timedelta(days=freq_days)).replace(
            hour=hh, minute=mm, second=0, microsecond=0
        )
        if candidate <= now_sh:
            # ref+freq_days landed in the past (clock skew or paused for a while);
            # bump forward by full freq cycles until in future.
            while candidate <= now_sh:
                candidate += timedelta(days=max(freq_days, 1))
    return candidate.astimezone(timezone.utc)


router = APIRouter(prefix="/api/review", tags=["review"])


class ScheduleIn(BaseModel):
    enabled: bool = False
    frequency_days: int = Field(default=7, ge=1, le=90)
    time_of_day: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")

    @field_validator("time_of_day")
    @classmethod
    def valid_time(cls, v: str) -> str:
        try:
            hh, mm = v.split(":")
            if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
                raise ValueError()
        except Exception:
            raise ValueError("time_of_day must be HH:MM in 24h")
        return v


class ScheduleOut(BaseModel):
    enabled: bool
    frequency_days: int
    time_of_day: str
    next_send_at: Optional[datetime] = None
    last_sent_at: Optional[datetime] = None
    has_wechat_binding: bool


class CitationOut(BaseModel):
    idx: int
    id: str
    title: str


class PreviewOut(BaseModel):
    text: Optional[str]
    article_count: int
    citations: list[CitationOut] = []
    message: Optional[str] = None


@router.get("/schedule", response_model=ScheduleOut)
async def get_schedule(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the current user's review config (defaults if none)."""
    r = await db.execute(
        select(ReviewSchedule).where(ReviewSchedule.user_id == current_user.id)
    )
    s = r.scalar_one_or_none()

    wb = await db.execute(
        select(WechatAccount.id).where(
            WechatAccount.user_id == current_user.id, WechatAccount.is_active.is_(True)
        )
    )
    has_wechat = wb.scalar_one_or_none() is not None

    if not s:
        return ScheduleOut(
            enabled=False,
            frequency_days=7,
            time_of_day="09:00",
            has_wechat_binding=has_wechat,
        )
    return ScheduleOut(
        enabled=s.enabled,
        frequency_days=s.frequency_days,
        time_of_day=s.time_of_day,
        next_send_at=s.next_send_at,
        last_sent_at=s.last_sent_at,
        has_wechat_binding=has_wechat,
    )


@router.put("/schedule", response_model=ScheduleOut)
async def update_schedule(
    body: ScheduleIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update the current user's review config. Computes next_send_at when enabling."""
    r = await db.execute(
        select(ReviewSchedule).where(ReviewSchedule.user_id == current_user.id)
    )
    s = r.scalar_one_or_none()

    next_at = compute_next_send_at(body.frequency_days, body.time_of_day) if body.enabled else None

    if s is None:
        s = ReviewSchedule(
            user_id=current_user.id,
            enabled=body.enabled,
            frequency_days=body.frequency_days,
            time_of_day=body.time_of_day,
            next_send_at=next_at,
        )
        db.add(s)
    else:
        s.enabled = body.enabled
        s.frequency_days = body.frequency_days
        s.time_of_day = body.time_of_day
        # Recompute next_send_at when enabling or freq/time changes. Preserve when disabling.
        if body.enabled:
            s.next_send_at = next_at
        else:
            s.next_send_at = None
    await db.commit()
    await db.refresh(s)

    wb = await db.execute(
        select(WechatAccount.id).where(
            WechatAccount.user_id == current_user.id, WechatAccount.is_active.is_(True)
        )
    )
    has_wechat = wb.scalar_one_or_none() is not None

    return ScheduleOut(
        enabled=s.enabled,
        frequency_days=s.frequency_days,
        time_of_day=s.time_of_day,
        next_send_at=s.next_send_at,
        last_sent_at=s.last_sent_at,
        has_wechat_binding=has_wechat,
    )


@router.post("/preview", response_model=PreviewOut)
async def preview_review(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a review preview NOW (no push). Window = last 7 days by default."""
    # Use the saved frequency if any, else default 7
    r = await db.execute(
        select(ReviewSchedule).where(ReviewSchedule.user_id == current_user.id)
    )
    s = r.scalar_one_or_none()
    freq = s.frequency_days if s else 7
    since = datetime.now(timezone.utc) - timedelta(days=freq)

    cnt_r = await db.execute(
        select(Article.id).where(Article.user_id == current_user.id, Article.created_at >= since)
    )
    count = len(cnt_r.all())

    if count == 0:
        return PreviewOut(
            text=None,
            article_count=0,
            message=f"过去 {freq} 天没有新收藏，没东西可回顾",
        )

    text, cite_map = await generate_review_text(db, current_user.id, since, freq)
    return PreviewOut(
        text=text,
        article_count=count,
        citations=[CitationOut(**c) for c in cite_map],
    )
