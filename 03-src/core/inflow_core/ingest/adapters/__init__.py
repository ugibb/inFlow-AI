"""Platform adapter package.

Each module in this package implements AbstractAdapter for a specific platform.
The registry (registry.py) maps URLs to the correct adapter instance.

Available adapters:
    wechat      — WeChat Official Account articles
    bilibili    — Bilibili videos
    xiaoyuzhou  — Xiaoyuzhou (podcast) episodes
    xhs         — Xiaohongshu notes
    douyin      — Douyin / TikTok videos
    youtube     — YouTube videos
    toutiao     — Toutiao articles
    juejin      — Juejin developer articles
    csdn        — CSDN developer articles
    upload      — Local file uploads (PDF, DOCX, EPUB, …)
    generic     — Fallback for any unrecognised URL
"""
