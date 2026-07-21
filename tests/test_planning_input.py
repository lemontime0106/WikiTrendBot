from __future__ import annotations

import unittest

from app.service.planning_input import parse_planning_input


class PlanningInputTests(unittest.TestCase):
    def test_plain_keyword_is_preserved(self) -> None:
        parsed = parse_planning_input("OpenAI Agents SDK 2026")

        self.assertEqual(parsed.keyword, "OpenAI Agents SDK 2026")
        self.assertEqual(parsed.selected_row, {})

    def test_perplexity_tsv_row_becomes_article_brief(self) -> None:
        raw = (
            "키워드\t유형\t최신성 근거·날짜\t검색 의도와 주요 독자\t추천 제목\t"
            "독자가 얻는 구체적 결과\t핵심 내용 5개 이상\t경쟁도·예상 트래픽\t"
            "직접 검증 필요 여부\t기존 글 중복도\t우선순위\n"
            "OpenAI Agents SDK 2026\t트렌드·이슈\t공식 업데이트 2026-04-15\t"
            "에이전트 개발 흐름을 이해하려는 개발자\tAgents SDK가 바뀐 이유\t"
            "새 구조를 이해\t파일 실행, 샌드박스, 메모리, MCP, 보안\t"
            "중간·높음\t불필요\t58\t94"
        )

        parsed = parse_planning_input(raw)

        self.assertEqual(parsed.keyword, "OpenAI Agents SDK 2026")
        self.assertIn("에이전트 개발 흐름", parsed.user_purpose)
        self.assertIn("파일 실행, 샌드박스", parsed.planning_brief)

    def test_highest_priority_markdown_row_is_selected(self) -> None:
        raw = """| 키워드 | 유형 | 추천 제목 | 우선순위 |
|---|---|---|---|
| 낮은 후보 | 정보성 검색 | 낮은 후보 제목 | 71 |
| 높은 후보 | 트렌드·이슈 | 높은 후보 제목 | 96 |
"""

        parsed = parse_planning_input(raw)

        self.assertEqual(parsed.keyword, "높은 후보")
        self.assertIn("높은 후보 제목", parsed.user_purpose)

    def test_line_break_inside_copied_tsv_row_is_recombined(self) -> None:
        raw = (
            "키워드\t유형\t최신성 근거·날짜\t검색 의도와 주요 독자\t추천 제목\t"
            "독자가 얻는 구체적 결과\t핵심 내용 5개 이상\t경쟁도·예상 트래픽\t"
            "직접 검증 필요 여부\t기존 글 중복도\t우선순위\n"
            "OpenAI Agents SDK 2026\t트렌드·이슈\t공식 업데이트 2026-04-15\n"
            "개발 흐름을 이해하려는 개발자\t추천 제목\t새 구조 이해\t"
            "파일, 코드, 메모리, MCP, 보안\t중간·높음\t불필요\t58\t94"
        )

        parsed = parse_planning_input(raw)

        self.assertEqual(parsed.keyword, "OpenAI Agents SDK 2026")
        self.assertIn("개발 흐름을 이해하려는 개발자", parsed.user_purpose)


if __name__ == "__main__":
    unittest.main()
