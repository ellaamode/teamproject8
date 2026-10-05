"""API 응답을 정적 JSON 으로 떠서 프론트(service/app/data)에 넣는다.

  python -m tools.export_static        # DATABASE_URL (데모 적재된 DB) 필요

백엔드가 꺼져 있어도(또는 Render 무료 서버가 잠들어 있어도) 화면이 같은 모양의 데이터로 동작하게 하는 장치.
파일 내용 = 실제 API 응답 그대로이므로, 화면 코드는 live/static 을 구분하지 않는다.
검색만은 정적으로 뜰 수 없어서 search_index.json 을 만들고 브라우저가 같은 점수 공식으로 계산한다.
"""
import json
import pathlib
import shutil
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.db import q
from app.main import app

OUT = pathlib.Path(__file__).resolve().parents[2] / "app" / "data"


def fname(key: str) -> str:
    return key.replace(":", "__")


def dump(path: pathlib.Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")


def main():
    # 폴더 자체는 두고 내용만 비운다 (Windows 에서 폴더가 열려 있으면 삭제가 막힘)
    for p in sorted(OUT.rglob("*"), reverse=True) if OUT.exists() else []:
        p.unlink() if p.is_file() else shutil.rmtree(p, ignore_errors=True)
    with TestClient(app) as c:
        get = lambda p: c.get(p).json()
        dump(OUT / "health.json", get("/health"))
        laws = get("/laws")
        dump(OUT / "laws.json", laws)
        for l in laws:
            dump(OUT / "toc" / f"{l['slug']}.json", get(f"/laws/{l['slug']}/toc"))
        # 스냅숏 범위 (실데이터 전체는 수천 개 파일 + 원문 대량 재게시가 되므로 대표 범위만):
        #   조문: 전자금융 3단 전체 + 많이 인용된 조문 상위 ARTICLE_LIMIT 개
        #   문서: 스냅숏 조문에 연결된 문서 중 최신 DOC_LIMIT 건 + 행정지도 전체
        ARTICLE_LIMIT, DOC_LIMIT = 400, 600
        keys = [r["key"] for r in q("""
            SELECT key FROM articles WHERE law_slug IN ('efta','efta-ed','efta-reg')
            UNION SELECT article_key FROM (SELECT article_key, count(*) n FROM article_links GROUP BY 1
                                           ORDER BY n DESC LIMIT %s) t""", (ARTICLE_LIMIT,))]
        for k in keys:
            dump(OUT / "articles" / f"{fname(k)}.json", get("/articles/" + quote(k)))
            dump(OUT / "graph" / f"{fname(k)}.json", get("/articles/" + quote(k) + "/graph"))
        doc_ids = [r["id"] for r in q("""
            SELECT id FROM (SELECT DISTINCT d.id, d.published_on FROM documents d JOIN article_links l ON l.doc_id=d.id
                            WHERE l.article_key = ANY(%s) ORDER BY d.published_on DESC LIMIT %s) t
            UNION SELECT id FROM documents WHERE kind='행정지도'""", (keys, DOC_LIMIT))]
        for i in doc_ids:
            dump(OUT / "documents" / f"{fname(i)}.json", get("/documents/" + quote(i)))
        dump(OUT / "feed.json", get("/feed?days=730&limit=200"))
        dump(OUT / "analysis.json", get("/analysis"))
        dump(OUT / "guidance.json", {s: get(f"/guidance?status={s}&within=60") for s in ("active", "expiring", "notice")})
        # 브라우저 검색용 색인: 문서 본문 + 연결 조문 + 조문 제목·약칭 사전
        docs = q("""SELECT d.id, d.kind, d.title, d.org, d.dept, d.published_on, d.stage, d.valid_to,
                           left(d.search_text, 600) AS search_text,
                           coalesce(json_agg(json_build_object('key',a.key,'label',a.label,'title',a.title,
                                     'law_name',w.name,'law_kind',w.kind,'law_root',coalesce(w.parent_slug,w.slug)))
                                     FILTER (WHERE a.key IS NOT NULL), '[]') AS articles
                    FROM documents d LEFT JOIN article_links l ON l.doc_id=d.id
                    LEFT JOIN articles a ON a.key=l.article_key LEFT JOIN laws w ON w.slug=a.law_slug
                    WHERE d.id = ANY(%s) GROUP BY d.id""", (doc_ids,))
        arts = q("""SELECT a.key, a.label, a.title, w.name AS law_name, w.kind AS law_kind, w.slug AS law_slug,
                           w.aliases, coalesce(s.total,0) AS linked
                    FROM articles a JOIN laws w ON w.slug=a.law_slug LEFT JOIN article_stats s ON s.article_key=a.key
                    WHERE a.key = ANY(%s)""", (keys,))
        dump(OUT / "search_index.json", {"documents": docs, "articles": arts})
    n = sum(1 for _ in OUT.rglob("*.json"))
    size = sum(p.stat().st_size for p in OUT.rglob("*.json"))
    print(f"정적 데이터 {n}개 파일, {size/1024:.0f} KB → {OUT}")


if __name__ == "__main__":
    main()
