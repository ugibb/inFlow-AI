#!/usr/bin/env bash
# inFlow AI — 验证 Docker 容器内 Key 是否已生效（向服务商发真实探测请求）
# 用法: ./verify-docker-keys.sh
#
# 通常在 ./sync-env-docker.sh 之后自动调用；也可单独执行以复查。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.baota.yml)

info()  { echo "[INFO]  $*"; }
error() { echo "[ERROR] $*" >&2; }

if ! command -v docker &>/dev/null || ! docker compose version &>/dev/null; then
  error "需要 Docker + Compose v2"
  exit 1
fi

if ! "${COMPOSE[@]}" ps --status running backend 2>/dev/null | grep -q backend; then
  error "backend 容器未运行，请先执行: ./sync-env-docker.sh 或 ./start-docker.sh --restart"
  exit 1
fi

info "检查容器内 Key 指纹（确认 .env 已注入，不输出完整 Key）..."
"${COMPOSE[@]}" exec -T backend python <<'PY'
import os

KEYS = (
    "SILICONFLOW_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "EMBEDDING_API_KEY",
    "SERVICE_TOKEN_WECHAT_BOT",
    "inFlow_PUBLIC_BASE",
)

def fingerprint(name: str) -> str:
    val = (os.environ.get(name) or "").strip()
    if not val:
        return "(未设置)"
    if len(val) <= 8:
        return "****"
    return f"{val[:4]}****{val[-4:]}"

print("── 容器内环境变量指纹 ──")
for k in KEYS:
    print(f"  {k}: {fingerprint(k)}")
PY

echo ""
info "向 LLM / Embedding / GROQ 发起连通性探测..."
"${COMPOSE[@]}" exec -T backend python <<'PY'
import asyncio
import os
import sys
import httpx
from app.core.config_manager import (
    get_llm_config,
    get_embedding_config,
    test_llm_connection,
    test_embedding_connection,
)

async def probe(name, coro):
    r = await coro
    ok = r.get("ok", False)
    detail = r.get("detail") or r.get("error") or r.get("message") or ""
    ms = r.get("latency_ms", "")
    tag = "OK  " if ok else "FAIL"
    line = f"[{tag}] {name}: {detail}"
    if ms != "":
        line += f" ({ms}ms)"
    print(line)
    return ok

async def probe_groq():
    key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not key:
        print("[SKIP] GROQ ASR: 未配置 GROQ_API_KEY")
        return True
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
        if resp.status_code == 200:
            print("[OK  ] GROQ ASR: Key 有效")
            return True
        if resp.status_code == 401:
            print("[FAIL] GROQ ASR: API Key 无效 (401)")
            return False
        print(f"[FAIL] GROQ ASR: HTTP {resp.status_code} {resp.text[:120]}")
        return False
    except Exception as e:
        print(f"[FAIL] GROQ ASR: {e}")
        return False

async def main():
    llm_cfg = get_llm_config()
    emb_cfg = get_embedding_config()
    llm_fp = llm_cfg.get("api_key", "")
    if llm_fp and len(llm_fp) > 8:
        print(f"  生效 LLM Key 指纹: {llm_fp[:4]}****{llm_fp[-4:]}")
    emb_fp = emb_cfg.get("api_key", "")
    if emb_fp and len(emb_fp) > 8:
        print(f"  生效 Embedding Key 指纹: {emb_fp[:4]}****{emb_fp[-4:]}")
    print("")

    results = []
    results.append(await probe("LLM 对话", test_llm_connection(llm_cfg)))
    results.append(await probe("Embedding 嵌入", test_embedding_connection(emb_cfg)))
    results.append(await probe_groq())
    print("")
    if all(results):
        print("=== 全部通过：Key 已同步到 Docker 且可用 ===")
    else:
        print("=== 存在失败项：请检查 .env 或网页「设置」中的 Key ===")
        sys.exit(1)

asyncio.run(main())
PY
