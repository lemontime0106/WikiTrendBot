from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from app.graph.trend_writer import (
    ArticlePlan,
    _create_llm_runnable,
    _invoke_structured,
    _looks_like_truncated_json,
    _reasoning_effort_for_model,
    _source_context,
    _strict_json_schema,
    _structured_output_tokens,
)


class _FakeStructuredRunnable:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.calls = 0

    async def ainvoke(self, messages: object) -> AIMessage:
        self.calls += 1
        return AIMessage(content=next(self.responses))


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

    def test_structured_output_budget_has_safe_bounds(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_STRUCTURED_MAX_OUTPUT_TOKENS": "1000"},
        ):
            self.assertEqual(_structured_output_tokens(), 1200)

        with patch.dict(
            os.environ,
            {"OPENAI_STRUCTURED_MAX_OUTPUT_TOKENS": "9000"},
        ):
            self.assertEqual(_structured_output_tokens(), 2000)

    def test_gpt_oss_uses_low_reasoning_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _reasoning_effort_for_model("openai/gpt-oss-120b"),
                "low",
            )

    def test_strict_schema_requires_every_object_property(self) -> None:
        schema = _strict_json_schema(ArticlePlan)

        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertFalse(schema["additionalProperties"])
        supported_claim = schema["$defs"]["SupportedClaim"]
        self.assertEqual(
            set(supported_claim["required"]),
            set(supported_claim["properties"]),
        )
        self.assertFalse(supported_claim["additionalProperties"])

    def test_rest_fallback_sends_strict_schema_and_low_reasoning(self) -> None:
        complete = ArticlePlan(
            publishable=True,
            topic_fit=True,
            topic_category="AI",
            risk_level="low",
            requires_firsthand_evidence=False,
            focus="핵심 기능",
            audience="개발자",
            reader_outcome="변경점을 이해한다",
            unique_angle="실행 기준",
            key_questions=[],
            supported_claims=[],
            claims_to_avoid=[],
            rejection_reason="",
        ).model_dump_json()
        environment = {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": "https://api.groq.com/openai/v1",
        }

        with (
            patch.dict(os.environ, environment, clear=True),
            patch(
                "app.graph.trend_writer._openai_chat_completions",
                new_callable=AsyncMock,
                return_value=complete,
            ) as completion,
        ):
            llm = _create_llm_runnable(
                "openai/gpt-oss-120b",
                max_output_tokens=1600,
            )
            structured_llm = llm.with_structured_output(
                ArticlePlan,
                method="json_schema",
            )
            result = self.async_run(
                structured_llm.ainvoke([HumanMessage(content="기획")])
            )

        request = completion.await_args.kwargs
        self.assertTrue(result.publishable)
        self.assertEqual(request["reasoning_effort"], "low")
        self.assertTrue(request["response_format"]["json_schema"]["strict"])
        self.assertEqual(request["max_output_tokens"], 1600)

    def test_truncated_structured_json_is_retried_once(self) -> None:
        truncated = '{"publishable":true,"topic_fit":true,'
        complete = ArticlePlan(
            publishable=True,
            topic_fit=True,
            topic_category="AI",
            risk_level="low",
            requires_firsthand_evidence=False,
            focus="핵심 기능",
            audience="개발자",
            reader_outcome="변경점을 이해한다",
            unique_angle="실행 기준",
            key_questions=["무엇이 바뀌었나"],
            supported_claims=[
                {"claim": "주장 1", "source_urls": []},
                {"claim": "주장 2", "source_urls": []},
                {"claim": "주장 3", "source_urls": []},
            ],
            claims_to_avoid=[],
            rejection_reason="",
        ).model_dump_json()
        runnable = _FakeStructuredRunnable([truncated, complete])

        with patch(
            "app.graph.trend_writer._create_llm_runnable",
            return_value=runnable,
        ):
            result = self.async_run(
                _invoke_structured(
                    model="test-model",
                    messages=[HumanMessage(content="기획")],
                    schema=ArticlePlan,
                )
            )

        self.assertTrue(result.publishable)
        self.assertEqual(runnable.calls, 2)

    @staticmethod
    def async_run(coro: object) -> object:
        import asyncio

        return asyncio.run(coro)

    def test_truncated_json_detection(self) -> None:
        self.assertTrue(_looks_like_truncated_json('{"value":"잘린 응답'))
        self.assertFalse(_looks_like_truncated_json('{"value":"완성"}'))


if __name__ == "__main__":
    unittest.main()
