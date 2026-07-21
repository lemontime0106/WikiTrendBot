from __future__ import annotations

import re
import unittest

from app.service.content_quality import (
    EditorialReview,
    ExistingPost,
    evaluate_article,
)


def _editorial_review(*, passed: bool = True) -> EditorialReview:
    return EditorialReview(
        passed=passed,
        score=92 if passed else 60,
        topic_fit=True,
        risk_level="low",
        factual_support_score=93,
        originality_score=88,
        specificity_score=91,
        reader_value_score=94,
        title_honesty_score=95,
        source_quality_score=90,
        blocking_issues=[] if passed else ["핵심 근거가 부족합니다."],
        unsupported_claims=[],
        revision_instructions=[],
        recommended_tags=["AI 자동화", "운영 기준"],
        summary="근거와 실행 기준이 연결된 글입니다.",
    )


def _long_article(extra: str = "") -> str:
    paragraph = (
        "자동화 도구를 도입할 때는 기능 목록보다 현재 업무에서 반복되는 입력과 출력, "
        "사람이 최종 확인해야 하는 지점, 실패했을 때 되돌리는 절차를 먼저 기록해야 한다. "
        "이 기준이 있으면 시연 화면의 인상에 기대지 않고 팀의 실제 병목과 도구의 역할을 연결할 수 있다. "
        "또한 같은 작업을 여러 번 측정해 처리 시간과 수정 횟수를 남기면 도입 전후의 차이를 설명할 수 있다. "
    )
    body = paragraph * 6
    return f"""# AI 자동화 도구 도입 전에 확인할 다섯 가지 운영 기준

새 도구를 고르는 문제는 기능 수를 세는 일이 아니라 실패 비용과 검증 책임을 정하는 일이다. 이 글은 작은 팀이 후보를 좁힐 때 바로 사용할 수 있는 판단 순서를 정리한다.

## 먼저 문제와 성공 조건을 숫자로 적는다

{body}

[OpenAI 공식 문서](https://platform.openai.com/docs)에서 제공 범위를 확인하고, 제품 소개 문구와 실제 API 제약을 구분한다.

## 근거가 있는 기능만 비교표에 남긴다

{body}

[Python 공식 문서](https://docs.python.org/3/)처럼 버전별 동작을 확인할 수 있는 원문을 기준으로 검증 항목을 만든다.

## 실패 시나리오와 사람의 검토 지점을 설계한다

{body}

권한과 배포 흐름은 [GitHub 공식 문서](https://docs.github.com/en)에서 현재 설정 방법을 확인한 뒤 팀 규칙에 맞게 정한다.

## 도입 여부를 결정하는 마지막 질문

도구가 시간을 줄이더라도 오류 확인 시간이 더 늘어난다면 자동화 범위를 좁혀야 한다. 일주일 단위의 작은 실험으로 시작하고, 재작업률과 중단 시간을 함께 기록하면 유지할 가치가 있는지 판단할 수 있다. {extra}

## 참고자료

- [OpenAI 공식 문서](https://platform.openai.com/docs)
- [Python 공식 문서](https://docs.python.org/3/)
- [GitHub 공식 문서](https://docs.github.com/en)
"""


class ContentQualityTests(unittest.TestCase):
    def test_well_supported_article_passes(self) -> None:
        report = evaluate_article(
            _long_article(),
            editorial_review=_editorial_review(),
        )

        self.assertTrue(report.passed)
        self.assertEqual(report.score, 100)
        self.assertEqual(report.metrics["source_count"], 3)
        self.assertGreaterEqual(report.metrics["text_chars"], 1800)

    def test_template_language_blocks_publication(self) -> None:
        report = evaluate_article(
            _long_article("오늘의 한줄 요약"),
            editorial_review=_editorial_review(),
        )

        self.assertFalse(report.passed)
        self.assertIn("오늘의 한줄 요약", report.metrics["template_phrases"])

    def test_firsthand_claim_requires_notes(self) -> None:
        report = evaluate_article(
            _long_article("이 도구를 직접 사용한 결과라고 단정한다."),
            editorial_review=_editorial_review(),
        )

        self.assertFalse(report.passed)
        failed_codes = {check.code for check in report.checks if not check.passed}
        self.assertIn("firsthand_evidence", failed_codes)

    def test_duplicate_title_blocks_publication(self) -> None:
        article = _long_article()
        report = evaluate_article(
            article,
            editorial_review=_editorial_review(),
            existing_posts=[
                ExistingPost(
                    title="AI 자동화 도구 도입 전에 확인할 다섯 가지 운영 기준",
                    text="다른 내용",
                    url="https://example.com/existing",
                )
            ],
        )

        self.assertFalse(report.passed)
        self.assertEqual(report.metrics["duplicate_similarity"], 1.0)

    def test_unresearched_source_url_blocks_publication(self) -> None:
        report = evaluate_article(
            _long_article(),
            editorial_review=_editorial_review(),
            allowed_source_urls=[
                "https://platform.openai.com/docs",
                "https://docs.python.org/3/",
            ],
        )

        self.assertFalse(report.passed)
        self.assertEqual(
            report.metrics["unapproved_source_urls"],
            ["https://docs.github.com/en"],
        )

    def test_article_without_source_links_can_pass(self) -> None:
        article = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", _long_article())
        article = article.split("## 참고자료", 1)[0].strip()

        report = evaluate_article(
            article,
            editorial_review=_editorial_review(),
            allowed_source_urls=[],
        )

        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["source_count"], 0)


if __name__ == "__main__":
    unittest.main()
