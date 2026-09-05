"""Authentication router — login, current user, change password, WeChat mini-program login."""
import base64
import binascii

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import get_settings
from backend.core.database import get_db
from backend.core.models.user import User
from backend.core.models.wechat_binding import WechatBinding
from backend.core.dependencies import (
    bearer_scheme,
    decode_access_token,
    get_current_user,
    hash_password,
    verify_password,
    create_access_token,
)
from backend.core.utils.logger import get_logger

logger = get_logger("auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ─────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class UserInfo(BaseModel):
    id: str
    username: str
    is_super_admin: bool
    is_active: bool
    created_at: str

    class Config:
        from_attributes = True


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=6, max_length=100)


class WechatLoginRequest(BaseModel):
    """小程序 wx.login 的 code 一次性（5 分钟）；昵称/头像为「填写能力」产物，选填。"""
    code: str = Field(..., min_length=1)
    invite_code: str = ""
    nickname: str = ""
    avatar_base64: str = ""


class WxProfile(BaseModel):
    nickname: str | None = None
    avatar: str | None = None  # data URI 或 None


class WechatLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict
    wx_profile: WxProfile


# ── Routes ──────────────────────────────────────────────────
@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login with username and password, return JWT token."""
    from sqlalchemy import select

    result = await db.execute(
        select(User).where(User.username == body.username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被停用，请联系管理员",
        )

    token = create_access_token(user.id, user.username, user.is_super_admin)

    return LoginResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "username": user.username,
            "is_super_admin": user.is_super_admin,
            "is_active": user.is_active,
        },
    )


@router.get("/me", response_model=UserInfo)
async def get_me(current_user: User = Depends(get_current_user)):
    """Get current logged-in user info."""
    return UserInfo(
        id=str(current_user.id),
        username=current_user.username,
        is_super_admin=current_user.is_super_admin,
        is_active=current_user.is_active,
        created_at=str(current_user.created_at) if current_user.created_at else "",
    )


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change current user's password (requires old password)."""
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="原密码错误",
        )

    current_user.password_hash = hash_password(body.new_password)
    await db.commit()

    return {"message": "密码修改成功"}


# ── WeChat mini-program login ───────────────────────────────
_AVATAR_MAX_BYTES = 1024 * 1024  # 解码后 ≤1MB
_NICKNAME_MAX_LEN = 64


def _clean_nickname(raw: str) -> str | None:
    nick = (raw or "").strip()
    return nick[:_NICKNAME_MAX_LEN] or None


def _clean_avatar(raw: str) -> str | None:
    """校验 base64 头像 → data URI。嗅探 magic bytes（JPEG/PNG/WebP），

    解码后 ≤1MB；不合法返回 None（忽略该字段，不阻断登录）。
    """
    b64 = (raw or "").strip()
    if not b64:
        return None
    if b64.startswith("data:"):  # 容忍前端直传 data URI
        b64 = b64.split(",", 1)[-1]
    try:
        data = base64.b64decode(b64)
    except (binascii.Error, ValueError):
        return None
    if not data or len(data) > _AVATAR_MAX_BYTES:
        return None
    if data[:3] == b"\xff\xd8\xff":
        mime = "image/jpeg"
    elif data[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        return None
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


async def _jscode2session(code: str) -> str:
    """code → openid。微信侧任何 errcode（含 code 过期/复用）统一 401 让前端重试。"""
    s = get_settings()
    if not s.wechat_appid or not s.wechat_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="微信登录未配置（.env 缺 WECHAT_APPID / WECHAT_SECRET）",
        )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.weixin.qq.com/sns/jscode2session",
                params={
                    "appid": s.wechat_appid,
                    "secret": s.wechat_secret,
                    "js_code": code,
                    "grant_type": "authorization_code",
                },
            )
            data = resp.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="微信接口不可达，请稍后重试",
        )
    if data.get("errcode"):
        logger.warning(
            "jscode2session errcode=%s errmsg=%s", data.get("errcode"), data.get("errmsg")
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="微信登录失败，请重试",
        )
    openid = data.get("openid")
    if not openid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="微信登录失败，请重试",
        )
    return openid


