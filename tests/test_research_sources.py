from __future__ import annotations

import unittest

from app.service.research_sources import (
    _extract_readable_text,
    _validate_public_url,
    count_usable_sources,
)


class ResearchSourceTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_network_url_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            await _validate_public_url("http://127.0.0.1/admin")

    def test_html_extraction_ignores_script_and_navigation(self) -> None:
        title, description, excerpt = _extract_readable_text(
            """
            <html><head><title>공식 안내</title>
            <meta name="description" content="기능 변경 설명"></head>
            <body><nav>메뉴 문구</nav><main><h1>변경 내용</h1>
            <p>API 제한과 적용 날짜를 설명합니다.</p></main>
            <script>secret = true;</script></body></html>
            """
        )

        self.assertEqual(title, "공식 안내")
        self.assertEqual(description, "기능 변경 설명")
        self.assertIn("API 제한과 적용 날짜", excerpt)
        self.assertNotIn("메뉴 문구", excerpt)
        self.assertNotIn("secret", excerpt)

    def test_usable_source_count_needs_substantive_text(self) -> None:
        sources = [
            {"url": "https://a.example", "content_excerpt": "가" * 200},
            {"url": "https://b.example", "snippet": "나" * 80},
            {"url": "https://c.example", "snippet": "짧음"},
        ]

        self.assertEqual(count_usable_sources(sources), 2)


if __name__ == "__main__":
    unittest.main()
