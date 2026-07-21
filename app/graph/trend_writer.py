from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime
from typing import Any, Literal, Optional, TypeVar, TypedDict
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, ValidationError

from app.service.content_quality import (
    EditorialReview,
    QualityReport,
    evaluate_article,
    extract_source_urls,
)
from app.service.existing_content import collect_existing_posts, serialize_existing_posts
from app.service.naver_search import collect_naver_search_context
from app.service.research_sources import enrich_research_sources


class SupportedClaim(BaseModel):
    claim: str
    source_urls: list[str] = Field(default_factory=list)


class ArticlePlan(BaseModel):
    publishable: bool
    topic_fit: bool
    topic_category: str
    risk_level: Literal["low", "medium", "high"]
    requires_firsthand_evidence: bool
    focus: str
    audience: str
    reader_outcome: str
    unique_angle: str
    key_questions: list[str] = Field(default_factory=list)
    supported_claims: list[SupportedClaim] = Field(default_factory=list)
    claims_to_avoid: list[str] = Field(default_factory=list)
    rejection_reason: str = ""


class TrendWriterState(TypedDict, total=False):
    keyword: Optional[str]
    user_purpose: str
    planning_brief: str
    firsthand_notes: str
    search_context: str
    search_results: list[dict[str, str]]
    existing_posts: list[dict[str, str]]
    article_plan: dict[str, Any]
    article_markdown: str
    image_prompts: list[dict[str, str | int]]
    recommended_tags: list[str]
    editorial_review: dict[str, Any]
    quality_report: dict[str, Any]
    revision_count: int
    model: str
    reviewer_model: str


class ContentRejectedError(RuntimeError):
    """Raised when a topic or evidence package should not proceed to article generation."""


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def _writer_model() -> str:
    return os.getenv("OPENAI_WRITER_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5.4-mini")


def _reviewer_model() -> str:
    return os.getenv("OPENAI_REVIEW_MODEL") or _writer_model()


def _temperature_for_model(model: str) -> float | None:
    explicit = (os.getenv("OPENAI_TEMPERATURE") or "").strip()
    if explicit:
        return float(explicit)
    if model.lower().startswith(("gpt-5", "o1", "o3", "o4")):
        return None
    return 0.35


async def _openai_chat_completions(
    *,
    api_key: str,
    model: str,
    messages: list[BaseMessage],
    base_url: str = "https://api.openai.com/v1",
    temperature: float | None = None,
    max_output_tokens: int = 2600,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            (
                {"role": "system", "content": message.content}
                if isinstance(message, SystemMessage)
                else {"role": "user", "content": message.content}
                if isinstance(message, HumanMessage)
                else {"role": "assistant", "content": message.content}
                if isinstance(message, AIMessage)
                else {
                    "role": "user",
                    "content": getattr(message, "content", str(message)),
                }
            )
            for message in messages
        ],
    }
    if temperature is not None:
        payload["temperature"] = temperature
    payload["max_tokens"] = max_output_tokens

    async with httpx.AsyncClient(timeout=120) as client:
        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                break
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429 and attempt < 2:
                    try:
                        retry_after = float(exc.response.headers.get("retry-after", "10"))
                    except ValueError:
                        retry_after = 10
                    await asyncio.sleep(min(max(retry_after, 1), 30))
                    continue
                detail = exc.response.text.strip()
                if len(detail) > 500:
                    detail = detail[:500].rstrip() + "..."
                raise RuntimeError(
                    "LLM API 요청이 실패했습니다. "
                    f"status={exc.response.status_code}, body={detail or '응답 본문 없음'}"
                ) from exc
            except httpx.HTTPError as exc:
                raise RuntimeError(f"LLM API 연결에 실패했습니다: {exc}") from exc

    if response is None:
        raise RuntimeError("LLM API 응답을 받지 못했습니다.")

    data = response.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"LLM 응답 형식이 예상과 다릅니다: {data}") from exc


