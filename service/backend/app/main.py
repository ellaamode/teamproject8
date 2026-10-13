"""금융규제통합조회 조회 API (읽기 전용).

  uvicorn app.main:app --port 8000      → http://127.0.0.1:8000/docs
환경변수: DATABASE_URL(api_reader 계정), ALLOWED_ORIGINS(쉼표 구분)

설계: 쓰기는 배치만 한다. API는 DB에서 읽어 JSON으로 돌려줄 뿐이라 무료 서버에서도 가볍다.
데이터는 하루 한 번 수집 때만 바뀌므로
  - 서버가 같은 요청의 응답을 메모리에 기억해 두고 다시 쓴다 (DB가 멀리 있어 질의마다 왕복 시간이 크다)
  - 서버가 켜지면 첫 화면들이 부르는 응답을 미리 만들어 둔다
  - 응답에 Cache-Control 을 붙여 브라우저 캐시도 활용한다.
"""
import os
import threading
import time
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .db import pool
from .routes import analysis, articles, collection, documents, feed, graph, laws, search, system

CACHE_TTL = 1800                       # 30분. 수집은 하루 한 번이라 이 정도 늦어도 괜찮다
CACHE_MAX = 600                        # 기억해 둘 응답 수 (무료 서버 메모리 512MB 안에서 충분히 작음)
NO_CACHE = {"/health", "/collection", "/docs", "/redoc", "/openapi.json"}   # 상태 확인용은 늘 최신으로
_cache: dict[str, tuple[float, bytes]] = {}
# 서버가 켜질 때 미리 만들어 둘 응답 (화면이 처음 부르는 것들, 화면이 쓰는 주소 그대로)
WARM = ["/laws", "/analysis", "/feed?days=120&limit=200", "/feed?days=3&limit=200",
        "/guidance?status=expiring&within=60", "/guidance?status=notice&within=60", "/guidance?status=active&within=60",
        "/laws/fscma/toc", "/laws/fx/toc", "/laws/bank/toc", "/laws/ins/toc", "/laws/efta/toc"]


def _key(path: str, query: str) -> str:
    """같은 요청이면 쿼리 순서가 달라도 같은 열쇠가 되게 정렬한다."""
    parts = sorted(p for p in query.split("&") if p)
    return path + ("?" + "&".join(parts) if parts else "")


def _warm():
    port = os.environ.get("PORT", "8000")
    time.sleep(2)                                    # 서버가 요청을 받을 수 있을 때까지 잠깐 기다림
    for path in WARM:
        try:
            requests.get(f"http://127.0.0.1:{port}{path}", timeout=60)
        except Exception:
            pass                                     # 미리 만들기는 실패해도 서비스에는 영향 없음


@asynccontextmanager
async def lifespan(_):
    pool.open()
    if os.environ.get("WARM_CACHE", "1") == "1":
        threading.Thread(target=_warm, daemon=True).start()
    yield
    pool.close()


app = FastAPI(title="금융규제통합조회 API", version="1.0",
              description="조문을 중심으로 법령·해석·비조치의견·행정지도를 연결해 조회하는 읽기 전용 API",
              lifespan=lifespan)


@app.middleware("http")
async def cache_headers(request: Request, call_next):
    resp = await call_next(request)
    if request.method == "GET" and resp.status_code == 200 and request.url.path != "/health":
        resp.headers["Cache-Control"] = "public, max-age=300"
    return resp


@app.middleware("http")
async def response_cache(request: Request, call_next):
    """같은 GET 요청은 서버 메모리에 기억해 둔 응답을 바로 돌려준다 (X-Cache: hit)."""
    if request.method != "GET" or request.url.path in NO_CACHE:
        return await call_next(request)
    key, now = _key(request.url.path, request.url.query), time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return Response(hit[1], media_type="application/json",
                        headers={"X-Cache": "hit", "Cache-Control": "public, max-age=300"})
    resp = await call_next(request)
    if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("application/json"):
        return resp
    body = b"".join([chunk async for chunk in resp.body_iterator])
    if len(_cache) >= CACHE_MAX:                     # 가득 차면 가장 먼저 만료될 것부터 비운다
        for k, _ in sorted(_cache.items(), key=lambda kv: kv[1][0])[: CACHE_MAX // 10]:
            _cache.pop(k, None)
    _cache[key] = (now + CACHE_TTL, body)
    headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
    return Response(body, status_code=200, headers=headers | {"X-Cache": "miss"}, media_type="application/json")


# CORS 는 가장 바깥에 둔다(마지막에 추가) → 기억해 둔 응답에도 허용 헤더가 붙는다
app.add_middleware(CORSMiddleware,
                   allow_origins=[o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:8765").split(",")
                                  if o.strip()],   # 끝의 '/'는 무시 (브라우저의 Origin 에는 '/'가 없다)
                   allow_methods=["GET"], allow_headers=["*"])


@app.exception_handler(Exception)
async def db_down(_, exc: Exception):
    import psycopg
    if isinstance(exc, (psycopg.OperationalError,)) or "PoolTimeout" in type(exc).__name__:
        return JSONResponse({"detail": "데이터베이스에 연결할 수 없습니다"}, status_code=503)
    return JSONResponse({"detail": "서버 오류"}, status_code=500)


for r in (system, laws, articles, graph, search, documents, feed, analysis, collection):
    app.include_router(r.router)
