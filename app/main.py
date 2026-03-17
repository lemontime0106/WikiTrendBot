import asyncio
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from dotenv import load_dotenv
from fastapi import FastAPI
from app.service.get_trend import get_trend_data
from app.graph.trend_writer import run_trend_writer

load_dotenv()

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/trend")
async def get_trend():
    return await get_trend_data()


@app.get("/generate")
async def generate(keyword: str | None = None):
    """
    트렌드 키워드를 가져온 뒤 LLM으로 글을 생성합니다.

    - keyword를 주면 해당 키워드 1개로 작성
    - keyword가 없으면 트렌드 상위 키워드로 작성
    """
    out = await run_trend_writer(keyword=keyword)
    return {
        "selected_keywords": out.get("selected_keywords", []),
        "model": out.get("model"),
        "article_markdown": out.get("article_markdown"),
    }