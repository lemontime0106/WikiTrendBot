from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.graph.trend_writer import _source_context


class PromptBudgetTests(unittest.TestCase):
    def test_research_context_respects_character_budget(self) -> None:
        sources = [
            {
                "title": f"공식 자료 {index}",
                "source": "example.com",
                "url": f"https://example.com/{index}",
                "content_excerpt": "근거 내용 " * 500,
                "fetch_status": "ok",
            }
            for index in range(10)
        ]

        with patch.dict(
            os.environ,
            {
                "CONTENT_MAX_RESEARCH_CONTEXT_CHARS": "1800",
                "CONTENT_MAX_RESEARCH_SOURCES_IN_PROMPT": "4",
            },
        ):
            context = _source_context(sources)

        self.assertLessEqual(len(context), 1800)
        self.assertIn("공식 자료 1", context)
        self.assertNotIn("공식 자료 5", context)


if __name__ == "__main__":
    unittest.main()
