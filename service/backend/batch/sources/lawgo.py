"""법제처 국가법령정보 공동활용 Open API (DRF) 수집기 — OC 키가 있으면 웹페이지 수집(lawweb) 대신 이것을 쓴다.

실제 응답으로 확인한 호출 (2026-10-05, tools/lawgo_probe.py 견본)
  lawSearch.do  target=law     법령 검색      LawSearch.law[]        법령명한글·법령일련번호(MST)·시행일자·현행연혁코드
  lawSearch.do  target=eflaw   nw=2 시행예정   LawSearch.law[]        같은 법령의 시행예정 본이 여러 개일 수 있다(자본시장법 3개)
  lawService.do target=law     MST 본문       법령.조문.조문단위[]    → lawtext.lines_from_law_json
  lawSearch.do  target=admrul  행정규칙 검색   AdmRulSearch.admrul    결과가 1건이면 list 가 아니라 dict
  lawService.do target=admrul  ID 본문        AdmRulService.조문내용[] → lawtext.lines_from_admrul_json
  lawService.do target=thdCmp  knd=2 위임조문  LspttnThdCmpLawXService.위임조문삼단비교.법률조문[]
                                              한 항목 = 법률 조문 하나 + 위임받은 시행령조문(·시행규칙조문) 하나
주의(실측): MST 만으로 본문을 받으면 '공포는 됐지만 아직 시행 전'인 개정 내용이 섞여 온다
  (전자금융거래법 제3조: 2026-12-17 시행분이 2026-10-02 본문에 들어옴) → 본문은 시행일(efYd)을 지정해서 받는다.

키는 Referer/User-Agent 가 없으면 '사용자 정보 검증 실패'로 거부된다(PoliteClient 가 붙인다).
"""
from __future__ import annotations

import json

from .. import store
from ..config import LAW_BY_SLUG, SETTINGS, TARGET_LAWS
from ..http import PoliteClient

BASE = "https://www.law.go.kr/DRF"
REFERER = "https://www.law.go.kr/"

# 검색 결과 필드 (실제 응답으로 확인)
FIELDS = {
    "law":    {"list": ("LawSearch", "law"), "name": "법령명한글", "id": "법령ID", "seq": "법령일련번호",
               "effective": "시행일자", "promulgated": "공포일자", "status": "현행연혁코드"},
    "admrul": {"list": ("AdmRulSearch", "admrul"), "name": "행정규칙명", "id": "행정규칙ID", "seq": "행정규칙일련번호",
               "effective": "시행일자", "promulgated": "발령일자", "status": "현행연혁구분"},
}
# 시행일 기준 법령 본문을 받는 target. 실측: eflaw + efYd 로 받으면 그날 시행 중인 본문만 온다
# (전자금융거래법 제3조가 2026-10-02 본에서는 개정 전 문구, 2026-12-17 시행예정 본에서는 개정 후 문구)
LAW_BODY_TARGET = "eflaw"


def _search(client, target: str, query: str, **extra) -> list[dict]:
    r = client.request("GET", f"{BASE}/lawSearch.do", expect="json", referer=REFERER,
                       params={"OC": SETTINGS.law_oc, "target": target, "type": "JSON", "query": query,
                               "display": 20, **extra})
    node = r.json()
    for k in FIELDS["admrul" if target == "admrul" else "law"]["list"]:
        node = node.get(k, {}) if isinstance(node, dict) else node
    return node if isinstance(node, list) else [node] if node else []


def _exact(rows: list[dict], name: str, f: dict) -> list[dict]:
    """이름이 정확히 같은 행만 (띄어쓰기 무시). '전자금융감독규정' 검색에 '…시행세칙'도 함께 나온다."""
    norm = name.replace(" ", "")
    return [r for r in rows if str(r.get(f["name"], "")).replace(" ", "") == norm]


BODY_TARGET_USED: dict[str, int] = {}      # 시험 실행에서 실제로 통한 target 기록


def _body(client, target: str, seq: str, efyd: str | None) -> dict:
    params = {"OC": SETTINGS.law_oc, "type": "JSON"}
    if target != "law":
        params.update({"target": "admrul", "ID": seq})
        return client.request("GET", f"{BASE}/lawService.do", expect="json", referer=REFERER, params=params).json()
    for t in dict.fromkeys((LAW_BODY_TARGET, "law")):          # 시행일 기준 본문: eflaw → 안 되면 law+efYd
        body = client.request("GET", f"{BASE}/lawService.do", expect="json", referer=REFERER,
                              params={**params, "target": t, "MST": seq, "efYd": efyd or ""}).json()
        if isinstance(body.get("법령"), dict):
            BODY_TARGET_USED[t] = BODY_TARGET_USED.get(t, 0) + 1
            return body
    raise ValueError(f"법령 본문 응답에 '법령' 항목이 없음: {list(body)[:5]}")


def _have(conn, source: str, key: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM raw_payloads WHERE source=%s AND source_key=%s LIMIT 1",
                             (source, key)).fetchone())


