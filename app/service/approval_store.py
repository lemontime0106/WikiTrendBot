from __future__ import annotations

import time
from dataclasses import dataclass

from app.service.content_quality import QualityReport, article_hash


@dataclass(frozen=True)
class Approval:
    report: QualityReport
    created_at: float


_APPROVALS: dict[str, Approval] = {}
_TTL_SECONDS = 6 * 60 * 60


def approve_article(article_markdown: str, report: QualityReport) -> None:
    key = article_hash(article_markdown)
    if not report.passed:
        _APPROVALS.pop(key, None)
        return
    if report.article_hash != key:
        raise ValueError("품질 보고서와 승인할 본문의 해시가 일치하지 않습니다.")
    _APPROVALS[key] = Approval(
        report=report,
        created_at=time.time(),
    )


def get_article_approval(article_markdown: str) -> QualityReport | None:
    now = time.time()
    expired = [
        key
        for key, approval in _APPROVALS.items()
        if now - approval.created_at > _TTL_SECONDS
    ]
    for key in expired:
        _APPROVALS.pop(key, None)

    approval = _APPROVALS.get(article_hash(article_markdown))
    return approval.report if approval else None


def clear_approvals() -> None:
    _APPROVALS.clear()
