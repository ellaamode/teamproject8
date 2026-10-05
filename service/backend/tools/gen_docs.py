"""발표용 문서 자동 생성: API 설명 문서 + DB 테이블 문서 → service/docs/data.json

  python -m tools.gen_docs          # DATABASE_URL 필요 (스키마가 적용된 DB)

- API: FastAPI 가 만드는 OpenAPI 명세(= Swagger 와 같은 원천)에서 경로·요청 방식·입력값을 읽고,
       응답 형식은 실제 API 를 한 번 호출한 결과에서 필드 이름·자료형을 뽑는다(예시 포함).
- DB : PostgreSQL 카탈로그에서 테이블·컬럼·자료형·NULL 허용·기본키·외래키를 읽는다.
코드와 DB 에서 바로 뽑으므로 문서가 실제와 어긋날 수 없다.
"""
import json
import pathlib
from urllib.parse import quote

from fastapi.testclient import TestClient

from app.db import q
from app.main import app

OUT = pathlib.Path(__file__).resolve().parents[2] / "docs" / "data.json"

TABLE_DESC = {
    "raw_payloads": "원천 응답 원본 보관소. 같은 내용(해시)은 다시 저장하지 않음 → 증분 수집·재처리의 기준",
    "pipeline_runs": "배치 단계별 실행 기록 (/health 의 데이터 기준 시각)",
    "laws": "대상 법령 목록. parent_slug 로 법률 → 시행령·감독규정 위임 계층",
    "articles": "조문의 정체성 (법령 + 조문 번호). 서비스의 중심",
    "article_versions": "조문 본문의 시행일별 버전 (현행·시행예정 공존)",
    "delegations": "조문 간 위임 관계 (법 → 시행령 → 감독규정)",
    "documents": "법령해석·비조치의견·행정지도·입법예고 등 문서",
    "article_links": "문서 ↔ 조문 인용 연결 (근거 표현·방법·신뢰도)",
    "unresolved_mentions": "연결하지 못한 인용 (대상 밖 법령 등) — 별칭 사전·대상 법령 보강용",
    "change_events": "변화 이벤트 (새 해석, 조문 시행예정, 행정지도 시행·만료 등)",
    "article_stats": "조문별 연결 문서 수 집계 (구체화 뷰)",
}
SAMPLE_PATHS = {
    "/articles/{key}": "efta:25의2", "/articles/{key}/graph": "efta:25의2", "/laws/{slug}/toc": "efta",
}


def shape(v, depth=0):
    """응답 JSON → 필드 이름과 자료형 트리."""
    if isinstance(v, dict):
        return {k: shape(x, depth + 1) for k, x in v.items()} if depth < 3 else "object"
    if isinstance(v, list):
        return [shape(v[0], depth + 1)] if v else []
    return {str: "string", int: "integer", float: "number", bool: "boolean", type(None): "null"}.get(type(v), "string")


def trim(v, depth=0):
    if isinstance(v, dict):
        return {k: trim(x, depth + 1) for k, x in list(v.items())[:14]}
    if isinstance(v, list):
        return [trim(x, depth + 1) for x in v[:2]] + (["…"] if len(v) > 2 else [])
    if isinstance(v, str) and len(v) > 80:
        return v[:80] + "…"
    return v


def api_docs(client) -> list:
    spec = client.get("/openapi.json").json()
    out = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            params = [{"name": p["name"], "in": {"path": "경로", "query": "쿼리"}[p["in"]], "required": p.get("required", False),
                       "type": (p["schema"].get("type") or (p["schema"].get("anyOf") or [{}])[0].get("type") or "array"),
                       "default": p["schema"].get("default"), "description": p.get("description", ""),
                       "constraints": {k: p["schema"][k] for k in ("minimum", "maximum", "maxLength", "pattern") if k in p["schema"]}}
                      for p in op.get("parameters", [])]
            url = path
            for k, v in [("{key}", SAMPLE_PATHS.get(path, "efta:25의2")), ("{slug}", "efta")]:
                url = url.replace(k, quote(v))
            if "{doc_id}" in url:
                did = q("SELECT id FROM documents WHERE kind='법령해석' ORDER BY published_on DESC LIMIT 1")
                url = url.replace("{doc_id}", quote(did[0]["id"]) if did else "x")
            r = client.get(url + ("?q=" + quote("선불충전금") if path == "/search" else ""))
            body = r.json() if r.status_code == 200 else None
            out.append({"method": method.upper(), "path": path, "summary": op.get("summary", ""), "tag": (op.get("tags") or [""])[0],
                        "params": params, "example_request": url, "status": r.status_code,
                        "response_shape": shape(body) if body is not None else None,
                        "response_example": trim(body) if body is not None else None})
    return out


