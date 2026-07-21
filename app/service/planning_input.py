from __future__ import annotations

import re
from dataclasses import dataclass, field


DEFAULT_COLUMNS = [
    "키워드",
    "유형",
    "최신성 근거·날짜",
    "검색 의도와 주요 독자",
    "추천 제목",
    "독자가 얻는 구체적 결과",
    "핵심 내용 5개 이상",
    "경쟁도·예상 트래픽",
    "직접 검증 필요 여부",
    "기존 글 중복도",
    "우선순위",
]


@dataclass(frozen=True)
class ParsedPlanningInput:
    keyword: str
    user_purpose: str = ""
    planning_brief: str = ""
    selected_row: dict[str, str] = field(default_factory=dict)


def _clean_cell(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned.strip("| ")


def _split_row(line: str, delimiter: str) -> list[str]:
    if delimiter == "|":
        line = line.strip().strip("|")
    return [_clean_cell(cell) for cell in line.split(delimiter)]


def _is_separator_row(cells: list[str]) -> bool:
    return bool(cells) and all(
        not cell or re.fullmatch(r":?-{3,}:?", cell) for cell in cells
    )


def _priority_value(row: dict[str, str]) -> int:
    raw = next(
        (
            value
            for key, value in row.items()
            if "우선순위" in key or "priority_score" in key.lower()
        ),
        "",
    )
    match = re.search(r"\d+(?:\.\d+)?", raw)
    return round(float(match.group(0))) if match else -1


def _purpose_from_row(row: dict[str, str]) -> str:
    parts: list[str] = []
    labels = (
        ("검색 의도와 주요 독자", "검색 의도와 독자"),
        ("독자가 얻는 구체적 결과", "독자 결과"),
        ("추천 제목", "추천 제목"),
        ("핵심 내용 5개 이상", "핵심 내용"),
        ("최신성 근거·날짜", "최신성 근거"),
        ("유형", "콘텐츠 유형"),
    )
    for key, label in labels:
        value = row.get(key, "").strip()
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts)


def parse_planning_input(raw_input: str) -> ParsedPlanningInput:
    raw = raw_input.strip()
    if not raw:
        return ParsedPlanningInput(keyword="")

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    delimiter = "\t" if any("\t" in line for line in lines) else "|"
    rows = [_split_row(line, delimiter) for line in lines if delimiter in line]
    rows = [cells for cells in rows if cells and not _is_separator_row(cells)]

    header_index = next(
        (
            index
            for index, cells in enumerate(rows)
            if any(cell == "키워드" for cell in cells)
        ),
        -1,
    )
    if header_index >= 0:
        headers = rows[header_index]
        raw_data_rows = rows[header_index + 1 :]
    elif rows:
        headers = DEFAULT_COLUMNS
        raw_data_rows = rows
    else:
        keyword = _clean_cell(lines[0]) if lines else raw
        return ParsedPlanningInput(keyword=keyword[:200])

    data_rows: list[list[str]] = []
    pending_cells: list[str] = []
    for cells in raw_data_rows:
        pending_cells.extend(cells)
        if len(pending_cells) >= len(headers):
            data_rows.append(pending_cells[: len(headers)])
            pending_cells = pending_cells[len(headers) :]
    if pending_cells:
        data_rows.append(pending_cells)

    parsed_rows: list[dict[str, str]] = []
    for cells in data_rows:
        if len(cells) < 2:
            continue
        row = {
            header: cells[index] if index < len(cells) else ""
            for index, header in enumerate(headers)
            if header
        }
        keyword = row.get("키워드", "").strip()
        if keyword and keyword != "키워드":
            parsed_rows.append(row)

    if not parsed_rows:
        keyword = _clean_cell(lines[-1]) if lines else raw
        return ParsedPlanningInput(keyword=keyword[:200])

    selected = max(parsed_rows, key=_priority_value)
    keyword = selected.get("키워드", "").strip()[:200]
    purpose = _purpose_from_row(selected)
    brief = "\n".join(
        f"{key}: {value}" for key, value in selected.items() if value.strip()
    )
    return ParsedPlanningInput(
        keyword=keyword,
        user_purpose=purpose,
        planning_brief=brief,
        selected_row=selected,
    )
