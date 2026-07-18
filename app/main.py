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
from app.graph.trend_writer import run_trend_writer
from app.service.tistory_publish import publish_to_tistory

load_dotenv()

app = FastAPI()
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


class GenerateRequest(BaseModel):
    keyword: str
    user_purpose: str | None = None


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
    try:
        out = await run_trend_writer(keyword=keyword, user_purpose=user_purpose)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"글 생성에 실패했습니다: {exc}") from exc
    return {
        "selected_keyword": keyword.strip(),
        "user_purpose": (user_purpose or "").strip(),
        "model": out.get("model"),
        "search_results": out.get("search_results", []),
        "article_markdown": out.get("article_markdown"),
        "image_prompts": out.get("image_prompts", []),
        "recommended_tags": out.get("recommended_tags", []),
    }


@app.post("/generate")
async def generate_from_selection(payload: GenerateRequest):
    keyword = payload.keyword.strip()
    user_purpose = (payload.user_purpose or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword 값이 비어 있습니다.")

    try:
        out = await run_trend_writer(keyword=keyword, user_purpose=user_purpose)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"글 생성에 실패했습니다: {exc}") from exc
    return {
        "selected_keyword": keyword,
        "user_purpose": user_purpose,
        "model": out.get("model"),
        "search_results": out.get("search_results", []),
        "article_markdown": out.get("article_markdown"),
        "image_prompts": out.get("image_prompts", []),
        "recommended_tags": out.get("recommended_tags", []),
    }


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
        return {
            "ok": True,
            "message": "티스토리 업로드를 완료했습니다.",
            **result,
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"티스토리 업로드에 실패했습니다: {exc}") from exc
    finally:
        for upload in image_files:
            await upload.close()
        shutil.rmtree(temp_dir, ignore_errors=True)