def _create_llm_runnable(model: str, *, max_output_tokens: int = 2600) -> Runnable:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    temperature = _temperature_for_model(model)
    use_rest_fallback = base_url != "https://api.openai.com/v1"

    if not use_rest_fallback:
        try:
            from langchain_openai import ChatOpenAI  # type: ignore

            kwargs: dict[str, Any] = {
                "model": model,
                "base_url": base_url,
                "timeout": 120,
                "max_retries": 2,
            }
            if api_key:
                kwargs["api_key"] = api_key
            if temperature is not None:
                kwargs["temperature"] = temperature
            configured_max_tokens = int(
                os.getenv("OPENAI_MAX_OUTPUT_TOKENS", str(max_output_tokens))
            )
            kwargs["max_tokens"] = min(max_output_tokens, configured_max_tokens)
            reasoning_effort = (os.getenv("OPENAI_REASONING_EFFORT") or "").strip()
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
            return ChatOpenAI(**kwargs)
        except Exception:
            pass

    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 환경변수를 설정해야 합니다.")

    class _OpenAIRestRunnable(Runnable):
        def invoke(self, input: Any, config: Any | None = None, **kwargs: Any) -> Any:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(self.ainvoke(input, config=config, **kwargs))
            raise RuntimeError("실행 중인 이벤트 루프에서는 invoke 대신 ainvoke를 사용해야 합니다.")

        async def ainvoke(
            self,
            input: Any,
            config: Any | None = None,
            **kwargs: Any,
        ) -> Any:
            if not (
                isinstance(input, list)
                and all(isinstance(message, BaseMessage) for message in input)
            ):
                raise TypeError("OpenAI REST 폴백은 message list 입력만 지원합니다.")
            text = await _openai_chat_completions(
                api_key=api_key,
                model=model,
                base_url=base_url,
                temperature=temperature,
                messages=input,
                max_output_tokens=min(
                    max_output_tokens,
                    int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", str(max_output_tokens))),
                ),
            )
            return AIMessage(content=text)

    return _OpenAIRestRunnable()


def _message_content(result: Any) -> str:
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                texts.append(block["text"])
        return "\n".join(texts)
    return ""


def _parse_json_model(content: str, schema: type[StructuredModel]) -> StructuredModel:
    cleaned = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    else:
        object_match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if object_match:
            cleaned = object_match.group(0)
    try:
        return schema.model_validate_json(cleaned)
    except ValidationError as exc:
        raise RuntimeError(f"구조화된 LLM 응답 검증에 실패했습니다: {exc}") from exc


async def _invoke_structured(
    *,
    model: str,
    messages: list[BaseMessage],
    schema: type[StructuredModel],
) -> StructuredModel:
    llm = _create_llm_runnable(model, max_output_tokens=1000)
    structured_method = getattr(llm, "with_structured_output", None)
    if callable(structured_method):
        for method in ("json_schema", "function_calling"):
            try:
                structured_llm = structured_method(schema, method=method)
                result = await structured_llm.ainvoke(messages)
                if isinstance(result, schema):
                    return result
                return schema.model_validate(result)
            except Exception:
                continue

    fallback_messages = [
        *messages,
        HumanMessage(
            content=(
                "응답은 설명 없이 다음 JSON Schema를 만족하는 JSON 객체 하나만 출력하세요.\n"
                + json.dumps(schema.model_json_schema(), ensure_ascii=False)
            )
        ),
    ]
    result = await llm.ainvoke(fallback_messages)
    content = _message_content(result)
    if not content.strip():
        raise RuntimeError("구조화된 LLM 응답이 비어 있습니다.")
    return _parse_json_model(content, schema)


def _normalize_tistory_text(content: str) -> str:
    cleaned = content.strip()
    for old in ("**", "__", "```", "`"):
        cleaned = cleaned.replace(old, "")
    lines = [line.rstrip() for line in cleaned.splitlines()]
    return "\n".join(lines).strip()


def _extract_image_prompts(content: str) -> list[dict[str, str | int]]:
    pattern = re.compile(r"^\[여기에 들어갈 이미지 생성 프롬프트:\s*(.+?)\]\s*$")
    prompts: list[dict[str, str | int]] = []
    for line_index, raw_line in enumerate(content.splitlines(), start=1):
        match = pattern.match(raw_line.strip())
        if not match:
            continue
        prompts.append(
            {
                "slot": len(prompts) + 1,
                "prompt": match.group(1).strip(),
                "placeholder": raw_line.strip(),
                "line": line_index,
            }
        )
    return prompts


