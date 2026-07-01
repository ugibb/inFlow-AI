"""WeChat iLink CDN media upload (AES-128-ECB) for outbound image messages."""
from __future__ import annotations

import base64
import hashlib
import math
import secrets
from typing import Any
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"


def _encrypted_size(rawsize: int) -> int:
    return math.ceil((rawsize + 1) / 16) * 16


def _encrypt_aes_ecb(plaintext: bytes, key: bytes) -> bytes:
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _aes_key_b64_hex(aes_hex: str) -> str:
    """Format B from iLink spec: base64(ASCII hex string)."""
    return base64.b64encode(aes_hex.encode("ascii")).decode("ascii")


async def upload_image_item(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    headers: dict[str, str],
    to_user_id: str,
    image_bytes: bytes,
    base_info: dict[str, Any],
) -> dict[str, Any]:
    """Upload image to CDN; return a sendmessage item_list entry (type=2)."""
    aes_hex = secrets.token_hex(16)
    aes_key = bytes.fromhex(aes_hex)
    rawsize = len(image_bytes)
    rawfilemd5 = hashlib.md5(image_bytes).hexdigest()
    filesize = _encrypted_size(rawsize)
    filekey = secrets.token_hex(16)
    ciphertext = _encrypt_aes_ecb(image_bytes, aes_key)

    upload_req = {
        "filekey": filekey,
        "media_type": 1,
        "to_user_id": to_user_id,
        "rawsize": rawsize,
        "rawfilemd5": rawfilemd5,
        "filesize": filesize,
        "no_need_thumb": True,
        "aeskey": aes_hex,
        "base_info": base_info,
    }
    r = await client.post(
        f"{base_url}/ilink/bot/getuploadurl",
        headers=headers,
        json=upload_req,
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"getuploadurl HTTP {r.status_code}: {r.text[:300]}")

    data = r.json() or {}
    upload_url = data.get("upload_full_url")
    if not upload_url:
        upload_param = data.get("upload_param")
        if upload_param:
            upload_url = (
                f"{CDN_BASE}/upload"
                f"?encrypted_query_param={quote(upload_param, safe='')}"
                f"&filekey={filekey}"
            )
        else:
            raise RuntimeError(f"getuploadurl missing upload URL: {r.text[:300]}")
    up = await client.post(
        upload_url,
        headers={"Content-Type": "application/octet-stream"},
        content=ciphertext,
        timeout=120,
    )
    if up.status_code != 200:
        raise RuntimeError(f"CDN upload HTTP {up.status_code}: {up.text[:200]}")

    encrypt_query_param = up.headers.get("x-encrypted-param") or up.headers.get(
        "X-Encrypted-Param"
    )
    if not encrypt_query_param:
        raise RuntimeError("CDN upload missing x-encrypted-param response header")

    return {
        "type": 2,
        "image_item": {
            "media": {
                "encrypt_query_param": encrypt_query_param,
                "aes_key": _aes_key_b64_hex(aes_hex),
                "encrypt_type": 1,
            },
            "mid_size": filesize,
        },
    }
