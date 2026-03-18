from __future__ import annotations

import asyncio
from urllib.parse import quote_plus


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


def _collect_naver_search_context_sync(keyword: str) -> dict[str, object]:
    try:
        from selenium import webdriver
        from selenium.common.exceptions import TimeoutException, WebDriverException
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:
        raise RuntimeError("selenium 패키지가 설치되어 있지 않습니다.") from exc

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=ko-KR")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(service=Service(), options=options)

    try:
        url = f"https://search.naver.com/search.naver?query={quote_plus(keyword)}"
        driver.get(url)

        wait = WebDriverWait(driver, 10)
        wait.until(
            EC.presence_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "div.fds-comps-right-image-text-title, a.news_tit, a.title_link, span.sds-comps-text-type-headline1",
                )
            )
        )

        results: list[dict[str, str]] = []
        selectors = [
            "div.fds-comps-right-image-text-title",
            "span.sds-comps-text-type-headline1",
            "a.news_tit",
            "a.title_link",
        ]

        seen_titles: set[str] = set()

        for selector in selectors:
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for element in elements:
                title = element.text.strip()
                if not title or title in seen_titles:
                    continue

                seen_titles.add(title)
                snippet = ""
                source = ""

                try:
                    container = element.find_element(
                        By.XPATH,
                        "./ancestor::*[self::div or self::li][1]",
                    )
                except WebDriverException:
                    container = element

                snippet_selectors = [
                    ".news_dsc",
                    ".total_dsc",
                    ".fds-comps-right-image-text-content",
                    ".sds-comps-text-type-body1",
                    ".api_txt_lines",
                ]
                for snippet_selector in snippet_selectors:
                    try:
                        snippet_element = container.find_element(By.CSS_SELECTOR, snippet_selector)
                        snippet = snippet_element.text.strip()
                        if snippet:
                            break
                    except WebDriverException:
                        continue

                source_selectors = [
                    ".info_group",
                    ".sub",
                    ".source",
                    ".fds-collection-source",
                ]
                for source_selector in source_selectors:
                    try:
                        source_element = container.find_element(By.CSS_SELECTOR, source_selector)
                        source = source_element.text.strip().split("\n")[0]
                        if source:
                            break
                    except WebDriverException:
                        continue

                results.append(
                    {
                        "title": title,
                        "snippet": snippet,
                        "source": source,
                    }
                )

                if len(results) >= 6:
                    search_context = _build_search_context(results)
                    return {
                        "search_results": results,
                        "search_context": search_context,
                    }

        if not results:
            raise RuntimeError("네이버 검색 결과에서 요약 정보를 찾지 못했습니다.")

        search_context = _build_search_context(results)
        return {
            "search_results": results,
            "search_context": search_context,
        }
    except TimeoutException as exc:
        raise RuntimeError("네이버 검색 결과 로딩 시간이 초과되었습니다.") from exc
    finally:
        driver.quit()


async def collect_naver_search_context(keyword: str) -> dict[str, object]:
    return await asyncio.to_thread(_collect_naver_search_context_sync, keyword)
