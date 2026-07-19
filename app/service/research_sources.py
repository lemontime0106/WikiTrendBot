from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


_MAX_REDIRECTS = 3
_MAX_RESPONSE_BYTES = 1_500_000
_MAX_EXCERPT_CHARS = 6_000


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._title_depth = 0
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.description = ""

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = tag.lower()
        if normalized in {"script", "style", "svg", "noscript", "nav", "footer"}:
            self._ignored_depth += 1
        if normalized == "title":
            self._title_depth += 1
        if normalized == "meta":
            values = {key.lower(): value or "" for key, value in attrs}
            name = (values.get("name") or values.get("property") or "").lower()
            if name in {"description", "og:description"} and not self.description:
                self.description = values.get("content", "").strip()

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized == "title" and self._title_depth:
            self._title_depth -= 1
        if (
            normalized in {"script", "style", "svg", "noscript", "nav", "footer"}
            and self._ignored_depth
        ):
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        value = data.strip()
        if not value:
            return
        if self._title_depth:
            self.title_parts.append(value)
        if not self._ignored_depth:
            self.text_parts.append(value)


def _is_public_ip(raw_ip: str) -> bool:
    address = ipaddress.ip_address(raw_ip)
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


async def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("HTTP(S) 공개 URL만 허용됩니다.")
    if parsed.username or parsed.password:
        raise ValueError("인증 정보가 포함된 URL은 허용되지 않습니다.")

    try:
        literal_ip = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None:
        if not _is_public_ip(str(literal_ip)):
            raise ValueError("로컬 또는 사설 네트워크 URL은 허용되지 않습니다.")
        return

    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("출처 도메인의 주소를 확인할 수 없습니다.") from exc
    if not addresses or any(not _is_public_ip(item[4][0]) for item in addresses):
        raise ValueError("로컬 또는 사설 네트워크로 연결되는 URL은 허용되지 않습니다.")


def _extract_readable_text(raw_html: str) -> tuple[str, str, str]:
    parser = _ReadableHtmlParser()
    parser.feed(raw_html)
    parser.close()
    title = re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip()
    description = re.sub(r"\s+", " ", html.unescape(parser.description)).strip()
    text = re.sub(r"\s+", " ", " ".join(parser.text_parts)).strip()
    if title and text.startswith(title):
        text = text[len(title) :].lstrip()
    return title[:300], description[:800], text[:_MAX_EXCERPT_CHARS]


async def _fetch_source(
    client: httpx.AsyncClient,
    source: dict[str, str],
) -> dict[str, str]:
    enriched = dict(source)
    current_url = source.get("url", "").strip()
    if not current_url:
        enriched["fetch_status"] = "missing_url"
        return enriched

    try:
        for _ in range(_MAX_REDIRECTS + 1):
            await _validate_public_url(current_url)
            async with client.stream("GET", current_url) as response:
                if response.is_redirect:
                    location = response.headers.get("location", "").strip()
                    if not location:
                        raise ValueError("이동할 주소가 없는 리다이렉트입니다.")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" not in content_type and "text/plain" not in content_type:
                    raise ValueError("HTML 또는 일반 텍스트 출처만 읽을 수 있습니다.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        break
                encoding = response.encoding or "utf-8"
                raw_text = bytes(body).decode(encoding, errors="replace")

            enriched["url"] = current_url
            if "text/html" in content_type:
                title, description, excerpt = _extract_readable_text(raw_text)
            else:
                title = ""
                description = ""
                excerpt = re.sub(r"\s+", " ", raw_text).strip()[:_MAX_EXCERPT_CHARS]
            if title and not enriched.get("title", "").strip():
                enriched["title"] = title
            if description and not enriched.get("snippet", "").strip():
                enriched["snippet"] = description
            if not excerpt:
                raise ValueError("읽을 수 있는 본문이 없습니다.")
            enriched["content_excerpt"] = excerpt
            enriched["fetch_status"] = "ok"
            return enriched
        raise ValueError("리다이렉트 횟수가 너무 많습니다.")
    except (httpx.HTTPError, UnicodeError, ValueError) as exc:
        enriched["fetch_status"] = "failed"
        enriched["fetch_error"] = str(exc)[:240]
        return enriched


async def enrich_research_sources(
    sources: list[dict[str, str]],
    *,
    limit: int = 10,
) -> list[dict[str, str]]:
    semaphore = asyncio.Semaphore(4)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(15, connect=7),
        follow_redirects=False,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; WikiTrendBot/2.0; "
                "+https://github.com/content-quality-research)"
            ),
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1",
        },
    ) as client:

        async def fetch(source: dict[str, str]) -> dict[str, str]:
            async with semaphore:
                return await _fetch_source(client, source)

        enriched = await asyncio.gather(
            *(fetch(source) for source in sources[:limit]),
        )

    if len(sources) > limit:
        enriched.extend(dict(source) for source in sources[limit:])
    return list(enriched)


def count_usable_sources(sources: list[dict[str, Any]]) -> int:
    return sum(
        1
        for source in sources
        if source.get("url")
        and (
            len(str(source.get("content_excerpt", "")).strip()) >= 200
            or len(str(source.get("snippet", "")).strip()) >= 80
        )
    )