def _source_context(search_results: list[dict[str, str]]) -> str:
    max_chars = max(
        1200,
        int(os.getenv("CONTENT_MAX_RESEARCH_CONTEXT_CHARS", "2600")),
    )
    max_sources = max(1, int(os.getenv("CONTENT_MAX_RESEARCH_SOURCES_IN_PROMPT", "4")))
    lines: list[str] = []
    used_chars = 0
    for index, source in enumerate(search_results[:max_sources], start=1):
        title = source.get("title", "").strip() or "제목 없음"
        publisher = source.get("source", "").strip() or "발행처 미상"
        snippet = source.get("snippet", "").strip() or "요약 없음"
        url = source.get("url", "").strip() or "URL 없음"
        excerpt = source.get("content_excerpt", "").strip()
        fetch_status = source.get("fetch_status", "").strip()
        evidence = excerpt[:450] if excerpt else snippet[:450]
        block = (
            f"[자료 {index}]\n제목: {title}\n발행처: {publisher}\nURL: {url}\n"
            f"원문 수집 상태: {fetch_status or '검색 요약만 사용'}\n"
            f"확인 가능한 내용: {evidence}"
        )
        remaining = max_chars - used_chars
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[:remaining].rstrip()
        lines.append(block)
        used_chars += len(block) + 2
    return "\n\n".join(lines)


async def node_collect_search_context(state: TrendWriterState) -> TrendWriterState:
    keyword = (state.get("keyword") or "").strip()
    if not keyword:
        raise RuntimeError("검색할 키워드가 비어 있습니다.")

    try:
        search_data = await collect_naver_search_context(keyword)
        search_results = list(search_data["search_results"])
    except RuntimeError:
        search_results = []
    search_results = await enrich_research_sources(search_results)
    blog_url = (os.getenv("TISTORY_BLOG_URL") or "").strip()
    existing_posts = await collect_existing_posts(blog_url) if blog_url else []
    planning_brief = (state.get("planning_brief") or "").strip()
    planning_brief = planning_brief[
        : max(500, int(os.getenv("CONTENT_MAX_PLANNING_BRIEF_CHARS", "1200")))
    ]
    search_context = _source_context(search_results)
    if planning_brief:
        search_context = (
            f"{search_context}\n\n[퍼플렉시티 기획 참고]\n{planning_brief}"
            if search_context
            else f"[퍼플렉시티 기획 참고]\n{planning_brief}"
        )
    return {
        "search_context": search_context,
        "search_results": search_results,
        "existing_posts": serialize_existing_posts(existing_posts),
    }


