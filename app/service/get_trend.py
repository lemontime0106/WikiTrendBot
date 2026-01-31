import asyncio
from playwright.async_api import async_playwright


async def get_trend_data():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="ko-KR"
        )

        # 페이지 진입
        await page.goto("https://namu.wiki/", timeout=15000)

        # DOM 구조 기반 실시간 검색어 추출
        trends = await page.evaluate("""
        () => {
            const results = [];

            // 실시간 검색어처럼 생긴 ul만 필터링
            const uls = Array.from(document.querySelectorAll("ul"))
                .filter(ul => ul.querySelectorAll("li > a > span").length >= 5);

            if (uls.length === 0) return results;

            const targetUl = uls[0];

            targetUl.querySelectorAll("li").forEach(li => {
                const span = li.querySelector("a > span");
                if (!span) return;

                const text = span.textContent?.trim();
                if (text && text.length <= 20) {
                    results.push(text);
                }
            });

            return results.slice(0, 10);
        }
        """)


        await browser.close()

        return {
            "count": len(trends),
            "trends": trends
        }