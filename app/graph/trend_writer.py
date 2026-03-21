from __future__ import annotations

import json
import os
from typing import Any, Optional, TypedDict

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langgraph.graph import END, StateGraph

from app.service.naver_search import collect_naver_search_context


class TrendWriterState(TypedDict, total=False):
    keyword: Optional[str]
    user_purpose: str
    search_context: str
    search_results: list[dict[str, str]]
    article_markdown: str
    recommended_tags: list[str]
    model: str


async def _openai_chat_completions(
    *,
    api_key: str,
    model: str,
    messages: list[BaseMessage],
    base_url: str = "https://api.openai.com/v1",
    temperature: float = 0.7,
) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            (
                {"role": "system", "content": m.content}
                if isinstance(m, SystemMessage)
                else {"role": "user", "content": m.content}
                if isinstance(m, HumanMessage)
                else {"role": "assistant", "content": m.content}
                if isinstance(m, AIMessage)
                else {"role": "user", "content": getattr(m, "content", str(m))}
            )
            for m in messages
        ],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


def _create_llm_runnable() -> Runnable:
    """
    우선순위:
    1) langchain_openai.ChatOpenAI (설치되어 있으면)
    2) langchain.chat_models.ChatOpenAI (구버전 호환, 설치되어 있으면)
    3) httpx 기반 OpenAI REST 폴백
    """

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    temperature = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))

    try:
        from langchain_openai import ChatOpenAI  # type: ignore

        return ChatOpenAI(model=model, temperature=temperature)
    except Exception:
        pass

    try:
        from langchain.chat_models import ChatOpenAI  # type: ignore

        return ChatOpenAI(model_name=model, temperature=temperature)
    except Exception:
        pass

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LLM 설정이 필요합니다. (1) langchain_openai 설치 또는 (2) OPENAI_API_KEY 환경변수를 설정하세요."
        )

    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    class _OpenAIRestRunnable(Runnable):
        async def ainvoke(self, input: Any, config: Any | None = None, **kwargs: Any) -> Any:
            if isinstance(input, list) and all(isinstance(m, BaseMessage) for m in input):
                messages = input
            else:
                raise TypeError("OpenAI REST 폴백은 message list 입력만 지원합니다.")
            text = await _openai_chat_completions(
                api_key=api_key,
                model=model,
                base_url=base_url,
                temperature=temperature,
                messages=messages,
            )
            return AIMessage(content=text)

    return _OpenAIRestRunnable()


def _normalize_tistory_text(content: str) -> str:
    cleaned = content.strip()
    replacements = [
        ("**", ""),
        ("__", ""),
        ("```", ""),
        ("`", ""),
    ]
    for old, new in replacements:
        cleaned = cleaned.replace(old, new)

    lines = [line.rstrip() for line in cleaned.splitlines()]
    return "\n".join(lines).strip()


async def node_collect_search_context(state: TrendWriterState) -> TrendWriterState:
    keyword = (state.get("keyword") or "").strip()
    if not keyword:
        raise RuntimeError("검색할 키워드가 비어 있습니다.")

    search_data = await collect_naver_search_context(keyword)
    return {
        "search_context": search_data["search_context"],
        "search_results": search_data["search_results"],
    }


