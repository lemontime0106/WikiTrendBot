from __future__ import annotations

import unittest

from app.service.approval_store import (
    approve_article,
    clear_approvals,
    get_article_approval,
)
from app.service.content_quality import QualityReport, article_hash


def _report(article: str, *, passed: bool) -> QualityReport:
    return QualityReport(
        passed=passed,
        score=100 if passed else 50,
        article_hash=article_hash(article),
        checks=[],
        blocking_reasons=[] if passed else ["차단"],
        warnings=[],
        metrics={},
    )


class ApprovalStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_approvals()

    def tearDown(self) -> None:
        clear_approvals()

    def test_only_exact_approved_article_is_available(self) -> None:
        article = "# 승인된 글"
        approve_article(article, _report(article, passed=True))

        self.assertIsNotNone(get_article_approval(article))
        self.assertIsNone(get_article_approval(article + "\n수정"))

    def test_failed_recheck_revokes_previous_approval(self) -> None:
        article = "# 다시 검사할 글"
        approve_article(article, _report(article, passed=True))
        approve_article(article, _report(article, passed=False))

        self.assertIsNone(get_article_approval(article))


if __name__ == "__main__":
    unittest.main()
