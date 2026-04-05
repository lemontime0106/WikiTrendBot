from __future__ import annotations

from urllib.parse import quote_plus

from playwright.async_api import async_playwright


def _build_search_context(search_results: list[dict[str, str]]) -> str:
    lines: list[str] = []
    for index, item in enumerate(search_results, start=1):
        title = item.get("title", "").strip()
        snippet = item.get("snippet", "").strip()
        source = item.get("source", "").strip()

        parts = [part for part in [title, snippet] if part]
        merged = " - ".join(parts)
        if source:
            merged = f"{merged} ({source})"
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
            url = f"https://search.naver.com/search.naver?query={quote_plus(keyword)}"
            await page.goto(url, timeout=15000)

            title_selectors = [
                "div.fds-comps-right-image-text-title",
                "span.sds-comps-text-type-headline1",
                "a.news_tit",
                "a.title_link",
            ]
            combined = ", ".join(title_selectors)
            await page.wait_for_selector(combined, timeout=10000)

            results: list[dict[str, str]] = []
            seen_titles: set[str] = set()

            for selector in title_selectors:
                elements = await page.query_selector_all(selector)
                for element in elements:
                    title = (await element.inner_text()).strip()
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)

                    snippet = ""
                    source = ""

                    # 가장 가까운 div/li 조상에서 snippet 탐색
                    container = await element.evaluate_handle(
                        "el => el.closest('div, li') ?? el"
                    )

                    snippet_selectors = [
                        ".news_dsc",
                        ".total_dsc",
                        ".fds-comps-right-image-text-content",
                        ".sds-comps-text-type-body1",
                        ".api_txt_lines",
                    ]
                    for ss in snippet_selectors:
                        el = await container.query_selector(ss)
                        if el:
                            snippet = (await el.inner_text()).strip()
                            if snippet:
                                break

                    source_selectors = [
                        ".info_group",
                        ".sub",
                        ".source",
                        ".fds-collection-source",
                    ]
                    for src_sel in source_selectors:
                        el = await container.query_selector(src_sel)
                        if el:
                            raw = (await el.inner_text()).strip()
                            source = raw.split("\n")[0]
                            if source:
                                break

                    results.append({"title": title, "snippet": snippet, "source": source})

                    if len(results) >= 6:
                        return {
                            "search_results": results,
                            "search_context": _build_search_context(results),
                        }

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