async def node_plan_article(state: TrendWriterState) -> TrendWriterState:
    keyword = (state.get("keyword") or "").strip()
    user_purpose = (state.get("user_purpose") or "").strip()
    firsthand_notes = (state.get("firsthand_notes") or "").strip()
    search_results = state.get("search_results", [])
    search_context = (state.get("search_context") or "").strip()
    site_focus = os.getenv(
        "CONTENT_SITE_FOCUS",
        "AI 도구 실험, 업무 자동화, 1인 개발·SaaS, AI 산업·정책",
    )
    current_date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "당신은 광고 수익화를 노린 양산형 글을 차단하는 한국어 콘텐츠 기획 편집자입니다. "
                "검색 순위가 아니라 독자 효용, 사실 근거, 사이트 전문성, 제목의 정직성을 우선합니다. "
                "제공된 자료에 없는 사실은 계획에 포함하지 않습니다.",
            ),
            (
                "user",
                "다음 자료로 고품질 블로그 글을 기획할 수 있는지 판정하고 ArticlePlan 스키마로 응답하세요.\n\n"
                "현재 날짜: {current_date}\n"
                "사이트 핵심 분야: {site_focus}\n"
                "키워드: {keyword}\n"
                "사용자가 원하는 방향: {user_purpose}\n"
                "사용자의 직접 경험·검증 메모:\n{firsthand_notes}\n\n"
                "수집 자료:\n{search_context}\n\n"
                "판정 규칙:\n"
                "- 사이트 핵심 분야와 직접 관련이 없으면 topic_fit=false, publishable=false\n"
                "- 금융 투자 추천, 보험·대출 추천, 의료·법률·세무 조언은 risk_level=high\n"
                "- 리뷰·추천·방문기·제품 비교는 직접 경험 메모가 있어야 함\n"
                "- supported_claims에는 수집 자료나 퍼플렉시티 기획에서 확인되는 주장만 포함\n"
                "- 실제 URL이 수집된 주장에만 source_urls를 넣고 URL이 없으면 빈 배열로 둘 것\n"
                "- 자료가 서로 충돌하거나 얕으면 발행 불가로 판정\n"
                "- unique_angle은 일반적인 정의 요약이 아니라 독자가 실행하거나 판단할 수 있는 구체적인 각도여야 함\n"
                "- 글을 읽은 독자가 무엇을 할 수 있게 되는지 reader_outcome에 명확히 작성\n",
            ),
        ]
    )
    messages = prompt.format_messages(
        current_date=current_date,
        site_focus=site_focus,
        keyword=keyword,
        user_purpose=user_purpose or "별도 요청 없음",
        firsthand_notes=firsthand_notes or "제공되지 않음",
        search_context=search_context,
    )
    plan = await _invoke_structured(
        model=_reviewer_model(),
        messages=messages,
        schema=ArticlePlan,
    )

    if not plan.publishable or not plan.topic_fit:
        raise ContentRejectedError(
            plan.rejection_reason
            or "사이트 핵심 분야와 맞지 않거나 근거가 부족해 글 생성을 중단했습니다."
        )
    if plan.requires_firsthand_evidence and len(firsthand_notes) < 80:
        raise ContentRejectedError(
            "이 주제는 실제 사용·측정이 필요한 리뷰 성격이라 자동 작성 대상에서 제외했습니다. "
            "공식 자료만으로 검증 가능한 정보형 키워드를 선택하세요."
        )
    if plan.risk_level.lower() == "high" and os.getenv(
        "CONTENT_ALLOW_HIGH_RISK_TOPICS", ""
    ).strip().lower() not in {"1", "true", "yes", "on"}:
        raise ContentRejectedError(
            "금융·의료·법률 등 고위험 조언 주제는 현재 발행 정책에서 차단됩니다."
        )
    allowed_urls = {
        item.get("url", "").strip()
        for item in search_results
        if item.get("url", "").strip()
    }
    planned_claims = [claim for claim in plan.supported_claims if claim.claim.strip()]
    planned_urls = {
        url.strip()
        for claim in planned_claims
        for url in claim.source_urls
        if url.strip()
    }
    if planned_urls - allowed_urls:
        raise ContentRejectedError(
            "기획안이 수집하지 않은 출처 URL을 사용했습니다. 자료를 다시 수집해 생성하세요."
        )
    if len(planned_claims) < 3:
        raise ContentRejectedError(
            "글을 지탱할 구체적인 핵심 내용이 부족합니다. 작성 가능한 핵심 내용이 3개 이상 필요합니다."
        )
    return {"article_plan": plan.model_dump()}


