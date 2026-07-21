import asyncio
import os
from pathlib import Path
import shutil
import tempfile
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from starlette.staticfiles import StaticFiles
from app.service.get_trend import get_trend_data
from app.graph.trend_writer import (
    ContentRejectedError,
    review_edited_article,
    run_trend_writer,
)
from app.service.approval_store import approve_article, get_article_approval
from app.service.content_quality import QualityReport
from app.service.planning_input import parse_planning_input
from app.service.tistory_publish import publish_to_tistory

load_dotenv()

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


class GenerateRequest(BaseModel):
    keyword: str
    user_purpose: str | None = None
    firsthand_notes: str | None = None


class QualityCheckRequest(BaseModel):
    article_markdown: str
    firsthand_notes: str | None = None


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=FileResponse)
def root():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="프론트 페이지를 찾을 수 없습니다.")
    return FileResponse(index_file)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    favicon_file = STATIC_DIR / "favicon.ico"
    if favicon_file.exists():
        return FileResponse(favicon_file)
    return Response(status_code=204)


@app.get("/trend")
async def get_trend():
    try:
        return await get_trend_data()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"트렌드 조회에 실패했습니다: {exc}") from exc


@app.get("/generate")
async def generate(keyword: str | None = None, user_purpose: str | None = None):
    if not keyword or not keyword.strip():
        raise HTTPException(status_code=400, detail="keyword 쿼리가 필요합니다.")
    parsed_input = parse_planning_input(keyword)
    selected_keyword = parsed_input.keyword
    if not selected_keyword:
        raise HTTPException(status_code=400, detail="입력에서 작성할 키워드를 찾지 못했습니다.")
    effective_purpose = (user_purpose or parsed_input.user_purpose).strip()
    try:
        out = await run_trend_writer(
            keyword=selected_keyword,
            user_purpose=effective_purpose,
            planning_brief=parsed_input.planning_brief,
        )
    except ContentRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"글 생성에 실패했습니다: {exc}") from exc
    article_markdown = out.get("article_markdown") or ""
    quality_data = out.get("quality_report") or {}
    if article_markdown and quality_data:
        report = QualityReport.model_validate(quality_data)
        approve_article(article_markdown, report)
    return {
        "selected_keyword": selected_keyword,
        "user_purpose": effective_purpose,
        "parsed_planning_row": parsed_input.selected_row,
        "model": out.get("model"),
        "reviewer_model": out.get("reviewer_model"),
        "search_results": out.get("search_results", []),
        "article_plan": out.get("article_plan", {}),
        "article_markdown": article_markdown,
        "image_prompts": out.get("image_prompts", []),
        "recommended_tags": out.get("recommended_tags", []),
        "quality_report": quality_data,
        "revision_count": out.get("revision_count", 0),
    }


@app.post("/generate")
async def generate_from_selection(payload: GenerateRequest):
    parsed_input = parse_planning_input(payload.keyword)
    keyword = parsed_input.keyword
    user_purpose = (payload.user_purpose or parsed_input.user_purpose).strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword 값이 비어 있습니다.")

    try:
        out = await run_trend_writer(
            keyword=keyword,
            user_purpose=user_purpose,
            planning_brief=parsed_input.planning_brief,
            firsthand_notes=payload.firsthand_notes,
        )
    except ContentRejectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"글 생성에 실패했습니다: {exc}") from exc
    article_markdown = out.get("article_markdown") or ""
    quality_data = out.get("quality_report") or {}
    if article_markdown and quality_data:
        report = QualityReport.model_validate(quality_data)
        approve_article(article_markdown, report)
    return {
        "selected_keyword": keyword,
        "user_purpose": user_purpose,
        "parsed_planning_row": parsed_input.selected_row,
        "model": out.get("model"),
        "reviewer_model": out.get("reviewer_model"),
        "search_results": out.get("search_results", []),
        "article_plan": out.get("article_plan", {}),
        "article_markdown": article_markdown,
        "image_prompts": out.get("image_prompts", []),
        "recommended_tags": out.get("recommended_tags", []),
        "quality_report": quality_data,
        "revision_count": out.get("revision_count", 0),
    }


@app.post("/quality-check")
async def quality_check(payload: QualityCheckRequest):
    article_markdown = payload.article_markdown.strip()
    if not article_markdown:
        raise HTTPException(status_code=400, detail="검사할 본문이 비어 있습니다.")
    try:
        report = await review_edited_article(
            article_markdown=article_markdown,
            firsthand_notes=(payload.firsthand_notes or "").strip(),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"품질 검사에 실패했습니다: {exc}") from exc
    approve_article(article_markdown, report)
    return report.model_dump()


@app.post("/publish")
async def publish_post(
    article_markdown: str = Form(...),
    title: str = Form(""),
    tags: str = Form(""),
    image_slot_numbers: list[int] = Form(default=[]),
    image_files: list[UploadFile] = File(default=[]),
):
    if not article_markdown.strip():
        raise HTTPException(status_code=400, detail="업로드할 본문이 비어 있습니다.")

    approval = get_article_approval(article_markdown)
    if approval is None or not approval.passed:
        raise HTTPException(
            status_code=400,
            detail="현재 본문은 품질 검사를 통과하지 않았습니다. 생성 또는 수정 후 품질 검사를 다시 실행하세요.",
        )

    blog_url = (os.getenv("TISTORY_BLOG_URL") or "").strip()
    if not blog_url:
        raise HTTPException(
            status_code=500,
            detail="TISTORY_BLOG_URL 환경변수가 설정되지 않았습니다.",
        )

    if len(image_slot_numbers) != len(image_files):
        raise HTTPException(status_code=400, detail="이미지 슬롯 정보와 업로드 파일 수가 맞지 않습니다.")

    temp_dir = Path(tempfile.mkdtemp(prefix="wikitrendbot-tistory-"))
    image_paths_by_slot: dict[int, Path] = {}

    try:
        for slot, upload in zip(image_slot_numbers, image_files):
            suffix = Path(upload.filename or "").suffix or ".png"
            target_path = temp_dir / f"slot-{slot}{suffix}"
            with target_path.open("wb") as file_obj:
                shutil.copyfileobj(upload.file, file_obj)
            image_paths_by_slot[slot] = target_path

        tag_list = [item.strip() for item in tags.split(",") if item.strip()]
        result = await publish_to_tistory(
            blog_url=blog_url,
            article_markdown=article_markdown,
            title=title,
            tags=tag_list,
            image_paths_by_slot=image_paths_by_slot,
        )
        status = result.get("status")
        message = (
            "티스토리 입력을 완료했습니다. 브라우저에서 최종 발행을 확인해 주세요."
            if status == "WAITING_FINAL_APPROVAL"
            else "티스토리 업로드를 완료했습니다."
        )
        return {
            "ok": True,
            "message": message,
            **result,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"티스토리 업로드에 실패했습니다: {exc}") from exc
    finally:
        for upload in image_files:
            await upload.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
