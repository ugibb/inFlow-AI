"""Podcast card renderer.

Produces a self-contained HTML file (suitable for headless screenshot) from a
ParsedContent record.  The pipeline:

  1. Build ``CardData`` from ParsedContent + optional raw metadata.
  2. Call LLM to extract the supplementary card fields
     (core_quote, optional_block, quotes, book, guest info).
  3. Render ``prompts/s4/podcast_card_template.j2`` with Jinja2.
  4. Write the rendered HTML to the output path and return it as a string.

Usage::

    from app.s4_compose.card_renderer import render_podcast_card

    html = await render_podcast_card(parsed_content, extra={"ep": "EP 69", ...})
    Path("out/card.html").write_text(html)
"""

from __future__ import annotations

import json
import re
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import get_settings
from app.core.utils.logger import get_logger
from app.s2_parse.schema import ParsedContent
from app.prompts import load_prompt

logger = get_logger("s4.card_renderer")

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_S4_DIR = _PROMPTS_DIR / "s4"

_PLATFORM_NAMES: dict[str, str] = {
    "xiaoyuzhou": "小宇宙",
    "xhs": "小红书",
    "wechat": "微信公众号",
    "bilibili": "哔哩哔哩",
}


def _card_screenshot_settings() -> tuple[int, int]:
    """(viewport_width_css, device_scale_factor) from config.py."""
    s = get_settings()
    return s.card_viewport_width, max(1, s.card_screenshot_scale)


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Guest:
    """A single participant (host or guest) in a podcast/interview."""
    name: str
    role: str = ""
    emoji: str = "🎤"
    is_host: bool = False
    stance: str = ""     # 立场标签，如"AI乐观派"，对辩论类内容有用


@dataclass
class CardData:
    """All fields consumed by podcast_card_template.j2."""

    # Header / hero
    source: str = ""          # "小宇宙" / "微信公众号" / …
    ep: str = ""              # "EP 69" / "Vol.12" / ""
    category: str = ""        # first tag or custom
    title: str = ""
    tags: list[str] = field(default_factory=list)
    guests: list[Guest] = field(default_factory=list)  # 1-4 people; host first with is_host=True
    duration_min: int | None = None
    reading_time: int = 5

    # Content
    core_quote: str = ""
    key_points: list[str] = field(default_factory=list)

    # Optional block (None = section hidden)
    optional_block: dict[str, Any] | None = None

    # Quotes (empty list = section hidden)
    quotes: list[str] = field(default_factory=list)

    # Footer
    book: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Guest helpers
# ─────────────────────────────────────────────────────────────────────────────

def _build_guests_list(
    llm_fields: dict,
    *,
    fallback_host_name: str = "主播",
    fallback_host_emoji: str = "🎙",
    fallback_guest_name: str | None = None,
    fallback_guest_role: str | None = None,
    fallback_guest_emoji: str | None = None,
) -> list[Guest]:
    """Build a Guest list from LLM-extracted fields.

    Prefers the new ``guests`` array format.  Falls back to the legacy
    ``guest_name / guest_role / guest_emoji`` fields combined with explicit
    fallback host values when the new format is absent.
    """
    raw = llm_fields.get("guests")
    if isinstance(raw, list) and raw:
        guests: list[Guest] = []
        for g in raw:
            if not isinstance(g, dict) or not g.get("name"):
                continue
            guests.append(Guest(
                name=g["name"],
                role=g.get("role") or "",
                emoji=g.get("emoji") or "🎤",
                is_host=bool(g.get("is_host", False)),
                stance=g.get("stance") or "",
            ))
        if guests:
            # Ensure host is first if flagged
            hosts = [g for g in guests if g.is_host]
            others = [g for g in guests if not g.is_host]
            return (hosts + others)[:4]

    # Legacy / fallback format
    guests = [Guest(
        name=fallback_host_name,
        role="主持人",
        emoji=fallback_host_emoji,
        is_host=True,
    )]
    gn = llm_fields.get("guest_name") or fallback_guest_name
    if gn:
        guests.append(Guest(
            name=gn,
            role=llm_fields.get("guest_role") or fallback_guest_role or "嘉宾",
            emoji=llm_fields.get("guest_emoji") or fallback_guest_emoji or "🎤",
            is_host=False,
        ))
    return guests


# ─────────────────────────────────────────────────────────────────────────────
# LLM extraction
# ─────────────────────────────────────────────────────────────────────────────

