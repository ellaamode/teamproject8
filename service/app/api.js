/* 데이터 계층. 화면은 이 객체만 부른다.
 *  live  : config.js 의 FINREG_API 가 있으면 FastAPI 호출
 *  static: 없으면 data/*.json (= 실제 API 응답을 떠 둔 스냅숏). 검색·피드 필터만 브라우저에서 계산
 * live 호출이 실패하면(무료 서버 절전 등) 자동으로 static 으로 넘어가 화면이 멈추지 않는다.
 */
const BASE = (window.FINREG_API || "").replace(/\/$/, "");
const cache = new Map();
let fellBack = false;

const fname = (k) => encodeURIComponent(k.replace(/:/g, "__"));
const STATIC = {
  health: () => "data/health.json",
  laws: () => "data/laws.json",
  toc: (slug) => `data/toc/${slug}.json`,
  article: (key) => `data/articles/${fname(key)}.json`,
  graph: (key) => `data/graph/${fname(key)}.json`,
  analysis: () => "data/analysis.json",
  document: (id) => `data/documents/${fname(id)}.json`,
  feed: () => "data/feed.json",
  guidance: () => "data/guidance.json",
  index: () => "data/search_index.json",
};

async function getJSON(url, timeoutMs) {
  if (cache.has(url)) return cache.get(url);
  const ctl = new AbortController();
  const t = timeoutMs ? setTimeout(() => ctl.abort(), timeoutMs) : null;
  const p = fetch(url, { signal: ctl.signal }).then((r) => {
    if (!r.ok) throw Object.assign(new Error(`HTTP ${r.status}`), { status: r.status });
    return r.json();
  }).finally(() => t && clearTimeout(t));
  cache.set(url, p);
  p.catch(() => cache.delete(url));
  return p;
}

async function call(livePath, staticKey, ...args) {
  if (BASE && !fellBack) {
    try {
      return await getJSON(BASE + livePath, 45000);   // 무료 서버 첫 요청은 30~60초 걸릴 수 있음
    } catch (e) {
      if (e.status === 404) throw e;
      fellBack = true;
      document.dispatchEvent(new CustomEvent("api:fallback"));
    }
  }
  return getJSON(STATIC[staticKey](...args));
}

const qs = (o) => Object.entries(o).flatMap(([k, v]) =>
  Array.isArray(v) ? v.map((x) => [k, x]) : v === undefined || v === "" || v === null ? [] : [[k, v]])
  .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");

/* ------------------------------------------------------------ 정적 모드 계산 (서버와 같은 규칙) */
const like = (h, w) => h.includes(w);