async def node_generate_article(state: TrendWriterState) -> TrendWriterState:
    keyword = (state.get("keyword") or "").strip()
    user_purpose = (state.get("user_purpose") or "").strip()
    firsthand_notes = (state.get("firsthand_notes") or "").strip()
    search_context = (state.get("search_context") or "").strip()
    plan = ArticlePlan.model_validate(state.get("article_plan", {}))
    current_date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "당신은 한국어 기술 블로그의 책임 작가입니다. 검색 노출을 위한 빈 문장을 늘리지 않고, "
                "제공된 출처와 사용자의 실제 경험만으로 독자가 실행 가능한 글을 작성합니다. "
                "자료에 없는 숫자·일정·사례·인용문·사용 경험을 만들지 않습니다.",
            ),
            (
                "user",
                "다음 기획과 자료를 바탕으로 티스토리 게시용 마크다운 글을 작성하세요.\n\n"
                "현재 날짜: {current_date}\n"
                "키워드: {keyword}\n"
                "사용자 요청: {user_purpose}\n"
                "직접 경험·검증 메모:\n{firsthand_notes}\n\n"
                "승인된 기획:\n{article_plan}\n\n"
                "근거 자료:\n{search_context}\n\n"
                "필수 규칙:\n"
                "- H1 제목은 정확히 하나, H2 소제목은 최소 3개\n"
                "- 제목은 본문이 실제로 입증하는 범위만 약속\n"
                "- 도입부에서 독자의 문제와 이 글을 읽고 얻는 결과를 구체적으로 제시\n"
                "- 단순 정의 요약보다 비교 기준, 판단 과정, 실행 단계, 한계 중 주제에 맞는 요소를 포함\n"
                "- 실제 URL이 수집된 통계·날짜·제품 기능·정책 주장은 마크다운 링크로 연결\n"
                "- 수집된 URL이 있을 때만 마지막에 ## 참고자료를 만들고 실제 URL만 나열\n"
                "- URL이 없다는 이유로 글 작성을 중단하거나 URL을 만들어 내지 말 것\n"
                "- 제공되지 않은 URL을 만들지 말 것\n"
                "- 직접 경험 메모가 없으면 실사용·직접 비교·직접 방문했다고 표현하지 말 것\n"
                "- '검색을 통해', '전문성 있어 보이는', '오늘의 한줄 요약' 같은 양산형 표현 금지\n"
                "- 결론은 상투적인 관심 요청 대신 독자가 취할 다음 행동과 판단 기준을 정리\n"
                "- 본문 목표 분량은 2,200~4,000자이며 근거 없는 분량 늘리기는 금지\n"
                "- 표, 코드블록, 굵은 글씨 문법은 사용하지 말고 헤더·문단·목록·링크만 사용\n"
                "- 이미지가 설명에 꼭 필요할 때만 한 줄짜리 이미지 슬롯을 최대 1개 사용\n"
                "- 이미지 슬롯 형식: [여기에 들어갈 이미지 생성 프롬프트: 구체적인 장면과 정보 목적]\n"
                "- AI 생성 장식 이미지보다 실제 캡처·도표가 필요한 위치를 우선 설명\n",
            ),
        ]
    )
    messages = prompt.format_messages(
        current_date=current_date,
        keyword=keyword,
        user_purpose=user_purpose or "별도 요청 없음",
        firsthand_notes=firsthand_notes or "제공되지 않음",
        article_plan=plan.model_dump_json(indent=2),
        search_context=search_context,
    )
    llm = _create_llm_runnable(_writer_model(), max_output_tokens=2600)
    result = await llm.ainvoke(messages)
    content = _message_content(result)
    if not content.strip():
        raise RuntimeError("LLM 글 생성 응답이 비어 있습니다.")
    article = _normalize_tistory_text(content)
    return {
        "article_markdown": article,
        "image_prompts": _extract_image_prompts(article),
        "model": _writer_model(),
        "reviewer_model": _reviewer_model(),
    }


