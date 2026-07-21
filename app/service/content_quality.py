from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field


MARKDOWN_LINK_PATTERN = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")
BARE_URL_PATTERN = re.compile(r"(?<!\()(https?://[^\s<>)]+)")
IMAGE_PROMPT_PATTERN = re.compile(r"^\[여기에 들어갈 이미지 생성 프롬프트:\s*(.+?)\]\s*$", re.MULTILINE)
H1_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)
H2_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)

TEMPLATE_PHRASES = (
    "오늘의 한줄 요약",
    "검색을 통해 확인된",
    "네이버 검색 결과에서도",
    "검색 결과와 직접 사용해 본 경험을 바탕으로",
    "앞으로도 지속적인 관심을 부탁",
)

FIRSTHAND_CLAIM_TERMS = (
    "실사용",
    "직접 사용",
    "직접 써",
    "직접 비교",
    "사용 후기",
    "방문 후기",
    "직접 방문",
    "직접 테스트",
)

HIGH_RISK_TERMS = (
    "종목 추천",
    "ETF 추천",
    "주식 추천",
    "코인 추천",
    "대출 추천",
    "보험 추천",
    "투자 수익",
    "치료법",
    "의학적 조언",
    "법률 자문",
    "세무 상담",
)


class EditorialReview(BaseModel):
    passed: bool = Field(description="편집 검토를 통과했는지")
    score: int = Field(ge=0, le=100, description="전체 편집 품질 점수")
    topic_fit: bool = Field(description="사이트의 핵심 AI·IT 주제와 맞는지")
    risk_level: Literal["low", "medium", "high"]
    factual_support_score: int = Field(ge=0, le=100)
    originality_score: int = Field(ge=0, le=100)
    specificity_score: int = Field(ge=0, le=100)
    reader_value_score: int = Field(ge=0, le=100)
    title_honesty_score: int = Field(ge=0, le=100)
    source_quality_score: int = Field(ge=0, le=100)
    blocking_issues: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    revision_instructions: list[str] = Field(default_factory=list)
    recommended_tags: list[str] = Field(default_factory=list)
    summary: str = ""


class QualityCheck(BaseModel):
    code: str
    label: str
    passed: bool
    blocking: bool
    weight: int = Field(ge=0)
    detail: str


class QualityReport(BaseModel):
    passed: bool
    score: int = Field(ge=0, le=100)
    article_hash: str
    checks: list[QualityCheck]
    blocking_reasons: list[str]
    warnings: list[str]
    metrics: dict[str, Any]
    editorial_review: EditorialReview | None = None


@dataclass(frozen=True)
class ExistingPost:
    title: str
    text: str = ""
    url: str = ""