function staticSearch(ix, p) {
  const q = (p.q || "").trim();
  const words = q.split(/\s+/).filter(Boolean).slice(0, 6);
  // 조문 표기 바로가기: '전금법 제25조의2', '전자금융감독규정 14조의2'
  let jump = null;
  const m = q.match(/(\d+(?:-\d+)?)\s*조(?:\s*의\s*(\d+))?/);
  if (m) {
    const no = m[1] + (m[2] ? `의${m[2]}` : "");
    const head = q.slice(0, m.index).replace(/\s|제$/g, "").replace(/제$/, "");
    const cands = ix.articles.filter((a) => a.key.endsWith(":" + no));
    const hit = cands.find((a) => head && (a.law_name.replace(/\s/g, "") === head ||
      (a.aliases || []).includes(head) || (head.endsWith("시행령") && a.law_kind === "시행령" && a.law_name.replace(/\s/g, "").startsWith(head.replace("시행령", ""))))) ||
      (!head ? cands.find((a) => a.law_kind === "법률") : null);
    if (hit) jump = { key: hit.key, label: hit.label, title: hit.title, law_name: hit.law_name };
  }
  const matchDoc = (d) => {
    if (!words.length) return 0;
    const titleMatchArt = (d.articles || []).some((a) => words.every((w) => like(a.title || "", w)));
    const hits = words.filter((w) => like(d.search_text, w)).length;
    if (!hits && !titleMatchArt) return null;
    const inTitle = words.filter((w) => like(d.title, w)).length;
    return (hits * 3 + inTitle * 2) / words.length;
  };
  let rows = ix.documents.map((d) => ({ d, score: matchDoc(d) })).filter((x) => x.score !== null);
  if (p.orgs?.length) rows = rows.filter((x) => p.orgs.includes(x.d.org));
  if (p.laws?.length) rows = rows.filter((x) => x.d.articles.some((a) => p.laws.includes(a.law_root)));
  if (p.from) rows = rows.filter((x) => x.d.published_on >= p.from);
  if (p.to) rows = rows.filter((x) => x.d.published_on <= p.to);
  const facets = {};
  rows.forEach((x) => { facets[x.d.kind] = (facets[x.d.kind] || 0) + 1; });
  if (p.kinds?.length) rows = rows.filter((x) => p.kinds.includes(x.d.kind));
  const byDate = (a, b) => (a.d.published_on < b.d.published_on ? 1 : -1);
  rows.sort(p.sort === "date" || !words.length ? byDate : (a, b) => b.score - a.score || byDate(a, b));
  const snippet = (t) => {
    t = t.replace(/\s+/g, " ");
    const pos = Math.min(...words.map((w) => t.indexOf(w)).filter((i) => i >= 0), Infinity);
    if (!isFinite(pos)) return t.slice(0, 140);
    const s = Math.max(0, pos - 70);
    return (s ? "…" : "") + t.slice(s, pos + 70) + (pos + 70 < t.length ? "…" : "");
  };
  const items = rows.slice(p.offset || 0, (p.offset || 0) + (p.limit || 20)).map(({ d, score }) => {
    const seen = new Set();
    return {
      id: d.id, kind: d.kind, title: d.title, org: d.org, dept: d.dept, published_on: d.published_on,
      stage: d.stage, valid_to: d.valid_to, score, snippet: snippet(d.search_text),
      articles: d.articles.filter((a) => !seen.has(a.key) && seen.add(a.key)).slice(0, 4),
    };
  });
  const artAll = words.length ? ix.articles.filter((a) => words.every((w) => like(a.title || "", w)))
    .sort((a, b) => b.linked - a.linked) : [];
  return { query: q, jump, total: rows.length, facets, articles: artAll.slice(0, 12), articles_total: artAll.length, items };
}

function staticFeed(f, p) {
  const since = new Date(Date.now() - (p.days || 90) * 864e5).toISOString().slice(0, 10);
  let items = f.items.filter((e) => e.occurred_on >= since);
  if (p.articles?.length) items = items.filter((e) => e.article_keys.some((k) => p.articles.includes(k)));
  if (p.kinds?.length) items = items.filter((e) => p.kinds.includes(e.kind));
  const summary = {};
  items.forEach((e) => { summary[e.kind] = (summary[e.kind] || 0) + 1; });
  return { since, summary, items: items.slice(0, p.limit || 50) };
}

export const api = {
  get mode() { return BASE && !fellBack ? "live" : "static"; },
  health: () => call("/health", "health"),
  laws: () => call("/laws", "laws"),
  toc: (slug) => call(`/laws/${encodeURIComponent(slug)}/toc`, "toc", slug),
  article: (key) => call(`/articles/${encodeURIComponent(key)}`, "article", key),
  graph: (key) => call(`/articles/${encodeURIComponent(key)}/graph`, "graph", key),
  analysis: () => call("/analysis", "analysis"),
  document: (id) => call(`/documents/${encodeURIComponent(id)}`, "document", id),
  async search(p) {
    if (BASE && !fellBack) {
      try { return await getJSON(`${BASE}/search?${qs(p)}`, 45000); } catch { fellBack = true; }
    }
    return staticSearch(await getJSON(STATIC.index()), p);
  },
  async feed(p = {}) {
    if (BASE && !fellBack) {
      try { return await getJSON(`${BASE}/feed?${qs(p)}`, 45000); } catch { fellBack = true; }
    }
    return staticFeed(await getJSON(STATIC.feed()), p);
  },
  async guidance(status = "active") {
    if (BASE && !fellBack) {
      try { return await getJSON(`${BASE}/guidance?status=${status}&within=60`, 45000); } catch { fellBack = true; }
    }
    return (await getJSON(STATIC.guidance()))[status];
  },
};