async def node_generate_article(state: TrendWriterState) -> TrendWriterState:
    keyword = (state.get("keyword") or "").strip()
    if not keyword:
        raise RuntimeError("글 생성을 위한 키워드가 필요합니다.")
    user_purpose = (state.get("user_purpose") or "").strip()
    search_context = (state.get("search_context") or "").strip()
    if not search_context:
        raise RuntimeError("네이버 검색 컨텍스트를 가져오지 못했습니다.")

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "너는 한국어 블로그 에디터다. 제공된 검색 결과를 우선 근거로 삼아 자연스럽고 읽기 쉬운 정보형 블로그 글을 작성한다. "
                "과장되거나 확인 불가능한 허위 사실은 만들지 않으며, 키워드가 약어이거나 중의적이면 검색 결과에 나타난 실제 맥락을 최우선으로 따른다. "
                "문장 길이, 리듬, 연결 표현, 서술 방식이 매 단락 비슷하게 반복되지 않도록 사람 손글처럼 변주를 준다.",
            ),
            (
                "user",
                "아래 키워드와 네이버 검색 요약을 바탕으로 실제 블로그에 올릴 만한 글(마크다운)을 작성해줘.\n\n"
                "키워드: {keyword}\n\n"
                "사용자 목적/원하는 방향:\n{user_purpose}\n\n"
                "네이버 검색 요약:\n{search_context}\n\n"
                "요구사항:\n"
                "- 제목 1개(H1), 본문 소제목은 H2/H3까지만 사용\n"
                "- 도입은 검색 유입을 고려한 블로그 문체로 작성\n"
                "- 본문은 H2 소제목 3~4개로 구성\n"
                "- 내용은 검색 결과에 나온 현재 이슈와 맥락을 우선 반영\n"
                "- 사용자 목적이 비어 있지 않다면 글의 각도, 강조 포인트, 독자 대상에 자연스럽게 반영\n"
                "- 검색 결과에 보이는 주제와 다르게 임의 해석하지 말 것\n"
                "- WBC 같은 약어는 검색 결과가 가리키는 실제 주제를 따라 쓸 것\n"
                "- 검색 요약에 없는 세부 숫자, 일정, 규정, 전적, 인용문은 추측해서 쓰지 말 것\n"
                "- 사실이 불확실한 부분은 단정하지 말고 완곡하게 설명할 것\n"
                "- 글 안에 쿠팡, 쇼핑, 구매 유도 문구를 넣지 말 것\n"
                "- 티스토리용이므로 **굵게**, __강조__, 표, 코드블록 같은 마크다운 문법은 쓰지 말 것\n"
                "- 본문은 일반 문장과 줄바꿈 위주로 쓰고, 헤더 문법만 최소한으로 사용\n"
                "- 블로그 실제 게시를 고려해 본문 중간 2~3곳에 이미지 자리표시자를 삽입\n"
                "- 이미지 자리표시자는 반드시 한 줄 단독으로 [여기에 들어갈 이미지 생성 프롬프트: ...] 형식으로 작성\n"
                "- 각 이미지 프롬프트에는 장면 설명, 분위기, 구도, 조명, 사실적인 스타일 여부를 구체적으로 포함\n"
                "- 이미지 자리표시자는 관련 단락 바로 아래에 배치하고, 글 흐름을 끊지 않도록 자연스럽게 넣을 것\n"
                "- 내용은 개념 소개, 왜 지금 주목받는지, 알아둘 포인트를 포함\n"
                "- 결론에는 독자 행동을 유도하는 마무리 문장 포함\n"
                "- 마지막에 '오늘의 한줄 요약' 1줄\n"
                "- 전체 톤은 정보형 블로그 문체\n"
                "- 이모지 없이 깔끔한 문장으로 작성\n"
                "- 단락마다 같은 문장 길이, 같은 접속어, 같은 어미를 반복하지 말 것\n"
                "- 설명형 단락, 짧은 환기 문장, 정리형 문장을 섞어 호흡을 다양하게 만들 것\n"
                "- 1200~1800자 정도\n",
            ),
        ]
    )

    llm = _create_llm_runnable()
    purpose_text = user_purpose if user_purpose else "별도 요청 없음"
    messages = prompt.format_messages(
        keyword=keyword,
        user_purpose=purpose_text,
        search_context=search_context,
    )

    result = await llm.ainvoke(messages)
    content = getattr(result, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM 응답이 비어있습니다.")

    return {
        "article_markdown": _normalize_tistory_text(content),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    }

async def node_recommend_tags(state: TrendWriterState) -> TrendWriterState:
    keyword = (state.get("keyword") or "").strip()
    user_purpose = (state.get("user_purpose") or "").strip()
    search_context = (state.get("search_context") or "").strip()
    if not keyword or not search_context:
        raise RuntimeError("태그 추천을 위한 키워드 또는 검색 컨텍스트가 없습니다.")

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "너는 SEO 태그 추천 도우미다. 티스토리 블로그용 검색 유입 태그를 한국어로 추천한다.",
            ),
            (
                "user",
                "아래 키워드와 검색 요약을 바탕으로 티스토리 태그를 최소 10개 추천해줘.\n\n"
                "키워드: {keyword}\n\n"
                "사용자 목적/원하는 방향:\n{user_purpose}\n\n"
                "검색 요약:\n{search_context}\n\n"
                "규칙:\n"
                '- 결과는 반드시 JSON 배열 문자열 형식 예시 ["태그1", "태그2"]\n'
                "- 태그는 검색 유입을 고려해 구체 키워드와 확장 키워드를 섞기\n"
                "- 중복 없이 최소 10개, 최대 15개\n"
                "- 해시 기호(#) 없이 태그 텍스트만 작성\n",
            ),
        ]
    )

    llm = _create_llm_runnable()
    purpose_text = user_purpose if user_purpose else "별도 요청 없음"
    messages = prompt.format_messages(
        keyword=keyword,
        user_purpose=purpose_text,
        search_context=search_context,
    )
    result = await llm.ainvoke(messages)
    content = getattr(result, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("태그 추천 응답이 비어있습니다.")

    cleaned = content.strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = [
            line.strip("- ").strip().lstrip("#").strip()
            for line in cleaned.splitlines()
            if line.strip()
        ]

    tags = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        tag = item.strip().lstrip("#").strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)

    return {"recommended_tags": tags[:15]}


def build_trend_writer_graph() -> Any:
    g = StateGraph(TrendWriterState)
    g.add_node("collect_search_context", node_collect_search_context)
    g.add_node("generate_article", node_generate_article)
    g.add_node("recommend_tags", node_recommend_tags)

    g.set_entry_point("collect_search_context")
    g.add_edge("collect_search_context", "generate_article")
    g.add_edge("generate_article", "recommend_tags")
    g.add_edge("recommend_tags", END)

    return g.compile()


async def run_trend_writer(*, keyword: Optional[str] = None, user_purpose: Optional[str] = None) -> TrendWriterState:
    graph = build_trend_writer_graph()
    init_state: TrendWriterState = {"keyword": keyword, "user_purpose": (user_purpose or "").strip()}
    out: TrendWriterState = await graph.ainvoke(init_state)
    return out