def _parse_llm_json(raw: str) -> dict:
    """Extract a JSON object from LLM output, tolerating surrounding text."""
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass
    # Attempt to find first {...} block
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return {}


async def _llm_extract_card_fields(
    parsed: ParsedContent,
    *,
    max_tokens: int = 2000,
) -> dict:
    """Call LLM to extract supplementary card fields from clean_content."""
    article = parsed.article
    prompt = load_prompt(
        "s4/card_extract_block",
        title=article.title,
        host_name=article.author or "主播",
        summary=article.summary[:800],
        clean_content=article.clean_content[:6000],
    )

    try:
        from app.core.shared.ai_service import llm_service
        from app.core.config_manager import get_llm_config
        cfg = get_llm_config()
        model_name = cfg.get("model", "deepseek-chat")
        raw_output = await llm_service._chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        logger.debug("[card_renderer] LLM extraction done | model=%s", model_name)
        return _parse_llm_json(raw_output)
    except Exception as exc:
        logger.warning("[card_renderer] LLM extraction failed: %s", exc)
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_card_data(
    parsed: ParsedContent,
    extra: dict | None,
    llm_fields: dict,
) -> CardData:
    """Merge ParsedContent + extra metadata + LLM-extracted fields into CardData."""
    extra = extra or {}
    article = parsed.article

    # Platform display name
    template_used = parsed.template_used or ""
    source = extra.get("source") or _PLATFORM_NAMES.get(template_used, template_used) or "播客"

    # Tags: use first tag as category
    tags = article.tags or []
    category = extra.get("category") or (tags[0] if tags else "")

    # Episode identifier (prefer caller-supplied, then try to parse from title)
    ep = extra.get("ep") or _extract_ep(article.title)

    # Core quote: prefer LLM extraction, fall back to first key_point or summary snippet
    core_quote = (
        llm_fields.get("core_quote")
        or (article.key_points[0] if article.key_points else "")
        or article.summary[:80]
    )

    # Quotes: at most 3, filter empty strings
    quotes = [q for q in (llm_fields.get("quotes") or []) if q.strip()][:3]

    # Optional block validation
    opt_raw = llm_fields.get("optional_block")
    optional_block = _validate_optional_block(opt_raw)

    guests = _build_guests_list(
        llm_fields,
        fallback_host_name=extra.get("host_name") or article.author or "主播",
        fallback_host_emoji=extra.get("host_emoji") or "🎙",
        fallback_guest_name=extra.get("guest_name"),
        fallback_guest_role=extra.get("guest_role"),
        fallback_guest_emoji=extra.get("guest_emoji"),
    )

    return CardData(
        source=source,
        ep=ep,
        category=category,
        title=article.title,
        tags=tags[:4],
        guests=guests,
        duration_min=extra.get("duration_min"),
        reading_time=article.reading_time or 5,
        core_quote=core_quote,
        key_points=article.key_points[:5],
        optional_block=optional_block,
        quotes=quotes,
        book=llm_fields.get("book") or extra.get("book"),
    )


def _extract_ep(title: str) -> str:
    """Try to extract episode number from title like '69.title' or 'EP69 title'."""
    if not title:
        return ""
    m = re.match(r"^(\d+)\.", title)
    if m:
        return f"EP {m.group(1)}"
    m = re.search(r"\bEP\s*(\d+)\b", title, re.IGNORECASE)
    if m:
        return f"EP {m.group(1)}"
    m = re.search(r"#(\d+)", title)
    if m:
        return f"#{m.group(1)}"
    return ""


_VALID_OPT_TYPES = {"list", "steps", "pills", "compare"}


def _validate_optional_block(raw: Any) -> dict | None:
    """Return validated optional_block dict or None if invalid/absent."""
    if not isinstance(raw, dict):
        return None
    if raw.get("type") not in _VALID_OPT_TYPES:
        return None
    # Must have a non-empty title
    if not raw.get("title"):
        return None
    block_type = raw["type"]
    # Each type requires either "items" or specific keys
    if block_type in ("list", "steps", "pills"):
        items = raw.get("items")
        if not isinstance(items, list) or not items:
            return None
    elif block_type == "compare":
        if not (raw.get("before_items") and raw.get("after_items")):
            return None
    return raw


# ─────────────────────────────────────────────────────────────────────────────
# Jinja2 renderer
# ─────────────────────────────────────────────────────────────────────────────

