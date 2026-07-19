from __future__ import annotations

import asyncio
import unittest

from fastapi import HTTPException

from app.main import publish_post
from app.service.approval_store import clear_approvals


class PublishGateTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_approvals()

    def tearDown(self) -> None:
        clear_approvals()

    def test_unapproved_article_is_rejected_before_tistory_automation(self) -> None:
        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                publish_post(
                    article_markdown="# 검사하지 않은 본문",
                    title="검사하지 않은 본문",
                    tags="",
                    image_slot_numbers=[],
                    image_files=[],
                )
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("품질 검사를 통과하지 않았습니다", context.exception.detail)


if __name__ == "__main__":
    unittest.main()
