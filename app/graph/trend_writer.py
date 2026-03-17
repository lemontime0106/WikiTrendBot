from __future__ import annotations

import os
from typing import Any, Literal, Optional, TypedDict

import httpx
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable
from langgraph.graph import END, StateGraph

from app.service.get_trend import get_trend_data


class TrendWriterState(TypedDict, total=False):
    keyword: Optional[str]
    trends: list[str]
    selected_keywords: list[str]
    article_markdown: str
    model: str


def _pick_keywords(trends: list[str], keyword: Optional[str], limit: int = 5) -> list[str]:
    if keyword:
        return [keyword]
    return trends[:limit]


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


async def node_fetch_trends(state: TrendWriterState) -> TrendWriterState:
    data = await get_trend_data()
    trends = [t for t in (data.get("trends") or []) if isinstance(t, str)]
    return {"trends": trends}


async def node_select_keywords(state: TrendWriterState) -> TrendWriterState:
    selected = _pick_keywords(state.get("trends", []), state.get("keyword"))
    return {"selected_keywords": selected}


async def node_generate_article(state: TrendWriterState) -> TrendWriterState:
    selected = state.get("selected_keywords") or []
    if not selected:
        raise RuntimeError("트렌드 키워드를 가져오지 못했습니다.")

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "너는 한국어로 트렌드를 바탕으로 읽기 좋은 글을 쓰는 작가다. 과장된 허위사실은 만들지 않는다.",
            ),
            (
                "user",
                "아래 키워드를 바탕으로 블로그 글(마크다운)을 작성해줘.\n\n"
                "키워드:\n{keywords}\n\n"
                "요구사항:\n"
                "- 제목 1개(H1)\n"
                "- 서론/본론/결론 구조\n"
                "- 각 키워드별로 1개씩 소제목(H2) 섹션을 만들기\n"
                "- 마지막에 '오늘의 한줄 요약' 1줄\n"
                "- 900~1400자 정도\n",
            ),
        ]
    )

    llm = _create_llm_runnable()
    keywords_md = "\n".join([f"- {k}" for k in selected])
    messages = prompt.format_messages(keywords=keywords_md)

    result = await llm.ainvoke(messages)
    content = getattr(result, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("LLM 응답이 비어있습니다.")

    return {
        "article_markdown": content.strip(),
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    }


def build_trend_writer_graph() -> Any:
    g = StateGraph(TrendWriterState)
    g.add_node("fetch_trends", node_fetch_trends)
    g.add_node("select_keywords", node_select_keywords)
    g.add_node("generate_article", node_generate_article)

    g.set_entry_point("fetch_trends")
    g.add_edge("fetch_trends", "select_keywords")
    g.add_edge("select_keywords", "generate_article")
    g.add_edge("generate_article", END)

    return g.compile()


async def run_trend_writer(*, keyword: Optional[str] = None) -> TrendWriterState:
    graph = build_trend_writer_graph()
    init_state: TrendWriterState = {"keyword": keyword}
    out: TrendWriterState = await graph.ainvoke(init_state)
    return out