def _get_jinja_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_S4_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def _render_html(card: CardData) -> str:
    env = _get_jinja_env()
    template = env.get_template("podcast_card_template.j2")
    return template.render(
        source=card.source,
        ep=card.ep,
        category=card.category,
        title=card.title,
        tags=card.tags,
        guests=card.guests,
        duration_min=card.duration_min,
        reading_time=card.reading_time,
        core_quote=card.core_quote,
        key_points=card.key_points,
        optional_block=card.optional_block,
        quotes=card.quotes,
        book=card.book,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def render_podcast_card(
    parsed: ParsedContent,
    *,
    extra: dict | None = None,
    output_path: Path | str | None = None,
    skip_llm: bool = False,
) -> str:
    """Render a podcast card HTML from a ParsedContent record.

    Args:
        parsed:       The ParsedContent object (from s2 parse pipeline).
        extra:        Optional caller-supplied overrides / supplementary fields:
                        ep, source, category, host_name, host_emoji,
                        guest_name, guest_role, guest_emoji, duration_min, book.
        output_path:  If provided, write the rendered HTML to this path.
        skip_llm:     If True, skip the LLM extraction step (use only existing fields).

    Returns:
        Rendered HTML string.
    """
    # Step 1: LLM extraction
    llm_fields: dict = {}
    if not skip_llm and parsed.article.clean_content:
        llm_fields = await _llm_extract_card_fields(parsed)

    # Step 2: Build CardData
    card = _build_card_data(parsed, extra, llm_fields)

    # Step 3: Render
    html = _render_html(card)

    # Step 4: Persist (optional)
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        logger.info("[card_renderer] Written to %s", out)

    return html


async def _llm_extract_from_transcript(transcript: str) -> dict:
    """Call LLM to extract CardData-compatible JSON fields from raw ASR transcript.

    Limits input to 10,000 characters (first 7k + last 3k) to stay within context limits.
    """
    MAX_CHARS = 10_000
    if len(transcript) > MAX_CHARS:
        head = transcript[:7000]
        tail = transcript[-3000:]
        sampled = head + "\n\n…（中间内容省略）…\n\n" + tail
    else:
        sampled = transcript

    prompt = load_prompt("s4/card_extract_asr", transcript=sampled)

    try:
        from app.core.shared.ai_service import llm_service
        raw_output = await llm_service._chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000,
        )
        logger.debug("[card_renderer] ASR JSON extraction done")
        return _parse_llm_json(raw_output)
    except Exception as exc:
        logger.warning("[card_renderer] ASR extraction failed: %s", exc)
        return {}