def article_hash(article_markdown: str) -> str:
    normalized = re.sub(r"\s+", " ", article_markdown).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_source_urls(article_markdown: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    candidates = MARKDOWN_LINK_PATTERN.findall(article_markdown)
    candidates.extend(BARE_URL_PATTERN.findall(article_markdown))

    for raw_url in candidates:
        url = raw_url.rstrip(".,;:")
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _source_domains(urls: Iterable[str]) -> set[str]:
    domains: set[str] = set()
    for url in urls:
        host = (urlparse(url).hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            domains.add(host)
    return domains


def _article_text(article_markdown: str) -> str:
    text = MARKDOWN_LINK_PATTERN.sub(lambda match: match.group(0).split("](", 1)[0].lstrip("["), article_markdown)
    text = IMAGE_PROMPT_PATTERN.sub("", text)
    text = re.sub(r"^#{1,3}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"\s+", " ", text).strip()


def _tokenize(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", value)
        if len(token) >= 2
    }


def _jaccard_similarity(left: str, right: str) -> float:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def find_most_similar_post(
    article_markdown: str,
    existing_posts: Iterable[ExistingPost | dict[str, str]],
) -> tuple[float, str, str]:
    title_match = H1_PATTERN.search(article_markdown)
    title = title_match.group(1).strip() if title_match else ""
    body = _article_text(article_markdown)
    best_score = 0.0
    best_title = ""
    best_url = ""

    for item in existing_posts:
        if isinstance(item, ExistingPost):
            existing_title = item.title
            existing_text = item.text
            existing_url = item.url
        else:
            existing_title = str(item.get("title", ""))
            existing_text = str(item.get("text", ""))
            existing_url = str(item.get("url", ""))

        title_score = SequenceMatcher(
            None,
            re.sub(r"\s+", "", title.lower()),
            re.sub(r"\s+", "", existing_title.lower()),
        ).ratio()
        body_score = _jaccard_similarity(body, existing_text) if existing_text else 0.0
        score = max(title_score, body_score)
        if score > best_score:
            best_score = score
            best_title = existing_title
            best_url = existing_url

    return best_score, best_title, best_url


def _build_check(
    *,
    code: str,
    label: str,
    passed: bool,
    blocking: bool,
    weight: int,
    success: str,
    failure: str,
) -> QualityCheck:
    return QualityCheck(
        code=code,
        label=label,
        passed=passed,
        blocking=blocking,
        weight=weight,
        detail=success if passed else failure,
    )


def evaluate_article(
    article_markdown: str,
    *,
    firsthand_notes: str = "",
    editorial_review: EditorialReview | None = None,
    topic_fit: bool = True,
    risk_level: str = "low",
    existing_posts: Iterable[ExistingPost | dict[str, str]] = (),
    allowed_source_urls: Iterable[str] | None = None,
) -> QualityReport:
    min_chars = int(os.getenv("CONTENT_MIN_ARTICLE_CHARS", "1800"))
    min_editorial_score = int(os.getenv("CONTENT_MIN_EDITORIAL_SCORE", "80"))
    duplicate_threshold = float(os.getenv("CONTENT_DUPLICATE_THRESHOLD", "0.72"))
    allow_high_risk = os.getenv("CONTENT_ALLOW_HIGH_RISK_TOPICS", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    text = _article_text(article_markdown)
    title_matches = H1_PATTERN.findall(article_markdown)
    h2_count = len(H2_PATTERN.findall(article_markdown))
    source_urls = extract_source_urls(article_markdown)
    source_domains = _source_domains(source_urls)
    allowed_urls = (
        {url.strip() for url in allowed_source_urls if url.strip()}
        if allowed_source_urls is not None
        else None
    )
    unapproved_source_urls = (
        [url for url in source_urls if url not in allowed_urls]
        if allowed_urls is not None
        else []
    )
    template_hits = [phrase for phrase in TEMPLATE_PHRASES if phrase in article_markdown]
    firsthand_claims = [term for term in FIRSTHAND_CLAIM_TERMS if term in article_markdown]
    high_risk_hits = [term for term in HIGH_RISK_TERMS if term in article_markdown]
    has_reference_section = any(
        heading.strip() in {"참고자료", "출처", "근거 자료", "참고한 공식 자료"}
        for heading in H2_PATTERN.findall(article_markdown)
    )
    image_prompt_count = len(IMAGE_PROMPT_PATTERN.findall(article_markdown))
    duplicate_score, duplicate_title, duplicate_url = find_most_similar_post(
        article_markdown,
        existing_posts,
    )

    checks: list[QualityCheck] = [
        _build_check(
            code="topic_fit",
            label="사이트 주제 적합성",
            passed=topic_fit,
            blocking=True,
            weight=12,
            success="사이트의 AI·IT 핵심 주제와 맞습니다.",
            failure="사이트의 핵심 주제와 맞지 않습니다.",
        ),
        _build_check(
            code="title",
            label="제목 구조",
            passed=len(title_matches) == 1 and 12 <= len(title_matches[0].strip()) <= 70,
            blocking=True,
            weight=7,
            success="H1 제목이 하나이며 길이가 적절합니다.",
            failure="H1 제목은 정확히 하나이고 12~70자여야 합니다.",
        ),
        _build_check(
            code="substance",
            label="본문 충실도",
            passed=len(text) >= min_chars and h2_count >= 3,
            blocking=True,
            weight=12,
            success=f"본문 {len(text):,}자, H2 {h2_count}개입니다.",
            failure=f"본문은 최소 {min_chars:,}자이며 H2 소제목이 3개 이상이어야 합니다.",
        ),
        _build_check(
            code="source_allowlist",
            label="수집 출처만 사용",
            passed=not unapproved_source_urls,
            blocking=True,
            weight=8,
            success="조사 단계에서 확인한 URL만 사용했습니다.",
            failure=(
                "조사 목록에 없던 URL이 포함됐습니다: "
                + ", ".join(unapproved_source_urls[:3])
            ),
        ),
        _build_check(
            code="template_language",
            label="양산형 표현",
            passed=not template_hits,
            blocking=True,
            weight=7,
            success="반복적으로 사용하던 고정 문구가 없습니다.",
            failure=f"양산형으로 보일 수 있는 표현이 있습니다: {', '.join(template_hits)}",
        ),
        _build_check(
            code="firsthand_evidence",
            label="직접 경험 근거",
            passed=not firsthand_claims or len(firsthand_notes.strip()) >= 80,
            blocking=True,
            weight=12,
            success="직접 경험을 주장하지 않거나 충분한 근거 메모가 제공됐습니다.",
            failure="실사용·직접 비교·방문 후기를 주장하려면 80자 이상의 직접 경험 메모가 필요합니다.",
        ),
        _build_check(
            code="risk",
            label="고위험 주제",
            passed=allow_high_risk or (risk_level.lower() != "high" and not high_risk_hits),
            blocking=True,
            weight=8,
            success="기본 차단 대상인 금융·의료·법률 조언이 아닙니다.",
            failure="금융·의료·법률 등 고위험 조언은 기본 정책상 발행할 수 없습니다.",
        ),
        _build_check(
            code="duplicate",
            label="기존 글 중복",
            passed=duplicate_score < duplicate_threshold,
            blocking=True,
            weight=10,
            success=f"기존 글과의 최고 유사도는 {duplicate_score:.0%}입니다.",
            failure=(
                f"기존 글 '{duplicate_title}'과 유사도가 {duplicate_score:.0%}입니다."
                + (f" ({duplicate_url})" if duplicate_url else "")
            ),
        ),
        _build_check(
            code="image_slots",
            label="이미지 슬롯",
            passed=image_prompt_count <= 2,
            blocking=False,
            weight=2,
            success=f"이미지 슬롯이 {image_prompt_count}개입니다.",
            failure="이미지 슬롯은 최대 2개까지만 허용합니다.",
        ),
    ]

    if editorial_review is not None:
        editorial_passed = (
            editorial_review.passed
            and editorial_review.score >= min_editorial_score
            and not editorial_review.blocking_issues
            and not editorial_review.unsupported_claims
        )
        checks.append(
            _build_check(
                code="editorial_review",
                label="AI 편집 검수",
                passed=editorial_passed,
                blocking=True,
                weight=10,
                success=f"편집 검수 점수는 {editorial_review.score}점입니다.",
                failure=(
                    f"편집 검수 점수 {editorial_review.score}점 또는 해결되지 않은 문제가 있습니다."
                ),
            )
        )

    total_weight = sum(check.weight for check in checks)
    passed_weight = sum(check.weight for check in checks if check.passed)
    score = round((passed_weight / max(total_weight, 1)) * 100)
    blocking_reasons = [
        check.detail for check in checks if check.blocking and not check.passed
    ]
    warnings = [
        check.detail for check in checks if not check.blocking and not check.passed
    ]

    return QualityReport(
        passed=not blocking_reasons and score >= min_editorial_score,
        score=score,
        article_hash=article_hash(article_markdown),
        checks=checks,
        blocking_reasons=blocking_reasons,
        warnings=warnings,
        metrics={
            "text_chars": len(text),
            "h1_count": len(title_matches),
            "h2_count": h2_count,
            "source_count": len(source_urls),
            "source_domain_count": len(source_domains),
            "source_domains": sorted(source_domains),
            "has_reference_section": has_reference_section,
            "unapproved_source_urls": unapproved_source_urls,
            "template_phrases": template_hits,
            "firsthand_claims": firsthand_claims,
            "high_risk_terms": high_risk_hits,
            "image_prompt_count": image_prompt_count,
            "duplicate_similarity": round(duplicate_score, 3),
            "duplicate_title": duplicate_title,
            "duplicate_url": duplicate_url,
        },
        editorial_review=editorial_review,
    )
