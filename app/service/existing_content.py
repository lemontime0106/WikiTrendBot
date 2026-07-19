from __future__ import annotations

import html
import re
import time
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import httpx

from app.service.content_quality import ExistingPost


_CACHE: dict[str, tuple[float, list[ExistingPost]]] = {}
_CACHE_TTL_SECONDS = 15 * 60


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


async def collect_existing_posts(blog_url: str, *, limit: int = 50) -> list[ExistingPost]:
    normalized = blog_url.strip().rstrip("/")
    if not normalized:
        return []

    cached = _CACHE.get(normalized)
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1][:]

    rss_url = urljoin(f"{normalized}/", "rss")
    try:
        async with httpx.AsyncClient(
            timeout=12,
            follow_redirects=True,
            headers={"User-Agent": "WikiTrendBot/1.0 content-quality-check"},
        ) as client:
            response = await client.get(rss_url)
            response.raise_for_status()
    except httpx.HTTPError:
        return []

    try:
        root = ElementTree.fromstring(response.text)
    except ElementTree.ParseError:
        return []

    posts: list[ExistingPost] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = _strip_html(item.findtext("description") or "")
        if not title:
            continue
        posts.append(
            ExistingPost(
                title=title,
                text=description[:6000],
                url=link,
            )
        )
        if len(posts) >= limit:
            break

    _CACHE[normalized] = (time.time(), posts)
    return posts[:]


def serialize_existing_posts(posts: list[ExistingPost]) -> list[dict[str, Any]]:
    return [
        {"title": post.title, "text": post.text, "url": post.url}
        for post in posts
    ]