async def _resolve_bind_target(db: AsyncSession) -> User:
    """首绑目标账号：WECHAT_BIND_USERNAME 指定，缺省取第一个超管。"""
    from sqlalchemy import select

    s = get_settings()
    if s.wechat_bind_username:
        result = await db.execute(select(User).where(User.username == s.wechat_bind_username))
        target = result.scalar_one_or_none()
    else:
        result = await db.execute(
            select(User)
            .where(User.is_active == True, User.is_super_admin == True)  # noqa: E712
            .order_by(User.created_at)
            .limit(1)
        )
        target = result.scalar_one_or_none()
    if not target or not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="微信绑定账号未配置（.env 设 WECHAT_BIND_USERNAME 或确保存在超管账号）",
        )
    return target


@router.post("/wechat", response_model=WechatLoginResponse)
async def wechat_login(body: WechatLoginRequest, db: AsyncSession = Depends(get_db)):
    """微信小程序一键登录：jscode2session → openid → 绑定账号签发 JWT（免鉴权）。

    已绑定 openid → 直接续登；未绑定 → 按 WECHAT_INVITE_CODE 门禁首绑
    （码为空 = 免验直进）。响应多一个 wx_profile（昵称/头像），客户端
    静默续登时用它刷新本地资料。方案：02-docs/20260905_微信小程序微信登录方案.md
    """
    from sqlalchemy import select

    openid = await _jscode2session(body.code)

    result = await db.execute(select(WechatBinding).where(WechatBinding.openid == openid))
    binding = result.scalar_one_or_none()

    if not binding:
        s = get_settings()
        if s.wechat_invite_code:
            supplied = (body.invite_code or "").strip()
            if not supplied:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="invite_required"
                )
            if supplied != s.wechat_invite_code:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="invite_invalid"
                )

        target = await _resolve_bind_target(db)
        binding = WechatBinding(
            user_id=target.id,
            openid=openid,
            nickname=_clean_nickname(body.nickname),
            avatar=_clean_avatar(body.avatar_base64),
        )
        db.add(binding)
        await db.commit()
        logger.info("wechat binding created: user=%s", target.username)
    else:
        # 续登顺手更新资料（用户可能在登录页重新填了昵称/头像；空值不覆盖）
        nick = _clean_nickname(body.nickname)
        avatar = _clean_avatar(body.avatar_base64)
        if (nick and nick != binding.nickname) or (avatar and avatar != binding.avatar):
            if nick:
                binding.nickname = nick
            if avatar:
                binding.avatar = avatar
            await db.commit()

    user = await db.get(User, binding.user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="绑定账号已被停用",
        )

    token = create_access_token(
        user.id, user.username, user.is_super_admin, extra_claims={"wx_openid": openid}
    )

    return WechatLoginResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "username": user.username,
            "is_super_admin": user.is_super_admin,
            "is_active": user.is_active,
        },
        wx_profile=WxProfile(nickname=binding.nickname, avatar=binding.avatar),
    )


class WechatProfileRequest(BaseModel):
    nickname: str = ""
    avatar_base64: str = ""


@router.patch("/wechat/profile", response_model=WxProfile)
async def wechat_update_profile(
    body: WechatProfileRequest,
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    """更新当前微信的昵称/头像（我的页「编辑资料」）。空字段 = 不变。

    仅微信登录签发的 JWT 带 wx_openid claim 可调用；账号密码登录的
    token 无此 claim，返回 403。
    """
    from sqlalchemy import select

    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    payload = decode_access_token(credentials.credentials)
    openid = payload.get("wx_openid")
    if not openid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号密码登录不支持编辑微信资料",
        )

    result = await db.execute(select(WechatBinding).where(WechatBinding.openid == openid))
    binding = result.scalar_one_or_none()
    if not binding:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="微信绑定不存在")

    nick = _clean_nickname(body.nickname)
    avatar = _clean_avatar(body.avatar_base64)
    if nick is not None:
        binding.nickname = nick
    if avatar is not None:
        binding.avatar = avatar
    await db.commit()

    return WxProfile(nickname=binding.nickname, avatar=binding.avatar)
