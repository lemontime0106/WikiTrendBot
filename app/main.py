from fastapi import FastAPI

app = FastAPI(
    title="WikiTrendBot API",
    version="0.1.0"
)

@app.get("/")
def root():
    return {"status": "ok"}