def _build_card_data_from_asr(
    llm_fields: dict,
    duration_min: int | None,
    source: str = "播客",
) -> CardData:
    """Build CardData from LLM-extracted ASR fields."""
    tags = [t for t in (llm_fields.get("tags") or []) if str(t).strip()]
    category = llm_fields.get("category") or (tags[0] if tags else "")
    key_points = [p for p in (llm_fields.get("key_points") or []) if str(p).strip()][:5]
    quotes = [q for q in (llm_fields.get("quotes") or []) if str(q).strip()][:3]
    optional_block = _validate_optional_block(llm_fields.get("optional_block"))
    reading_time = max(3, min(len(key_points) * 2, 10))

    guests = _build_guests_list(
        llm_fields,
        fallback_host_name=llm_fields.get("host_name") or "主播",
        fallback_host_emoji="🎙",
    )

    return CardData(
        source=source,
        ep=llm_fields.get("ep") or "",
        category=category,
        title=llm_fields.get("title") or "",
        tags=tags[:4],
        guests=guests,
        duration_min=duration_min,
        reading_time=reading_time,
        core_quote=llm_fields.get("core_quote") or "",
        key_points=key_points,
        optional_block=optional_block,
        quotes=quotes,
        book=llm_fields.get("book") or None,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Prompt → HTML → PNG (WeChat bot push)
# ─────────────────────────────────────────────────────────────────────────────

_PROMPT_CARD_HTML = "s4/20250413-播客访谈记录生成网页Prompt"
_CONTENT_MAX_CHARS = 12_000


def _resolve_cards_dir(
    asr_file_path: str | None,
    parsed_file_path: str | None,
) -> Path:
    """Map 02_parse episode folder → parallel 03_display folder."""
    base = Path(parsed_file_path or asr_file_path or "").parent
    if not base.name:
        cards_dir = _S4_DIR / "cards"
    else:
        cards_dir = Path(str(base).replace("/02_parse/", "/03_display/", 1))
        if cards_dir == base:
            cards_dir = _S4_DIR / "cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    return cards_dir


def _sample_text(text: str, max_chars: int = _CONTENT_MAX_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    head = text[:8000]
    tail = text[-4000:]
    return head + "\n\n…（中间内容省略）…\n\n" + tail


def _platform_label(platform: str | None) -> str:
    return _PLATFORM_NAMES.get(platform or "", platform or "") or "内容"


def _build_prompt_content(
    *,
    asr_file_path: str | None,
    parsed_file_path: str | None,
    source_platform: str | None,
) -> str:
    """Assemble the user content block for the card HTML prompt."""
    import json as _json

    platform = _platform_label(source_platform)
    parts: list[str] = [f"来源平台：{platform}"]

    parsed_body = ""
    if parsed_file_path and Path(parsed_file_path).is_file():
        data = _json.loads(Path(parsed_file_path).read_text(encoding="utf-8"))
        art = data.get("article") or {}
        if art.get("title"):
            parts.append(f"标题：{art['title']}")
        if art.get("author"):
            parts.append(f"作者：{art['author']}")
        if art.get("summary"):
            parts.append(f"摘要：{art['summary']}")
        kps = [p for p in (art.get("key_points") or []) if str(p).strip()]
        if kps:
            parts.append("要点：\n" + "\n".join(f"- {p}" for p in kps[:8]))
        parsed_body = (art.get("clean_content") or art.get("plain_text") or "").strip()

    asr_text = ""
    duration_s = 0
    if asr_file_path and Path(asr_file_path).is_file():
        asr_path = Path(asr_file_path)
        if asr_path.suffix == ".txt" or asr_path.name.endswith("_asr.txt"):
            asr_text = asr_path.read_text(encoding="utf-8").strip()
        else:
            asr = _json.loads(asr_path.read_text(encoding="utf-8"))
            asr_text = (asr.get("text") or "").strip()
            duration_s = int(asr.get("duration") or 0)

    if parsed_body:
        parts.append("正文：\n" + _sample_text(parsed_body))
        return "\n\n".join(parts)

    if asr_text:
        if duration_s:
            parts.append(f"时长：约 {duration_s // 60} 分钟")
        parts.append("转录文本：\n" + _sample_text(asr_text))
        return "\n\n".join(parts)

    raise ValueError("No parsed_file_path or asr_file_path available for card render")


def _extract_html_from_llm(raw: str) -> str:
    """Pull a complete HTML document from LLM output."""
    text = raw.strip()
    fence = re.search(r"```(?:html)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    doc = re.search(r"(<!DOCTYPE[\s\S]*?</html>)", text, re.IGNORECASE)
    if doc:
        return doc.group(1).strip()
    if text.lstrip().lower().startswith(("<!doctype", "<html")):
        return text
    raise ValueError("LLM output does not contain a complete HTML document")


async def _llm_generate_card_html(content: str) -> str:
    """Load card prompt and inject content without str.format (CSS braces safe)."""
    path = _PROMPTS_DIR / f"{_PROMPT_CARD_HTML}.md"
    template = path.read_text(encoding="utf-8")
    if "{{content}}" in template:
        prompt = template.replace("{{content}}", content, 1)
    elif "{content}" in template:
        prompt = template.replace("{content}", content, 1)
    else:
        prompt = template.rstrip() + "\n\n待处理内容：\n" + content

    from app.core.shared.ai_service import llm_service
    raw = await llm_service._chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.35,
        max_tokens=16000,
    )
    return _extract_html_from_llm(raw)


def _read_png_dims(path: Path) -> tuple[int, int]:
    """Read PNG width/height from IHDR chunk (no external deps)."""
    with path.open("rb") as f:
        f.read(16)
        w, h = struct.unpack(">II", f.read(8))
    return w, h


def _format_png_meta(path: Path) -> str:
    size_kb = path.stat().st_size // 1024
    try:
        w, h = _read_png_dims(path)
        return f"{w}x{h}px, {size_kb}KB"
    except Exception:
        return f"{size_kb}KB"


async def _screenshot_html_to_png(
    html_path: Path,
    png_path: Path,
    serve_dir: Path,
    progress_cb: Callable[[str], None] | None = None,
) -> None:
    """Playwright full-page screenshot via local HTTP (CDN fonts).

    Layout width and scale come from ``config.py`` (card_viewport_width, card_screenshot_scale).
    """
    import http.server
    import socket
    import socketserver
    import threading

    from playwright.async_api import async_playwright

    viewport_w, scale = _card_screenshot_settings()

    def _find_free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    class _QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serve_dir), **kwargs)

        def log_message(self, fmt, *args):
            pass

    def _log(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)
        else:
            logger.info(msg)

    port = _find_free_port()
    httpd = socketserver.TCPServer(("127.0.0.1", port), _QuietHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    t0 = time.monotonic()
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(
                viewport={
                    "width": viewport_w,
                    "height": 1334,
                },
                device_scale_factor=scale,
            )
            url = f"http://127.0.0.1:{port}/{html_path.name}"
            await page.goto(url, wait_until="networkidle", timeout=45000)
            await page.evaluate(
                "typeof window.hideToolbar === 'function' && window.hideToolbar()"
            )
            await page.wait_for_timeout(1500)
            await page.screenshot(path=str(png_path), full_page=True, type="png")
            await browser.close()
    finally:
        httpd.shutdown()

    elapsed = time.monotonic() - t0
    _log(
        f"HTML→PNG 完成 / viewport={viewport_w}px scale={scale}x"
        f" / {_format_png_meta(png_path)} / {elapsed:.1f}s"
    )


async def screenshot_html_content(html_content: str) -> bytes:
    """Playwright full-page PNG from an HTML string (same engine as pipeline cards)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        html_path = tmp / "export.html"
        png_path = tmp / "export.png"
        html_path.write_text(html_content, encoding="utf-8")
        await _screenshot_html_to_png(html_path, png_path, tmp)
        return png_path.read_bytes()


async def render_card_png_for_job(
    job_id: str,
    *,
    asr_file_path: str | None = None,
    parsed_file_path: str | None = None,
    source_platform: str | None = None,
    progress_cb: Callable[[str], None] | None = None,
) -> str:
    """Render or reuse a精华卡 PNG for an ingest job (Prompt → HTML → Playwright).

    Supports audio (ASR transcript) and article (ParsedContent). If ``{job_id}.png``
    already exists under ``data/03_display/…``, returns that path without re-rendering.
    """
    cards_dir = _resolve_cards_dir(asr_file_path, parsed_file_path)
    html_path = cards_dir / f"{job_id}.html"
    png_path = cards_dir / f"{job_id}.png"
    viewport_w, scale = _card_screenshot_settings()
    min_width = viewport_w * scale

    def _log(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)
        else:
            logger.info(msg)

    if png_path.is_file() and png_path.stat().st_size > 0:
        try:
            w, _ = _read_png_dims(png_path)
            if w >= min_width:
                _log(f"复用已有 PNG {_format_png_meta(png_path)}")
                return str(png_path.resolve())
            _log(f"PNG 分辨率不足 ({w}px < {min_width}px)，重新渲染")
        except Exception:
            _log("PNG 缓存不可读，重新渲染")

    content = _build_prompt_content(
        asr_file_path=asr_file_path,
        parsed_file_path=parsed_file_path,
        source_platform=source_platform,
    )
    content_kb = len(content.encode("utf-8")) // 1024
    platform_part = f" / 平台={source_platform}" if source_platform else ""

    t_llm = time.monotonic()
    html_content = await _llm_generate_card_html(content)
    elapsed = time.monotonic() - t_llm
    html_path.write_text(html_content, encoding="utf-8")
    _log(
        f"生成卡片 HTML 完成："
        f" / 输入={content_kb}KB"
        f" / viewport={viewport_w}px scale={scale}x"
        f" / {len(html_content)} 字 / {elapsed:.1f}s"
        # f" / {html_path.name}"
    )

    await _screenshot_html_to_png(html_path, png_path, cards_dir, progress_cb=progress_cb)
    return str(png_path.resolve())


async def render_podcast_card_from_asr(
    job_id: str,
    asr_file_path: str,
    *,
    source_platform: str | None = None,
) -> str:
    """Backward-compatible wrapper — delegates to :func:`render_card_png_for_job`."""
    return await render_card_png_for_job(
        job_id,
        asr_file_path=asr_file_path,
        source_platform=source_platform,
    )


def render_podcast_card_sync(
    parsed: ParsedContent,
    *,
    extra: dict | None = None,
    output_path: Path | str | None = None,
    card_data_override: CardData | None = None,
) -> str:
    """Synchronous render (no LLM call). Useful for local testing or preview.

    If ``card_data_override`` is provided, skips the build step entirely.
    """
    if card_data_override is not None:
        card = card_data_override
    else:
        card = _build_card_data(parsed, extra or {}, {})

    html = _render_html(card)

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")

    return html
