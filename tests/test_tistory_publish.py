from __future__ import annotations

import unittest

from app.service.tistory_publish import (
    _expected_body_text,
    _markdown_body_to_html,
)


class TistoryMarkdownTests(unittest.TestCase):
    def test_markdown_links_become_safe_clickable_links(self) -> None:
        markdown = (
            "## 참고자료\n\n"
            "- [공식 문서](https://example.com/docs?x=1&y=2)\n"
            "본문의 [근거](https://example.org/source)를 확인합니다."
        )

        rendered = _markdown_body_to_html(markdown)

        self.assertIn('href="https://example.com/docs?x=1&amp;y=2"', rendered)
        self.assertIn('target="_blank"', rendered)
        self.assertIn('rel="noopener noreferrer"', rendered)
        self.assertIn("공식 문서", _expected_body_text(markdown))
        self.assertNotIn("https://example.com", _expected_body_text(markdown))


if __name__ == "__main__":
    unittest.main()
