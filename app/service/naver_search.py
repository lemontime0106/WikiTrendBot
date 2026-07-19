from __future__ import annotations

from urllib.parse import quote_plus
from urllib.parse import urlparse

from playwright.async_api import async_playwright


def _build_search_context(search_results: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for index, item in enumerate(search_results, start=1):
        title = item.get("title", "").strip()
        snippet = item.get("snippet", "").strip()
        source = item.get("source", "").strip()
        url = item.get("url", "").strip()

        parts = [part for part in [title, snippet] if part]
        merged = " - ".join(parts)
        if source:
            merged = f"{merged} ({source})"
        if url:
            merged = f"{merged}\n   URL: {url}"
        if merged:
            lines.append(f"{index}. {merged}")

    return "\n".join(lines)


async def collect_naver_search_context(keyword: str) -> dict[str, object]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ko-KR",
        )

        try:
            title_selectors = [
                "div.fds-comps-right-image-text-title",
                "span.sds-comps-text-type-headline1",
                "a.news_tit",
                "a.title_link",
            ]
            combined = ", ".join(title_selectors)
            results: list[dict[str, str]] = []
            seen_titles: set[str] = set()
            seen_urls: set[str] = set()

            async def collect_query(query: str) -> None:
                url = f"https://search.naver.com/search.naver?query={quote_plus(query)}"
                await page.goto(url, timeout=15000)
                await page.wait_for_selector(combined, timeout=10000)

                for selector in title_selectors:
                    elements = await page.query_selector_all(selector)
                    for element in elements:
                        title = (await element.inner_text()).strip()
                        if not title or title in seen_titles:
                            continue

                        href = await element.get_attribute("href") or ""
                        if not href:
                            href = await element.evaluate(
                                """
                                (el) => {
                                  const anchor = el.closest('a') || el.querySelector('a');
                                  return anchor?.href || '';
                                }
                                """
                            )
                        href = str(href).strip()
                        if href and not href.startswith(("http://", "https://")):
                            href = ""
                        if href and href in seen_urls:
                            continue

                        snippet = ""
                        source = ""
                        container = await element.evaluate_handle(
                            "el => el.closest('article, li, div') ?? el"
                        )

                        snippet_selectors = [
                            ".news_dsc",
                            ".total_dsc",
                            ".fds-comps-right-image-text-content",
                            ".sds-comps-text-type-body1",
                            ".api_txt_lines",
                        ]
                        for snippet_selector in snippet_selectors:
                            snippet_element = await container.query_selector(snippet_selector)
                            if snippet_element:
                                snippet = (await snippet_element.inner_text()).strip()
                                if snippet:
                                    break

                        source_selectors = [
                            ".info_group",
                            ".sub",
                            ".source",
                            ".fds-collection-source",
                        ]
                        for source_selector in source_selectors:
                            source_element = await container.query_selector(source_selector)
                            if source_element:
                                raw = (await source_element.inner_text()).strip()
                                source = raw.split("\n")[0]
                                if source:
                                    break

                        if not source and href:
                            source = (urlparse(href).hostname or "").removeprefix("www.")

                        seen_titles.add(title)
                        if href:
                            seen_urls.add(href)
                        results.append(
                            {
                                "title": title,
                                "snippet": snippet,
                                "source": source,
                                "url": href,
                            }
                        )
                        if len(results) >= 10:
                            return

            queries = [keyword, f"{keyword} 공식 발표"]
            for query in queries:
                try:
                    await collect_query(query)
                except Exception:
                    if query == keyword and not results:
                        raise
                if len(results) >= 10:
                    break

            if not results:
                raise RuntimeError("네이버 검색 결과에서 요약 정보를 찾지 못했습니다.")

            return {
                "search_results": results,
                "search_context": _build_search_context(results),
            }

        except Exception as exc:
            if "timeout" in str(exc).lower():
                raise RuntimeError("네이버 검색 결과 로딩 시간이 초과되었습니다.") from exc
            raise

        finally:
            await browser.close()