def db_docs() -> list:
    cols = q("""SELECT c.table_name, c.column_name, c.data_type, c.is_nullable, c.column_default, c.ordinal_position
                FROM information_schema.columns c WHERE c.table_schema='public' ORDER BY c.table_name, c.ordinal_position""")
    pks = q("""SELECT tc.table_name, kcu.column_name FROM information_schema.table_constraints tc
               JOIN information_schema.key_column_usage kcu ON kcu.constraint_name=tc.constraint_name AND kcu.table_schema=tc.table_schema
               WHERE tc.constraint_type='PRIMARY KEY' AND tc.table_schema='public'""")
    fks = q("""SELECT con.conrelid::regclass::text AS table_name, a.attname AS column_name,
                      con.confrelid::regclass::text AS ref_table, af.attname AS ref_column, con.confdeltype AS on_delete
               FROM pg_constraint con
               JOIN pg_attribute a ON a.attrelid=con.conrelid AND a.attnum = ANY(con.conkey)
               JOIN pg_attribute af ON af.attrelid=con.confrelid AND af.attnum = con.confkey[array_position(con.conkey, a.attnum)]
               WHERE con.contype='f' AND con.connamespace='public'::regnamespace""")
    views = q("SELECT matviewname AS table_name FROM pg_matviews WHERE schemaname='public'")
    counts = {}
    for t in TABLE_DESC:
        try:
            counts[t] = q(f"SELECT count(*) AS n FROM {t}")[0]["n"]
        except Exception:
            counts[t] = None
    tables = []
    names = list(dict.fromkeys([c["table_name"] for c in cols] + [v["table_name"] for v in views]))
    for t in sorted(names, key=lambda x: list(TABLE_DESC).index(x) if x in TABLE_DESC else 99):
        if t not in TABLE_DESC:
            continue
        pk = [p["column_name"] for p in pks if p["table_name"] == t]
        tf = {f["column_name"]: f for f in fks if f["table_name"] == t}
        tables.append({"name": t, "description": TABLE_DESC[t], "rows": counts.get(t), "primary_key": pk,
                       "columns": [{"name": c["column_name"], "type": c["data_type"], "nullable": c["is_nullable"] == "YES",
                                    "default": c["column_default"], "pk": c["column_name"] in pk,
                                    "fk": f"{tf[c['column_name']]['ref_table']}.{tf[c['column_name']]['ref_column']}" if c["column_name"] in tf else None}
                                   for c in cols if c["table_name"] == t],
                       "references": sorted({f["ref_table"] for f in fks if f["table_name"] == t})})
    for v in views:                                    # 구체화 뷰는 information_schema.columns 에 안 나옴
        if v["table_name"] in TABLE_DESC and not any(t["name"] == v["table_name"] for t in tables):
            vc = q("""SELECT a.attname AS name, format_type(a.atttypid, a.atttypmod) AS type FROM pg_attribute a
                      WHERE a.attrelid = %s::regclass AND a.attnum > 0 ORDER BY a.attnum""", (v["table_name"],))
            tables.append({"name": v["table_name"], "description": TABLE_DESC[v["table_name"]], "rows": counts.get(v["table_name"]),
                           "primary_key": [], "view": True, "references": ["article_links", "documents"],
                           "columns": [{"name": c["name"], "type": c["type"], "nullable": True, "pk": False, "fk": None} for c in vc]})
    return tables


def main():
    with TestClient(app) as c:
        data = {"api": api_docs(c), "db": db_docs()}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"API {len(data['api'])}개, 테이블 {len(data['db'])}개 → {OUT}")


if __name__ == "__main__":
    main()
