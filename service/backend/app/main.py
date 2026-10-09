"""금융규제통합조회 조회 API (읽기 전용).

  uvicorn app.main:app --port 8000      → http://127.0.0.1:8000/docs
환경변수: DATABASE_URL(api_reader 계정), ALLOWED_ORIGINS(쉼표 구분)

설계: 쓰기는 배치만 한다. API는 DB에서 읽어 JSON으로 돌려줄 뿐이라 무료 서버에서도 가볍다.
데이터가 하루 한 번 바뀌므로 응답에 Cache-Control 을 붙여 브라우저·CDN 캐시를 활용한다.
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .db import pool
from .routes import analysis, articles, collection, documents, feed, graph, laws, search, system


@asynccontextmanager
async def lifespan(_):
    pool.open()
    yield
    pool.close()


app = FastAPI(title="금융규제통합조회 API", version="1.0",
              description="조문을 중심으로 법령·해석·비조치의견·행정지도를 연결해 조회하는 읽기 전용 API",
              lifespan=lifespan)
app.add_middleware(CORSMiddleware,
                   allow_origins=[o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:8765").split(",")
                                  if o.strip()],   # 끝의 '/'는 무시 (브라우저의 Origin 에는 '/'가 없다)
                   allow_methods=["GET"], allow_headers=["*"])


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    resp = await call_next(request)
    if request.method == "GET" and resp.status_code == 200 and request.url.path != "/health":
        resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.exception_handler(Exception)
async def db_down(_, exc: Exception):
    import psycopg
    if isinstance(exc, (psycopg.OperationalError,)) or "PoolTimeout" in type(exc).__name__:
        return JSONResponse({"detail": "데이터베이스에 연결할 수 없습니다"}, status_code=503)
    return JSONResponse({"detail": "서버 오류"}, status_code=500)


for r in (system, laws, articles, graph, search, documents, feed, analysis, collection):
    app.include_router(r.router)