async def _review_article(
    *,
    article_markdown: str,
    search_context: str,
    firsthand_notes: str,
) -> EditorialReview:
    site_focus = os.getenv(
        "CONTENT_SITE_FOCUS",
        "AI 도구 실험, 업무 자동화, 1인 개발·SaaS, AI 산업·정책",
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "당신은 게시 직전 글을 검수하는 엄격한 한국어 편집장입니다. "
                "문장이 매끄럽다는 이유만으로 통과시키지 말고 사실 근거, 독창적 가치, 구체성, "
                "독자 효용, 제목 정직성, 출처 품질을 각각 평가합니다.",
            ),
            (
                "user",
                "아래 글을 EditorialReview 스키마로 검수하세요.\n\n"
                "사이트 핵심 분야: {site_focus}\n"
                "사용자의 직접 경험·검증 메모:\n{firsthand_notes}\n\n"
                "허용된 근거 자료:\n{search_context}\n\n"
                "검수할 글:\n{article_markdown}\n\n"
                "검수 규칙:\n"
                "- 허용된 자료에서 확인할 수 없는 구체적 주장은 unsupported_claims에 기록\n"
                "- 퍼플렉시티 기획과 검색 요약에 일관되게 포함된 핵심 내용은 검토 근거로 사용할 수 있음\n"
                "- 다른 글에서도 볼 수 있는 일반론뿐이면 originality_score와 reader_value_score를 낮게 평가\n"
                "- 실사용·직접 비교를 주장하지만 경험 메모가 뒷받침하지 않으면 차단\n"
                "- 제목이 과장되거나 본문보다 넓은 약속을 하면 차단\n"
                "- 참고자료 링크가 있다면 본문의 핵심 주장과 실제로 연결되는지 평가\n"
                "- 출처 링크 개수가 적거나 없다는 이유만으로 차단하지 말 것\n"
                "- source_quality_score는 URL 개수가 아니라 제공된 기획·검색 자료와 글의 일치도로 평가\n"
                "- 사이트 핵심 분야와 맞지 않으면 topic_fit=false\n"
                "- 금융·의료·법률 조언이면 risk_level=high\n"
                "- blocking_issues 또는 unsupported_claims가 하나라도 있으면 passed=false\n"
                "- 80점 미만이면 passed=false\n"
                "- recommended_tags는 글에 실제 등장하는 핵심 개념만 5~8개 추천\n",
            ),
        ]
    )
    messages = prompt.format_messages(
        site_focus=site_focus,
        firsthand_notes=firsthand_notes or "제공되지 않음",
        search_context=search_context,
        article_markdown=article_markdown,
    )
    return await _invoke_structured(
        model=_reviewer_model(),
        messages=messages,
        schema=EditorialReview,
    )


async def _revise_article(
    *,
    article_markdown: str,
    search_context: str,
    firsthand_notes: str,
    review: EditorialReview,
    quality_report: QualityReport,
) -> str:
    instructions = [
        *review.revision_instructions,
        *review.blocking_issues,
        *quality_report.blocking_reasons,
        *quality_report.warnings,
    ]
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "당신은 근거가 부족한 글을 고치는 선임 편집자입니다. 기존 글의 유용한 부분은 보존하되, "
                "검수 지적을 모두 해결합니다. 새 사실이나 새 URL을 만들지 않습니다.",
            ),
            (
                "user",
                "아래 글을 수정하세요.\n\n"
                "수정 지시:\n{instructions}\n\n"
                "허용된 근거 자료:\n{search_context}\n\n"
                "직접 경험·검증 메모:\n{firsthand_notes}\n\n"
                "기존 글:\n{article_markdown}\n\n"
                "출력은 수정된 마크다운 글만 작성하세요. H1 하나와 H2 세 개 이상을 유지하세요. "
                "기존 글에 실제 출처 링크가 있을 때만 참고자료 구역을 유지하세요.",
            ),
        ]
    )
    instruction_text = (
        "\n".join(f"- {item}" for item in instructions if item)
        or "- 편집 품질을 전반적으로 높일 것"
    )[:1200]
    messages = prompt.format_messages(
        instructions=instruction_text,
        search_context=search_context,
        firsthand_notes=firsthand_notes or "제공되지 않음",
        article_markdown=article_markdown,
    )
    llm = _create_llm_runnable(_writer_model(), max_output_tokens=2600)
    result = await llm.ainvoke(messages)
    revised = _message_content(result)
    if not revised.strip():
        raise RuntimeError("LLM 수정 응답이 비어 있습니다.")
    return _normalize_tistory_text(revised)


def _unique_tags(items: list[str]) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in items:
        tag = raw_tag.strip().lstrip("#").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
    return tags[:8]