def fetch_laws(conn, client: PoliteClient | None = None, slugs: list[str] | None = None) -> dict:
    """대상 법령의 현행 본문과 시행예정 본문(여러 개일 수 있음), 법률의 3단비교(위임조문)를 '바뀐 경우에만' 받는다.

    원본 키: '{slug}:{일련번호}:{시행일}' — 웹 수집분('{slug}:{일련번호}')과 겹치지 않아, 키를 받은 첫날 API 본으로 한 번 다시 받는다.
    같은 키가 이미 있으면(=그 시행일 본문을 이미 받음) 호출하지 않는다 → 평소에는 법령마다 검색 1~2회로 끝난다."""
    if not SETTINGS.law_oc:
        return {"skipped": "LAW_GO_KR_OC 미설정"}
    client = client or PoliteClient()
    stats = {"checked": 0, "fetched": 0, "pending_versions": 0, "thdcmp": 0, "unchanged": 0, "not_found": [], "errors": 0}
    for spec in TARGET_LAWS:
        if slugs and spec.slug not in slugs:
            continue
        stats["checked"] += 1
        target = "admrul" if spec.source == "lawgo.admrul" else "law"
        f = FIELDS[target]
        try:
            hits = _exact(_search(client, target, spec.name), spec.name, f)
            cur = next((h for h in hits if h.get(f["status"]) == "현행"), hits[0] if hits else None)
            if not cur:
                stats["not_found"].append(spec.name)
                continue
            store.upsert_law(conn, spec, source_id=str(cur.get(f["id"]) or ""), current_seq=None)
            versions = [("현행", cur)]
            if target == "law":                                     # 시행예정 본 (여러 개면 모두)
                versions += [("시행예정", h) for h in _exact(_search(client, "eflaw", spec.name, nw=2), spec.name, f)
                             if str(h.get(f["seq"])) != str(cur[f["seq"]]) or h.get(f["effective"]) != cur.get(f["effective"])]
            for label, h in versions:
                seq, efyd = str(h[f["seq"]]), str(h.get(f["effective"]) or "")
                key = f"{spec.slug}:{seq}:{efyd}"
                if _have(conn, spec.source, key):
                    stats["unchanged"] += 1
                    continue
                meta = {"slug": spec.slug, "seq": seq, "version": label, "effective": efyd,
                        "promulgated": h.get(f["promulgated"]), "via": "api",
                        "source_url": f"https://www.law.go.kr/{'법령' if target == 'law' else '행정규칙'}/"
                                      f"{spec.name.replace(' ', '')}"}
                body = _body(client, target, seq, efyd)
                store.save_raw(conn, spec.source, key, 200, json.dumps({"meta": meta, "body": body}, ensure_ascii=False))
                stats["fetched"] += 1
                stats["pending_versions"] += label == "시행예정"
            if spec.kind == "법률":                                  # 3단비교: 법률 ↔ 시행령·시행규칙 위임조문
                key = f"{spec.slug}:{cur[f['seq']]}"
                if not _have(conn, "lawgo.thdcmp", key):
                    r = client.request("GET", f"{BASE}/lawService.do", expect="json", referer=REFERER,
                                       params={"OC": SETTINGS.law_oc, "target": "thdCmp", "type": "JSON",
                                               "MST": cur[f["seq"]], "knd": 2})
                    store.save_raw(conn, "lawgo.thdcmp", key, r.status_code, r.text)
                    stats["thdcmp"] += 1
            conn.commit()
        except Exception as e:
            conn.rollback()
            stats["errors"] += 1
            msg = str(e).replace(SETTINGS.law_oc, "<OC>")          # 오류 문구의 URL 에 키가 섞여 실행 기록(/health)에 남지 않게
            stats.setdefault("error_detail", []).append(f"{spec.slug}: {type(e).__name__}: {msg[:120]}")
    stats["body_target"] = dict(BODY_TARGET_USED)
    return stats


def _art_no(item: dict) -> str | None:
    """3단비교 항목의 조번호 '0002'·조가지번호 '02' → '2의2'"""
    try:
        no, br = int(item.get("조번호") or 0), int(item.get("조가지번호") or 0)
    except ValueError:
        return None
    return (f"{no}의{br}" if br else str(no)) if no else None


def delegation_pairs(slug: str, payload: str) -> list[tuple[str, str]]:
    """3단비교(knd=2) 응답 → (법률 조문 키, 시행령·시행규칙 조문 키) 목록.
    조내용이 '제1장 총칙' 같은 장 제목인 행, 위임 조문이 없는 행은 건너뛴다."""
    root = json.loads(payload).get("LspttnThdCmpLawXService", {})
    items = (root.get("위임조문삼단비교") or {}).get("법률조문") or []
    items = items if isinstance(items, list) else [items]
    pairs = []
    for it in items:
        src = _art_no(it)
        if not src or not str(it.get("조제목") or "").startswith("제"):
            continue
        for field, child in (("시행령조문", "ed"), ("시행규칙조문", "rule")):
            subs = it.get(field) or []
            for sub in subs if isinstance(subs, list) else [subs]:
                if isinstance(sub, dict) and (dst := _art_no(sub)):
                    pairs.append((f"{slug}:{src}", f"{slug}-{child}:{dst}"))
    return list(dict.fromkeys(pairs))


def spec_of(slug: str):
    return LAW_BY_SLUG[slug]
