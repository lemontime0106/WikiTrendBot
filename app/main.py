import asyncio
import sys

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from app.service.get_trend import get_trend_data

app = FastAPI()

@app.get("/")
def root():
    return {"status": "ok"}

@app.get("/trend")
async def get_trend():
    return await get_trend_data()