async def node_review_and_revise(state: TrendWriterState) -> TrendWriterState:
    article = (state.get("article_markdown") or "").strip()
    search_context = (state.get("search_context") or "").strip()
    firsthand_notes = (state.get("firsthand_notes") or "").strip()
    existing_posts = state.get("existing_posts", [])
    plan = ArticlePlan.model_validate(state.get("article_plan", {}))
    max_revisions = max(0, min(int(os.getenv("CONTENT_MAX_REVISION_ROUNDS", "1")), 2))

    review = await _review_article(
        article_markdown=article,
        search_context=search_context,
        firsthand_notes=firsthand_notes,
    )
    report = evaluate_article(
        article,
        firsthand_notes=firsthand_notes,
        editorial_review=review,
        topic_fit=plan.topic_fit and review.topic_fit,
        risk_level="high"
        if "high" in {plan.risk_level.lower(), review.risk_level.lower()}
        else plan.risk_level,
        existing_posts=existing_posts,
        allowed_source_urls=[
            item.get("url", "")
            for item in state.get("search_results", [])
            if item.get("url", "")
        ],
    )
    revision_count = 0

    if not report.passed and max_revisions:
        article = await _revise_article(
            article_markdown=article,
            search_context=search_context,
            firsthand_notes=firsthand_notes,
            review=review,
            quality_report=report,
        )
        revision_count = 1
        review = await _review_article(
            article_markdown=article,
            search_context=search_context,
            firsthand_notes=firsthand_notes,
        )
        report = evaluate_article(
            article,
            firsthand_notes=firsthand_notes,
            editorial_review=review,
            topic_fit=plan.topic_fit and review.topic_fit,
            risk_level="high"
            if "high" in {plan.risk_level.lower(), review.risk_level.lower()}
            else plan.risk_level,
            existing_posts=existing_posts,
            allowed_source_urls=[
                item.get("url", "")
                for item in state.get("search_results", [])
                if item.get("url", "")
            ],
        )

    return {
        "article_markdown": article,
        "image_prompts": _extract_image_prompts(article),
        "recommended_tags": _unique_tags(review.recommended_tags),
        "editorial_review": review.model_dump(),
        "quality_report": report.model_dump(),
        "revision_count": revision_count,
    }


def build_trend_writer_graph() -> Any:
    graph = StateGraph(TrendWriterState)
    graph.add_node("collect_search_context", node_collect_search_context)
    graph.add_node("plan_article", node_plan_article)
    graph.add_node("generate_article", node_generate_article)
    graph.add_node("review_and_revise", node_review_and_revise)

    graph.set_entry_point("collect_search_context")
    graph.add_edge("collect_search_context", "plan_article")
    graph.add_edge("plan_article", "generate_article")
    graph.add_edge("generate_article", "review_and_revise")
    graph.add_edge("review_and_revise", END)
    return graph.compile()


async def run_trend_writer(
    *,
    keyword: Optional[str] = None,
    user_purpose: Optional[str] = None,
    planning_brief: Optional[str] = None,
    firsthand_notes: Optional[str] = None,
) -> TrendWriterState:
    graph = build_trend_writer_graph()
    initial_state: TrendWriterState = {
        "keyword": keyword,
        "user_purpose": (user_purpose or "").strip(),
        "planning_brief": (planning_brief or "").strip(),
        "firsthand_notes": (firsthand_notes or "").strip(),
    }
    return await graph.ainvoke(initial_state)


async def review_edited_article(
    *,
    article_markdown: str,
    firsthand_notes: str = "",
) -> QualityReport:
    urls = extract_source_urls(article_markdown)
    search_results = [
        {
            "title": f"본문 참고자료 {index}",
            "snippet": "수정된 글 본문에 포함된 참고자료입니다.",
            "source": (urlparse(url).hostname or "").removeprefix("www."),
            "url": url,
        }
        for index, url in enumerate(urls, start=1)
    ]
    search_results = await enrich_research_sources(search_results)
    search_context = _source_context(search_results)
    review = await _review_article(
        article_markdown=article_markdown,
        search_context=search_context,
        firsthand_notes=firsthand_notes.strip(),
    )
    blog_url = (os.getenv("TISTORY_BLOG_URL") or "").strip()
    existing_posts = await collect_existing_posts(blog_url) if blog_url else []
    return evaluate_article(
        article_markdown,
        firsthand_notes=firsthand_notes,
        editorial_review=review,
        topic_fit=review.topic_fit,
        risk_level=review.risk_level,
        existing_posts=existing_posts,
    )
