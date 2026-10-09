import { api } from "./api.js";
import { renderGraph } from "./graph.js";
import { bindTips, hbars, ratioBar, stackedCols } from "./charts.js";

/* ============================================================ 유틸 */
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const I = (n, c = "") => window.icon(n, c);
const KI = (k) => window.KIND_ICON[k] || "article";
const today = () => new Date().toISOString().slice(0, 10);
const fmt = (d) => (d ? String(d).slice(0, 10).replace(/-/g, ".") : "");
const days = (d) => Math.round((new Date(d) - new Date(today())) / 864e5);
const kchip = (k, label = k) => `<span class="kchip" data-k="${esc(k)}">${I(KI(k))}${esc(label)}</span>`;
const kicon = (k) => `<span class="kicon" data-k="${esc(k)}">${I(KI(k))}</span>`;
const aLink = (key) => `#/a/${encodeURIComponent(key)}`;
const dLink = (id) => `#/d/${encodeURIComponent(id)}`;
// 짧은 출처 표기: '전자금융거래법 시행령' → '시행령', 감독규정·법률은 이름 그대로
const lawShort = (name) => (/ 시행령$/.test(name) ? "시행령" : / 시행규칙$/.test(name) ? "시행규칙" : name);
const tierShort = { "법률": "법", "시행령": "령", "시행규칙": "칙", "감독규정": "규", "고시": "고", "시행세칙": "세" };
const ADMIN_RULE = new Set(["감독규정", "고시", "시행세칙"]);   // 국가법령정보센터 '행정규칙'으로 게시되는 종류
const methodLabel = {
  explicit: "법령명 명시", abbr: "약칭", defined: "문서 내 약칭", same_law: "같은 법·같은 조",
  this_law: "이 법", parent_ref: "모법·하위규정 지칭", title: "제목 표기", inferred: "문맥 추정", manual: "수동 검수",
};
const EV = {
  해석_신규: ["법령해석", "새 법령해석"], 비조치_신규: ["비조치의견", "새 비조치의견"],
  조문_개정: ["조문", "조문 개정"], 조문_시행예정: ["조문", "시행 예정"],
  행정지도_예고: ["행정지도", "행정지도 예고"], 행정지도_시행: ["행정지도", "행정지도 시행"],
  행정지도_만료임박: ["행정지도", "만료 임박"], 행정지도_만료: ["행정지도", "존속기간 만료"],
  입법예고_시작: ["입법예고", "예고 시작"], 입법예고_마감임박: ["입법예고", "의견제출 마감 임박"],
};
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("on");
  clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("on"), 1900);
}
const skeleton = (n = 3) => Array.from({ length: n }, () => '<div class="skeleton" style="margin-bottom:12px"></div>').join("");

/* 관심 조문: 로그인 없이 이 브라우저에만 저장 */
const watch = {
  all() { try { return JSON.parse(localStorage.getItem("finreg.watch") || "[]"); } catch { return []; } },
  has(key) { return this.all().some((w) => w.key === key); },
  toggle(item) {
    let w = this.all();
    w = w.some((x) => x.key === item.key) ? w.filter((x) => x.key !== item.key) : [...w, item];
    try { localStorage.setItem("finreg.watch", JSON.stringify(w)); } catch {}
    updateBadge(); return w.some((x) => x.key === item.key);
  },
};
function updateBadge() {
  const n = watch.all().length, b = $("#watchBadge");
  b.textContent = n; b.hidden = !n;
}

/* ============================================================ 일러스트 */
const ILLUS = {
  constellation: () => `
  <svg viewBox="0 0 360 280" role="img" aria-label="조문 하나에 해석·비조치·행정지도·예고가 연결된 모습">
    <defs><filter id="sh" x="-20%" y="-20%" width="140%" height="160%"><feDropShadow dx="0" dy="6" stdDeviation="8" flood-opacity=".14"/></filter></defs>
    <g stroke="var(--line-2)" stroke-width="1.6" stroke-dasharray="3 6" fill="none">
      <path d="M180 140 L70 64"/><path d="M180 140 L292 58"/><path d="M180 140 L60 214"/><path d="M180 140 L300 214"/>
    </g>
    <g class="orb" style="animation:float 6s ease-in-out infinite">
      ${[["법령해석", 70, 64], ["비조치의견", 292, 58], ["행정지도", 60, 214], ["입법예고", 300, 214]].map(([k, x, y]) => `
      <g transform="translate(${x} ${y})" data-k="${k}">
        <circle r="30" fill="var(--surface)" filter="url(#sh)"/><circle r="30" fill="color-mix(in srgb, var(--k) 16%, transparent)"/>
        <svg x="-13" y="-13" width="26" height="26" viewBox="0 0 24 24" style="color:var(--k)" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><use href="#i-${KI(k)}"/></svg>
      </g>`).join("")}
    </g>
    <g transform="translate(118 98)" filter="url(#sh)">
      <rect width="124" height="84" rx="18" fill="var(--surface)" stroke="var(--line)"/>
      <rect x="14" y="14" width="30" height="30" rx="9" fill="var(--brand)"/>
      <text x="29" y="35" text-anchor="middle" font-size="17" font-weight="800" fill="var(--on-brand)">§</text>
      <rect x="54" y="18" width="54" height="8" rx="4" fill="var(--ink-2)" opacity=".75"/>
      <rect x="54" y="32" width="38" height="7" rx="3.5" fill="var(--line-2)"/>
      <rect x="14" y="56" width="96" height="6" rx="3" fill="var(--line-2)"/>
      <rect x="14" y="68" width="70" height="6" rx="3" fill="var(--line-2)"/>
    </g>
  </svg>`,
  emptySearch: () => `
  <svg class="art" viewBox="0 0 120 100" aria-hidden="true">
    <rect x="18" y="14" width="62" height="76" rx="10" fill="var(--surface)" stroke="var(--line-2)" stroke-width="2"/>
    <rect x="30" y="30" width="38" height="6" rx="3" fill="var(--line-2)"/><rect x="30" y="44" width="28" height="6" rx="3" fill="var(--line-2)"/>
    <circle cx="80" cy="62" r="18" fill="var(--brand-soft)" stroke="var(--brand)" stroke-width="3"/>
    <path d="M93 75l12 12" stroke="var(--brand)" stroke-width="5" stroke-linecap="round"/>
  </svg>`,
  emptyStar: () => `
  <svg class="art" viewBox="0 0 120 100" aria-hidden="true">
    <circle cx="60" cy="50" r="38" fill="var(--bg-tint)"/>
    <path d="M60 22l8.4 17 18.8 2.7-13.6 13.3 3.2 18.7L60 64.9 43.2 73.7l3.2-18.7L32.8 41.7l18.8-2.7z" fill="color-mix(in srgb, var(--t-guide) 30%, var(--surface))" stroke="var(--t-guide)" stroke-width="2.5" stroke-linejoin="round"/>
  </svg>`,
};

/* ============================================================ 화면: 홈 */
async function viewHome() {
  view.innerHTML = skeleton(4);
  const [feed, health, laws, upcoming] = await Promise.all([
    api.feed({ days: 120, limit: 200 }), api.health(), api.laws(), api.feed({ days: 3, limit: 200 }),
  ]);
  const t = today();
  const past = feed.items.filter((e) => e.occurred_on <= t);
  const future = upcoming.items.filter((e) => e.occurred_on > t);
  // 다가오는 일정: 시행예정 조문은 날짜별로 묶는다
  const guidanceSoon = await api.guidance("expiring");
  const notices = await api.guidance("notice");
  const sched = [];
  const byDate = {};
  future.filter((e) => e.kind === "조문_시행예정").forEach((e) => { (byDate[e.occurred_on] ||= []).push(e); });
  Object.entries(byDate).forEach(([d, list]) => sched.push({ d, k: "조문", t: `${list[0].law_name} 조문 ${list.length}개 시행`, m: list.slice(0, 3).map((e) => e.article_label).join(", ") + (list.length > 3 ? " 외" : ""), href: aLink(list[0].article_key) }));
  guidanceSoon.items.forEach((g) => sched.push({ d: g.valid_to, k: "행정지도", t: g.title, m: "존속기간 만료", href: dLink(g.id) }));
  notices.items.filter((g) => g.valid_to >= t).forEach((g) => sched.push({ d: g.valid_to, k: "행정지도", t: g.title, m: "예고 의견제출 마감", href: dLink(g.id) }));
  sched.sort((a, b) => (a.d < b.d ? -1 : 1));

  const recent90 = past.filter((e) => days(e.occurred_on) >= -90);
  const nNew = recent90.filter((e) => e.kind === "해석_신규" || e.kind === "비조치_신규").length;
  const nPending = future.filter((e) => e.kind === "조문_시행예정").length;
  const nextPending = Object.keys(byDate).sort()[0];
  const kpi = (k, ic, v, unit, c, s, href) => `
    <a class="card hover kpi" href="${href}" data-k="${k}">
      <div class="top-row">${kicon(k)}${I("arrow", "s faint")}</div>
      <div><div class="v num">${v}<small>${unit}</small></div></div>
      <div><div class="c">${c}</div><div class="s">${s}</div></div>
    </a>`;
  const familyRoots = laws.filter((l) => !l.parent);
  view.innerHTML = `
  <section class="hello">
    <div>
      <span class="eyebrow">${I("spark", "s")} ${fmt(t)} 기준 · 데이터 ${fmt(health.data_as_of) || "-"} 갱신</span>
      <h1>조문 하나로,<br>규제의 변화를 따라갑니다</h1>
      <p class="lead">금융법률과 하위법령(시행령·시행규칙·감독규정·고시·시행세칙)을 법령해석·비조치의견·행정지도와 조문 단위로 연결했습니다.</p>
      <p class="scope-line">${I("book", "s")} 1단계 대상 · 자본시장법 · 외국환거래법 · 은행법 · 보험업법 · 전자금융거래법 <span class="faint">— 추후 확대 예정</span></p>
      <form class="bigq" id="bigq" role="search">
        ${I("search")}
        <label class="sr" for="bq">통합검색</label>
        <input id="bq" placeholder="키워드나 조문을 입력하세요 (예: 선불충전금, 전금법 제25조의2)" autocomplete="off">
        <button class="btn primary">검색</button>
      </form>
      <div class="chips"><span class="faint">많이 찾는</span>
        ${["선불충전금", "클라우드", "소액후불결제", "전금법 제25조의2", "전자금융감독규정 제14조의2"].map((w) => `<a class="pill" href="#/search?q=${encodeURIComponent(w)}">${esc(w)}</a>`).join("")}
      </div>
    </div>
    <div class="hello-art">${ILLUS.constellation()}</div>
  </section>
  <section class="kpis">
    ${kpi("법령해석", "interp", nNew, "건", "최근 90일 새 해석·비조치의견", "조문에 자동 연결됨", "#/search?kinds=법령해석&kinds=비조치의견&sort=date")}
    ${kpi("조문", "pending", nPending, "개", "시행을 앞둔 조문", nextPending ? `가장 가까운 시행 ${fmt(nextPending)}` : "예정 없음", "#/laws")}
    ${kpi("행정지도", "guide", guidanceSoon.items.length, "건", "60일 안에 만료되는 행정지도", "존속기간 기준", "#/guidance?tab=expiring")}
    ${kpi("조문", "link", (health.counts?.links || 0).toLocaleString(), "건", "조문에 연결된 해석·의견", "인용 연결 엔진이 자동 연결", "#/insights")}
  </section>
  <div class="grid-2">
    <section class="card sec">
      <div class="sec-h"><h2>${I("bell")} 최근 변화</h2>
        <div class="tabs" id="feedTabs">
          ${[["all", "전체"], ["doc", "해석·비조치"], ["guide", "행정지도"]].map(([v, l], i) => `<button class="pill" data-f="${v}" aria-pressed="${!i}">${l}</button>`).join("")}
        </div>
      </div>
      <div id="feedList"></div>
    </section>
    <div style="display:grid;gap:22px">
      <section class="card sec">
        <div class="sec-h"><h2>${I("clock")} 다가오는 일정</h2></div>
        <div class="upcoming">${sched.slice(0, 6).map((s) => `
          <a class="up" href="${s.href}" data-k="${esc(s.k)}">
            <div class="d"><b class="num">${s.d.slice(8, 10)}</b><span>${+s.d.slice(5, 7)}월</span></div>
            <div><div class="t">${esc(s.t)}</div><div class="m">${kchip(s.k, s.m)} <span class="dday">D-${days(s.d)}</span></div></div>
          </a>`).join("") || '<p class="faint" style="padding:8px 0 16px">예정된 일정이 없습니다.</p>'}</div>
      </section>
      <section class="card sec" id="watchCard"></section>
    </div>
  </div>
  <section class="law-cards">
    ${familyRoots.map((root) => {
      const fam = laws.filter((l) => l.slug === root.slug || l.parent === root.slug);
      return `<a class="card hover law-card" href="#/laws/${root.slug}">
        <div class="tier">${I("book")}</div>
        <div><b>${esc(root.name)}</b><span>${fam.map((f) => `${f.kind} ${f.articles}조`).join(" · ")}</span></div>
        ${I("chev", "faint")}
      </a>`;
    }).join("")}
  </section>`;
  $("#bigq").onsubmit = (e) => { e.preventDefault(); const q = $("#bq").value.trim(); if (q) location.hash = `#/search?q=${encodeURIComponent(q)}`; };
  const groups = { all: null, doc: ["해석_신규", "비조치_신규"], guide: ["행정지도_시행", "행정지도_예고", "행정지도_만료임박", "행정지도_만료"] };
  const renderFeed = (f) => {
    const list = past.filter((e) => !groups[f] || groups[f].includes(e.kind)).slice(0, 8);
    $("#feedList").innerHTML = list.map(feedItem).join("") || '<p class="faint" style="padding:12px 0 20px">이 기간에 변화가 없습니다.</p>';
  };
  $("#feedTabs").onclick = (e) => {
    const b = e.target.closest("[data-f]"); if (!b) return;
    $("#feedTabs").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    renderFeed(b.dataset.f);
  };
  renderFeed("all");
  renderWatchCard();
}

function feedItem(e) {
  const [k, label] = EV[e.kind] || ["조문", e.kind];
  const href = e.doc_id ? dLink(e.doc_id) : e.article_key ? aLink(e.article_key) : "#/";
  return `<a class="feed-item" href="${href}">
    ${kicon(k)}
    <div style="min-width:0">
      <div class="t">${esc(e.title)}</div>
      <div class="m">${kchip(k, label)}<span class="num">${fmt(e.occurred_on)}</span>
        ${(e.articles || []).slice(0, 3).map((a) => `<span class="tag brand">${esc(lawShort(a.law_name))} ${esc(a.label)}</span>`).join("")}
      </div>
    </div>
  </a>`;
}

async function renderWatchCard() {
  const el = $("#watchCard"); if (!el) return;
  const w = watch.all();
  if (!w.length) {
    el.innerHTML = `<div class="sec-h"><h2>${I("star")} 관심 조문</h2></div>
      <div class="empty" style="padding:8px 8px 22px">${ILLUS.emptyStar()}<b>관심 조문을 등록해 보세요</b>
      조문 화면의 ☆ 버튼을 누르면 그 조문에 새 해석·개정이 생길 때 여기에 모입니다.</div>`;
    return;
  }
  const f = await api.feed({ days: 365, articles: w.map((x) => x.key), limit: 5 });
  el.innerHTML = `<div class="sec-h"><h2>${I("star")} 관심 조문 <span class="faint" style="font-weight:500">${w.length}</span></h2><a class="btn sm ghost" href="#/watch">전체 ${I("chev", "s")}</a></div>
    <div class="chips" style="margin:0 0 6px">${w.slice(0, 6).map((x) => `<a class="acite" href="${aLink(x.key)}">${esc(x.label)} <span class="lk">${esc(x.title)}</span></a>`).join("")}</div>
    ${f.items.slice(0, 3).map(feedItem).join("") || '<p class="faint" style="padding:12px 0 18px">최근 1년간 변화가 없습니다.</p>'}`;
}

/* ============================================================ 화면: 검색 */
async function viewSearch(params) {
  const p = {
    q: params.get("q") || "", kinds: params.getAll("kinds"), orgs: params.getAll("orgs"),
    from: params.get("from") || "", to: params.get("to") || "", sort: params.get("sort") || "relevance",
  };
  $("#gq").value = p.q;
  view.innerHTML = skeleton(3);
  const r = await api.search({ ...p, limit: 30 });
  const words = p.q.split(/\s+/).filter(Boolean);
  const hl = (s) => words.reduce((acc, w) => acc.replace(new RegExp(esc(w).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g"), (m) => `<mark>${m}</mark>`), esc(s));
  const set = (k, v) => {
    const n = new URLSearchParams(params);
    if (Array.isArray(v)) { n.delete(k); v.forEach((x) => n.append(k, x)); } else if (v) n.set(k, v); else n.delete(k);
    location.hash = "#/search?" + n.toString();
  };
  // 수집하는 유형만 보여 준다 (입법예고 등은 데이터가 생기면 자동으로 나타남)
  const KINDS = ["법령해석", "비조치의견", "행정지도", ...["입법예고", "규정변경예고"].filter((k) => r.facets[k])];
  const artTotal = Math.max(r.articles_total ?? r.articles.length, r.jump ? 1 : 0);   // '전금법 제28조'처럼 바로가기만 있는 경우 포함
  view.innerHTML = `
  <div class="page-h"><div><h1>${p.q ? `“${esc(p.q)}” 검색 결과` : "해석·의견 찾기"}</h1>
    <div class="sub">${p.q ? `조문 ${artTotal.toLocaleString()}개 · 해석·의견 ${r.total.toLocaleString()}건` : `${r.total.toLocaleString()}건 · 법령해석·비조치의견·행정지도`}</div></div>
    <select class="sel" id="sort" style="width:auto" aria-label="정렬">
      <option value="relevance" ${p.sort === "relevance" ? "selected" : ""}>관련도순</option>
      <option value="date" ${p.sort === "date" ? "selected" : ""}>최신순</option>
    </select>
  </div>
  <div class="search-layout">
    <aside class="card facets">
      <div><h3>해석·의견 유형</h3>${KINDS.map((k) => `
        <button class="fopt" data-kind="${k}" aria-pressed="${p.kinds.includes(k)}" data-k="${k}">
          <span class="box">${p.kinds.includes(k) ? I("check") : ""}</span>${kchip(k)}<span class="n num">${r.facets[k] || 0}</span>
        </button>`).join("")}</div>
      <div><h3>기관</h3>${["금융위원회", "금융감독원"].map((o) => `
        <button class="fopt" data-org="${o}" aria-pressed="${p.orgs.includes(o)}"><span class="box">${p.orgs.includes(o) ? I("check") : ""}</span>${o}</button>`).join("")}</div>
      <div><h3>기간</h3><div class="dates">
        <input type="date" id="fFrom" value="${esc(p.from)}" aria-label="시작일"><input type="date" id="fTo" value="${esc(p.to)}" aria-label="종료일"></div></div>
      <button class="btn sm ghost" id="reset">${I("x", "s")} 조건 초기화</button>
    </aside>
    <section>
      ${p.q ? `
      <div class="res-h"><h2>${I("book", "s")} 조문 <span class="n">${artTotal.toLocaleString()}개</span></h2>
        <span class="faint">법령·하위법령 본문에서 찾은 조문${artTotal > r.articles.length ? ` · 상위 ${r.articles.length}개 표시` : ""}</span></div>
      ${r.jump ? `<a class="card jump" href="${aLink(r.jump.key)}"><span class="ic">${I("article", "l")}</span>
        <div><small>입력하신 조문으로 바로 가기</small><b>${esc(r.jump.law_name)} ${esc(r.jump.label)} ${esc(r.jump.title)}</b></div>${I("arrow")}</a>` : ""}
      ${r.articles.length ? `<div class="art-list">${r.articles.map((a) => `
        <a class="art-chip" href="${aLink(a.key)}"><span class="ic">${I("article", "s")}</span>
        <div><b>${esc(LAW_SHORT[a.law_name] || a.law_name)} ${esc(a.label)}</b><span>${hl(a.title || "")} · 연결 ${a.linked}건</span></div></a>`).join("")}</div>`
        : r.jump ? "" : `<div class="card art-empty">검색어와 맞는 조문이 없습니다.</div>`}
      <div class="res-h"><h2>${I("interp", "s")} 해석·의견 <span class="n">${r.total.toLocaleString()}건</span></h2>
        <span class="faint">법령해석·비조치의견·행정지도</span></div>` : ""}
      ${r.items.map((d) => `
        <a class="card hover result" href="${dLink(d.id)}" data-k="${esc(d.kind)}">
          ${kicon(d.kind)}
          <div style="min-width:0">
            <div class="meta">${kchip(d.kind)}<span>${esc(d.org)}${d.dept ? " · " + esc(d.dept) : ""}</span><span class="num">${fmt(d.published_on)}</span>
              ${d.kind === "행정지도" && d.valid_to ? `<span>존속 ~${fmt(d.valid_to)}</span>` : ""}</div>
            <h3>${hl(d.title)}</h3>
            <p class="snip">${hl(d.snippet)}</p>
            ${d.articles.length ? `<div class="arts">${d.articles.map((a) => `<span class="acite">${I("article")}${esc(a.label)} <span class="lk">${esc(a.title)}</span></span>`).join("")}</div>` : ""}
          </div>
        </a>`).join("") || `<div class="card empty">${ILLUS.emptySearch()}<b>조건에 맞는 해석·의견이 없습니다</b>검색어를 줄이거나 유형 필터를 해제해 보세요.</div>`}
    </section>
  </div>`;
  view.querySelectorAll("[data-kind]").forEach((b) => b.onclick = () => {
    const k = b.dataset.kind; set("kinds", p.kinds.includes(k) ? p.kinds.filter((x) => x !== k) : [...p.kinds, k]);
  });
  view.querySelectorAll("[data-org]").forEach((b) => b.onclick = () => {
    const o = b.dataset.org; set("orgs", p.orgs.includes(o) ? p.orgs.filter((x) => x !== o) : [...p.orgs, o]);
  });
  $("#fFrom").onchange = (e) => set("from", e.target.value);
  $("#fTo").onchange = (e) => set("to", e.target.value);
  $("#sort").onchange = (e) => set("sort", e.target.value);
  $("#reset").onclick = () => { location.hash = p.q ? `#/search?q=${encodeURIComponent(p.q)}` : "#/search"; };
}

/* ============================================================ 화면: 법령 목차 */
const LAW_SHORT = { "자본시장과 금융투자업에 관한 법률": "자본시장법" };
const rootOf = (laws, slug) => (laws.find((l) => l.slug === slug) || {}).parent || slug;
const LAW_ORDER = ["fscma", "bank", "ins", "efta", "fx"];          // 화면에 보이는 5개 법률 순서
const rootsOf = (laws) => laws.filter((l) => !l.parent).sort((x, y) => (LAW_ORDER.indexOf(x.slug) + 99) % 99 - (LAW_ORDER.indexOf(y.slug) + 99) % 99);

function lawSwitch(laws, current) {
  return `<nav class="law-switch" aria-label="법률 선택">${rootsOf(laws).map((r) =>
    `<a href="#/laws/${r.slug}" aria-current="${r.slug === current}">${esc(LAW_SHORT[r.name] || r.name)}</a>`).join("")}</nav>`;
}

function viewLawIndex(laws) {
  const roots = rootsOf(laws);
  view.innerHTML = `
  <div class="page-h"><div><h1>법령</h1>
    <div class="sub">1단계 대상 ${roots.length}개 법률과 하위법령 ${laws.length - roots.length}건 · 추후 확대 예정</div></div></div>
  ${roots.map((r) => {
    const fam = laws.filter((l) => l.slug === r.slug || l.parent === r.slug);
    const arts = fam.reduce((s, f) => s + (f.articles || 0), 0), links = fam.reduce((s, f) => s + (f.linked_docs || 0), 0);
    return `<section class="card sec law-group">
      <div class="sec-h"><h2>${I("book")} ${esc(r.name)}</h2><span class="faint" style="font-size:12.5px">법령 ${fam.length}건 · 조문 ${arts.toLocaleString()}개 · 연결 ${links.toLocaleString()}건</span></div>
      <div class="family">${fam.map((f) => `<a class="fam" href="#/laws/${f.slug}">
        <span class="lv">${tierShort[f.kind] || "·"}</span><div><b>${esc(f.name)}</b><span>${esc(f.kind)} · ${f.articles ?? "-"}조 · 연결 ${f.linked_docs ?? 0}건</span></div></a>`).join("")}</div>
    </section>`;
  }).join("")}`;
}

async function viewLaws(slug) {
  view.innerHTML = skeleton(4);
  const laws = await api.laws();
  if (!slug) return viewLawIndex(laws);
  const t = await api.toc(slug);
  const lvl = tierShort;
  const total = t.chapters.reduce((s, c) => s + c.articles.length, 0);
  const cnt = (k, n) => (n ? `<span class="cnt" data-k="${k}" title="${k} ${n}건">${I(KI(k))}${n}</span>` : "");
  view.innerHTML = `
  ${lawSwitch(laws, rootOf(laws, slug))}
  <div class="page-h"><div><h1>${esc(t.law.name)}</h1>
    <div class="sub">${esc(t.law.kind)} · ${total}개 조문 · 시행 ${fmt(t.law.effective_on)}</div></div></div>
  <div class="family">${t.family.map((f) => {
    const L = laws.find((x) => x.slug === f.slug) || {};
    return `<a class="fam" href="#/laws/${f.slug}" aria-current="${f.slug === slug}">
      <span class="lv">${lvl[f.kind] || "·"}</span><div><b>${esc(f.name)}</b><span>${esc(f.kind)} · ${L.articles ?? "-"}조 · 연결 ${L.linked_docs ?? 0}건</span></div></a>`;
  }).join("")}</div>
  <div class="toc-legend"><span>조문 옆 숫자 = 그 조문에 연결된 자료 수</span>
    ${["법령해석", "비조치의견", "행정지도"].map((k) => `<span data-k="${k}">${kchip(k)}</span>`).join("")}
    <span class="tag pending">${I("pending", "s")} 시행 예정</span></div>
  ${t.chapters.map((c, i) => {
    const linked = c.articles.reduce((s, a) => s + a.total, 0);
    return `<section class="card chapter" data-open="${i < 2 || linked > 0}">
      <button>${I("chev", "chev")}<span>${esc(c.name || "본문")}</span><span class="n">${c.articles.length}개 조문${linked ? ` · 연결 ${linked}건` : ""}</span></button>
      <div class="rows">${c.articles.map((a) => `
        <a class="trow ${a.is_deleted ? "del" : ""}" href="${aLink(a.key)}">
          <span class="lb">${esc(a.label)}</span>
          <span>${esc(a.title || "")} ${a.pending ? `<span class="tag pending">${I("pending", "s")} 개정·신설 예정</span>` : ""}</span>
          <span class="counts">${cnt("법령해석", a.interp)}${cnt("비조치의견", a.noaction)}${cnt("행정지도", a.guidance)}${cnt("입법예고", a.notice)}</span>
        </a>`).join("")}</div>
    </section>`;
  }).join("")}`;
  view.querySelectorAll(".chapter > button").forEach((b) => b.onclick = () => {
    const s = b.parentElement; s.dataset.open = s.dataset.open !== "true";
  });
}

/* ============================================================ 화면: 조문 상세 */
function formatBody(body, label, title) {
  let text = body.replace(new RegExp("^" + label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\s*\\([^)]*\\)\\s*"), "");
  return text.split("\n").map((ln) => {
    const cls = /^\d+(의\d+)?\.\s/.test(ln) ? "ho" : /^[가-하]\.\s/.test(ln) ? "mok" : "";
    const h = ln.replace(/(<[^<>]*(개정|신설|삭제|전문개정|본조신설|제목개정)[^<>]*>|\[[^\]]*(개정|신설|본조신설|제목개정)[^\]]*\])/g, (m) => `\u0001${m}\u0002`);
    return `<p class="${cls}">${esc(h).replace(/\u0001/g, '<span class="hist">').replace(/\u0002/g, "</span>")}</p>`;
  }).join("");
}

function wordDiff(a, b) {
  const A = a.split(/(\s+)/), B = b.split(/(\s+)/);
  const n = A.length, m = B.length;
  if (n * m > 1_500_000) return null;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { out.push(["=", A[i]]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push(["-", A[i++]]);
    else out.push(["+", B[j++]]);
  }
  while (i < n) out.push(["-", A[i++]]);
  while (j < m) out.push(["+", B[j++]]);
  return out;
}
function diffHtml(cur, pend) {
  const d = wordDiff(cur, pend);
  if (!d) return null;
  // 같은 종류가 이어지는 토큰을 한 덩어리로 묶어 표시 (단어마다 끊겨 보이지 않게)
  const runs = [];
  d.forEach(([op, s]) => {
    const last = runs[runs.length - 1];
    if (last && (last[0] === op || (/^\s+$/.test(s) && op !== "="))) last[1] += s; else runs.push([op, s]);
  });
  return runs.map(([op, s]) => {
    const e = esc(s).replace(/\n/g, "</p><p>");
    return op === "=" ? e : op === "+" ? `<ins>${e}</ins>` : `<del>${e}</del>`;
  }).join("");
}

async function viewArticle(key) {
  view.innerHTML = skeleton(3);
  let a;
  try { a = await api.article(key); } catch { return notFound("조문"); }
  const s = a.stats;
  const max = Math.max(1, s.interp, s.noaction, s.guidance, s.notice);
  const versions = [a.current && ["cur", "현행", a.current.effective_from], a.pending && ["pend", "시행 예정", a.pending.effective_from]].filter(Boolean);
  let mode = a.current ? "cur" : "pend";
  const isWatched = watch.has(key);
  const lawUrl = ADMIN_RULE.has(a.law_kind) ? `https://www.law.go.kr/행정규칙/${encodeURIComponent(a.law_name.replace(/\s/g, ""))}`
    : `https://www.law.go.kr/법령/${encodeURIComponent(a.law_name.replace(/\s/g, ""))}/${encodeURIComponent(a.label)}`;
  const groups = ["법령해석", "비조치의견", "행정지도", "입법예고", "규정변경예고"].map((k) => [k, a.documents.filter((d) => d.kind === k)]).filter(([, l]) => l.length);
  const parentRoot = a.law_parent || a.law_slug;
  view.innerHTML = `
  <nav class="crumb"><a href="#/laws/${parentRoot}">${I("book", "s")} 법령</a>${I("chev")}<a href="#/laws/${a.law_slug}">${esc(a.law_name)}</a>
    ${a.chapter ? `${I("chev")}<span>${esc(a.chapter)}</span>` : ""}</nav>
  <section class="card map-sec" style="margin:0 0 22px">
    <div class="sec-h"><h2>${I("tree")} 연결 지도 <span class="faint" style="font-weight:500;font-size:13.5px">${esc(a.label)} ${esc(a.title || "")}</span></h2><span class="faint" style="font-size:12.5px">상자를 누르면 그 조문·문서로 이동</span></div>
    <div id="graph"><div class="skeleton" style="height:220px"></div></div>
    <div class="map-legend">
      <span><span class="ln"></span>위임 (위 → 아래)</span>
      ${["법령해석", "비조치의견", "행정지도", "입법예고"].map((k) => `<span data-k="${k}"><span class="ln" style="border-color:var(--k)"></span>${k === "입법예고" ? "예고" : k} 인용</span>`).join("")}
      <span>· 그림은 API 응답(<code>/articles/{key}/graph</code>)으로 자동 생성</span>
    </div>
  </section>
  <div class="art-layout">
    <div>
      <article class="card">
        <div class="art-head">
          <div class="row"><span class="tag brand">${esc(a.law_kind)}</span><span class="faint" style="font-size:13.5px">${esc(a.law_name)}</span>
            <span style="margin-left:auto;display:flex;gap:8px">
              <button class="btn sm star-btn" id="star" aria-pressed="${isWatched}">${I("star", "s")} ${isWatched ? "관심 조문" : "관심 등록"}</button>
              <a class="btn sm" href="${lawUrl}" target="_blank" rel="noopener">원문 ${I("ext", "s")}</a>
            </span></div>
          <h1><span class="lb">${esc(a.label)}</span>${esc(a.title || "")}</h1>
          ${!a.current && a.pending ? `<div class="notice-bar" style="margin-top:12px">${I("pending")}<span><b>${fmt(a.pending.effective_from)} 시행 예정인 신설 조문</b>입니다. 아직 효력이 없습니다.</span></div>` : ""}
          ${versions.length > 1 ? `<div class="row" style="margin-top:14px">
            <div class="seg" id="seg">${versions.map(([v, l, d]) => `<button data-v="${v}" aria-pressed="${v === mode}">${v === "pend" ? I("pending", "s") : ""}${l} <span class="faint num">${fmt(d)}~</span></button>`).join("")}
              <button data-v="diff" aria-pressed="false">${I("amend", "s")} 바뀌는 부분</button></div></div>` : ""}
        </div>
        <div id="diffLegend"></div>
        <div class="body-text" id="body"></div>
      </article>
      <section class="card docs-sec">
        <div class="sec-h"><h2>${I("link")} 이 조문을 다룬 자료 <span class="faint" style="font-weight:500">${a.documents.length}</span></h2>
          <div class="tabs" id="dtabs">${groups.length > 1 ? `<button class="pill" data-g="" aria-pressed="true">전체</button>` + groups.map(([k, l]) => `<button class="pill" data-g="${k}" aria-pressed="false">${k} <span class="n">${l.length}</span></button>`).join("") : ""}</div></div>
        <div id="dlist"></div>
      </section>
      <div class="pager">${a.neighbors.map((n) => `<a class="card hover" href="${aLink(n.key)}"><span class="faint">${n.key < a.key ? "← 이전" : "다음 →"}</span><b>${esc(n.label)} ${esc(n.title || "")}</b></a>`).join("")}</div>
    </div>
    <aside class="side">
      <div class="card"><h3>${I("layers", "s")} 연결된 자료</h3>
        <div class="kbars">${[["법령해석", s.interp], ["비조치의견", s.noaction], ["행정지도", s.guidance], ["입법예고", s.notice]].map(([k, n]) => `
          <div class="kbar" data-k="${k}"><span class="ic">${I(KI(k))}</span>
            <div><div style="display:flex;justify-content:space-between"><span>${k === "입법예고" ? "입법·규정변경예고" : k}</span><b class="num">${n}</b></div>
            <div class="track"><div class="fill" style="width:${(n / max) * 100}%"></div></div></div></div>`).join("")}</div>
      </div>
      ${a.delegates_to.length || a.delegated_from.length ? `<div class="card"><h3>${I("tree", "s")} ${a.delegated_from.length ? "근거·위임 관계" : "위임된 하위 규정"}</h3>
        <div class="deleg">
          ${a.delegated_from.map((d) => `<a href="${aLink(d.key)}"><span class="lv">↑ ${tierShort[d.law_kind] || ""}</span><b>${esc(d.label)}</b><span>${esc(d.title || "")}</span></a>`).join("")}
          ${a.delegates_to.map((d) => `<a href="${aLink(d.key)}"><span class="lv">↓ ${tierShort[d.law_kind] || ""}</span><b>${esc(d.label)}</b><span>${esc(d.title || "")}</span></a>`).join("")}
        </div>
        <p class="faint" style="font-size:12px;margin-top:10px">${a.delegates_to.some((d) => d.origin === "thdcmp") ? "법제처 3단비교 기준" : "하위 규정 본문의 ‘법 제N조’ 인용으로 추정한 관계"}</p></div>` : ""}
      <div class="card"><h3>${I("clock", "s")} 이 조문의 변화</h3>
        <div class="mini-tl">${a.events.map((e) => `<div><time>${fmt(e.occurred_on)}</time><a href="${e.doc_id ? dLink(e.doc_id) : "#"}">${esc((EV[e.kind] || [, e.kind])[1])} · ${esc(e.title.slice(0, 34))}${e.title.length > 34 ? "…" : ""}</a></div>`).join("") || '<p class="faint" style="font-size:13px">기록된 변화가 없습니다.</p>'}
        ${a.history.length ? `<div><time>본문 이력</time><span>${a.history.map((h) => fmt(h.effective_from) + "~").join(" → ")}</span></div>` : ""}</div>
      </div>
    </aside>
  </div>`;
  const paint = () => {
    const legend = $("#diffLegend");
    if (mode === "diff") {
      const h = diffHtml(a.current.body, a.pending.body);
      $("#body").innerHTML = h ? `<p>${h}</p>` : formatBody(a.pending.body, a.label);
      legend.innerHTML = `<div class="diff-legend"><span><ins style="background:color-mix(in srgb,var(--t-interp) 22%,transparent);text-decoration:none">추가</ins></span><span><del style="color:var(--t-notice)">삭제</del></span><span>${fmt(a.current.effective_from)} 현행 → ${fmt(a.pending.effective_from)} 시행본</span></div>`;
    } else {
      const v = mode === "pend" ? a.pending : a.current;
      $("#body").innerHTML = formatBody(v.body, a.label);
      legend.innerHTML = "";
    }
  };
  paint();
  // 연결 지도: 그래프 API 응답으로 그림을 그리고, 창 크기가 바뀌면 다시 그린다
  api.graph(key).then((g) => {
    const el = $("#graph"); if (!el) return;
    renderGraph(el, g);
    clearTimeout(viewArticle.rz);
    window.onresize = () => { clearTimeout(viewArticle.rz); viewArticle.rz = setTimeout(() => $("#graph") && renderGraph($("#graph"), g), 150); };
  }).catch(() => { const el = $("#graph"); if (el) el.innerHTML = '<p class="faint" style="font-size:13.5px">연결 지도를 불러오지 못했습니다.</p>'; });
  $("#seg")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-v]"); if (!b) return;
    mode = b.dataset.v; $("#seg").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b)); paint();
  });
  const renderDocs = (g) => {
    const list = a.documents.filter((d) => !g || d.kind === g);
    $("#dlist").innerHTML = list.map((d) => `
      <a class="doc-row" href="${dLink(d.id)}" data-k="${esc(d.kind)}">${kicon(d.kind)}
        <div style="min-width:0">
          <div class="meta" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:12.5px;color:var(--ink-3)">${kchip(d.kind)}<span>${esc(d.dept || d.org)}</span><span class="num">${fmt(d.published_on)}</span>
            ${d.paragraphs?.length ? `<span class="tag">제${d.paragraphs.join("·")}항</span>` : ""}</div>
          <h4 style="margin-top:6px">${esc(d.title)}</h4>
          <span class="evid">${I("link", "s")} “${esc(d.evidence[0])}” <span class="conf">${Math.round(d.confidence * 100)}%</span></span>
        </div></a>`).join("") || `<div class="empty" style="padding:24px">${ILLUS.emptySearch()}<b>아직 이 조문을 인용한 자료가 없습니다</b></div>`;
  };
  renderDocs("");
  $("#dtabs").onclick = (e) => {
    const b = e.target.closest("[data-g]"); if (!b) return;
    $("#dtabs").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b)); renderDocs(b.dataset.g);
  };
  $("#star").onclick = () => {
    const on = watch.toggle({ key, label: a.label, title: a.title, law_name: a.law_name });
    $("#star").setAttribute("aria-pressed", on);
    $("#star").innerHTML = `${I("star", "s")} ${on ? "관심 조문" : "관심 등록"}`;
    toast(on ? "관심 조문에 추가했어요. 새 변화가 홈에 모입니다" : "관심 조문에서 뺐어요");
  };
}

/* ============================================================ 화면: 문서 상세 */
async function viewDocument(id) {
  view.innerHTML = skeleton(3);
  let d;
  try { d = await api.document(id); } catch { return notFound("문서"); }
  const isDemo = /예시/.test(d.source_name);
  // 인용 근거 표현을 본문에서 찾아 조문 링크로 감싼다 (긴 표현부터)
  const evs = [...new Map(d.links.map((l) => [l.evidence, l])).values()].sort((x, y) => y.evidence.length - x.evidence.length);
  const linkify = (txt) => {
    if (!txt) return "";
    let h = esc(txt);
    const slots = [];
    evs.forEach((l, i) => {
      const e = esc(l.evidence);
      if (h.includes(e)) h = h.split(e).join(`\u0000${i}\u0000`);
      slots[i] = `<a class="cite" href="${aLink(l.key)}" title="${esc(l.law_name)} ${esc(l.label)} · ${methodLabel[l.method] || l.method}">${e}</a>`;
    });
    return h.replace(/\u0000(\d+)\u0000/g, (_, i) => slots[i]);
  };
  const sec = (cls, mark, title, txt) => (txt ? `<section class="${cls}"><h3><span class="qmark">${mark}</span>${title}</h3><div class="txt">${linkify(txt)}</div></section>` : "");
  const uniq = [...new Map(d.links.map((l) => [l.key, l])).values()];
  view.innerHTML = `
  <nav class="crumb"><a href="#/search">${I("search", "s")} 검색</a>${I("chev")}<span>${esc(d.kind)}</span></nav>
  <div class="art-layout">
    <article class="card" data-k="${esc(d.kind)}">
      <div class="doc-head">
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">${kchip(d.kind)}${isDemo ? `<span class="tag line">${I("info", "s")} 예시 데이터</span>` : ""}</div>
        <h1>${esc(d.title)}</h1>
        <div class="doc-meta"><span>${I("user", "s")} ${esc(d.org)}${d.dept ? " · " + esc(d.dept) : ""}</span>
          <span class="num">${I("clock", "s")} ${d.kind === "행정지도" || /예고/.test(d.kind) ? "공고" : "회신"} ${fmt(d.published_on)}</span>
          ${d.valid_to ? `<span class="num">${I("hourglass", "s")} ${d.kind === "행정지도" ? "존속기간" : "의견제출"} ${fmt(d.valid_from)} ~ ${fmt(d.valid_to)}${days(d.valid_to) >= 0 ? ` <b class="dday">D-${days(d.valid_to)}</b>` : " (종료)"}</span>` : ""}</div>
      </div>
      <div class="qa">
        ${sec("", "Q", "질의요지", d.question)}${sec("ans", "A", "회답", d.answer)}${sec("", "≡", "이유", d.reason)}${sec("", "≡", "주요 내용", d.body)}
      </div>
      <div class="src-box">${I("globe")}<div>출처: <b>${esc(d.source_name)}</b> · 원문은 변경 없이 표시하며, 연결된 조문(밑줄)은 자동 추출 결과입니다.
        <a href="${esc(d.source_url)}" target="_blank" rel="noopener" style="color:var(--brand-2);font-weight:650"> 원문 보기 ${I("ext", "s")}</a></div></div>
    </article>
    <aside class="side">
      <div class="card"><h3>${I("article", "s")} 인용한 조문 <span class="faint" style="font-weight:500">${uniq.length}</span></h3>
        ${uniq.map((l) => `<a class="link-card" href="${aLink(l.key)}">
          <div class="top"><span class="tag">${esc(l.law_kind)}</span><b>${esc(l.label)}</b><span class="faint" style="font-size:12.5px">${esc(l.title || "")}</span></div>
          <div class="ev">“${esc(l.evidence)}” · ${methodLabel[l.method] || l.method} <span class="conf">${Math.round(l.confidence * 100)}%</span></div>
        </a>`).join("") || '<p class="faint" style="font-size:13px">본문에서 조문 인용을 찾지 못했습니다.</p>'}
      </div>
      ${d.related.length ? `<div class="card"><h3>${I("link", "s")} 같은 조문을 다룬 자료</h3>
        ${d.related.map((r) => `<a class="link-card" href="${dLink(r.id)}" data-k="${esc(r.kind)}"><div class="top">${kchip(r.kind)}<span class="faint num" style="font-size:12px">${fmt(r.published_on)}</span></div>
          <b style="font-size:13.5px;line-height:1.45">${esc(r.title)}</b><div class="ev">공유 조문: ${r.via.map(esc).join(", ")}</div></a>`).join("")}</div>` : ""}
    </aside>
  </div>`;
}

/* ============================================================ 화면: 행정지도 */
async function viewGuidance(params) {
  const tab = params.get("tab") || "active";
  view.innerHTML = skeleton(2);
  const r = await api.guidance(tab);
  const t = today();
  const card = (g) => {
    const s = g.valid_from || t, e = g.valid_to;
    const total = e ? Math.max(1, (new Date(e) - new Date(s)) / 864e5) : 1;
    const pos = e ? Math.min(100, Math.max(0, ((new Date(t) - new Date(s)) / 864e5 / total) * 100)) : 0;
    const left = e ? days(e) : null;
    const status = g.stage === "예고" ? [I("notice"), "예고 중 · 의견 접수"] : left !== null && left <= 60 ? [I("hourglass"), `만료 ${left}일 전`] : [I("check"), "시행 중"];
    return `<a class="card hover g-card" href="${dLink(g.id)}" data-k="행정지도">
      <div class="g-top">${kchip("행정지도", g.stage === "예고" ? "행정지도 예고" : "행정지도")}<span class="status">${status[0]} ${status[1]}</span></div>
      <h3>${esc(g.title)}</h3>
      <div class="faint" style="font-size:13px">${esc(g.org)} · ${esc(g.dept || "")}</div>
      ${e ? `<div class="period" aria-label="${fmt(s)}부터 ${fmt(e)}까지 중 오늘 위치">
        <div class="bar"><div class="fill" style="width:${pos}%"></div><div class="today" style="left:calc(${pos}% - 1px)"></div></div>
        <div class="ends"><span class="num">${fmt(s)}</span><span>오늘</span><span class="num">${fmt(e)}</span></div></div>` : ""}
    </a>`;
  };
  view.innerHTML = `
  <div class="page-h"><div><h1>행정지도 현황</h1><div class="sub">금융위원회 행정지도는 존속기간이 있어, 지금 효력이 있는지가 중요합니다.</div></div>
    <div class="tabs">${[["active", "시행 중"], ["expiring", "60일 내 만료"], ["notice", "예고"]].map(([v, l]) => `<a class="pill ${v === tab ? "on" : ""}" href="#/guidance?tab=${v}">${l}</a>`).join("")}</div></div>
  <div class="g-grid">${r.items.map(card).join("") || `<div class="card empty" style="grid-column:1/-1">${ILLUS.emptySearch()}<b>해당하는 행정지도가 없습니다</b></div>`}</div>
  <p class="faint" style="font-size:12.5px;margin-top:16px">막대 = 존속기간, 세로선 = 오늘. 금융감독원 행정지도는 수집 범위를 순차 확대할 예정입니다.</p>`;
}

/* ============================================================ 화면: 관심 조문 */
async function viewWatch() {
  const w = watch.all();
  if (!w.length) {
    view.innerHTML = `<div class="page-h"><div><h1>관심 조문</h1></div></div>
      <div class="card empty">${ILLUS.emptyStar()}<b>등록한 관심 조문이 없습니다</b>
      조문 화면에서 ☆ 관심 등록을 누르면, 그 조문의 개정·시행 예정과 새 해석·비조치의견·행정지도가 여기에 모입니다.<br><br>
      <a class="btn primary" href="#/laws">${I("book", "s")} 법령 목차로 가기</a></div>`;
    return;
  }
  view.innerHTML = skeleton(3);
  const f = await api.feed({ days: 730, articles: w.map((x) => x.key), limit: 100 });
  view.innerHTML = `
  <div class="page-h"><div><h1>관심 조문</h1><div class="sub">이 브라우저에만 저장됩니다 · 로그인 없이 동작</div></div></div>
  <div class="grid-2">
    <section class="card sec"><div class="sec-h"><h2>${I("bell")} 관심 조문의 변화</h2></div>
      ${f.items.filter((e) => e.occurred_on <= today()).map(feedItem).join("") || '<p class="faint" style="padding:10px 0 20px">기록된 변화가 없습니다.</p>'}
      ${f.items.some((e) => e.occurred_on > today()) ? `<div class="sec-h" style="margin-top:12px"><h2>${I("pending")} 다가오는 시행</h2></div>${f.items.filter((e) => e.occurred_on > today()).map(feedItem).join("")}` : ""}
    </section>
    <section class="card sec"><div class="sec-h"><h2>${I("star")} 등록한 조문 ${w.length}</h2></div>
      <div class="deleg" style="padding-bottom:16px">${w.map((x) => `<a href="${aLink(x.key)}"><b>${esc(x.label)}</b><span>${esc(x.law_name)} · ${esc(x.title || "")}</span></a>`).join("")}</div>
    </section>
  </div>`;
}

/* ============================================================ 화면: 데이터 분석 (과제 필수 페이지) */
const METHOD_KO = { explicit: "법령명 명시", abbr: "약칭", defined: "문서 내 약칭", same_law: "같은 법·조", this_law: "이 법",
  parent_ref: "모법·하위규정 지칭", title: "제목형 표기", inferred: "문맥 추정", manual: "수동 검수" };
const REASON_KO = { unknown_law: "대상 밖 법령", unknown_article: "없는 조문 번호", article_not_loaded: "본문 미적재", ambiguous: "모호" };

async function viewInsights() {
  view.innerHTML = skeleton(4);
  const a = await api.analysis();
  const t = a.totals, lq = a.link_quality, g = a.guidance;
  const pct = (x) => (x == null ? "-" : `${Math.round(x * 1000) / 10}%`);
  const tile = (k, ic, v, unit, c, s) => `<div class="card kpi" data-k="${k}"><div class="top-row">${k === "조문" ? `<span class="kicon">${I(ic)}</span>` : kicon(k)}</div>
    <div class="v num">${v}<small>${unit}</small></div><div><div class="c">${c}</div><div class="s">${s}</div></div></div>`;
  view.innerHTML = `
  <div class="page-h"><div><h1>데이터 분석</h1>
    <div class="sub">이 서비스가 수집한 데이터가 무엇이고, 무엇을 알려 주는지 정리했습니다. 모든 수치는 <code>GET /analysis</code> 응답입니다.</div></div></div>
  <section class="kpis">
    ${tile("법령해석", "interp", (t.documents || 0).toLocaleString(), "건", "수집·정규화한 문서", `회신일 ${fmt(t.first_reply)} ~ ${fmt(t.last_reply)}`)}
    ${tile("조문", "article", (t.articles || 0).toLocaleString(), "개", `법령 ${t.laws}건의 조문`, `시행예정 본문 ${t.pending_versions}개`)}
    ${tile("조문", "tree", (t.delegations || 0).toLocaleString(), "건", "위임 관계 (법→령→규→세칙)", "법→령·규칙은 법제처 3단비교, 그 아래는 본문 인용으로 추출")}
    ${lq.in_scope ? tile("비조치의견", "link", pct(lq.in_scope.rate), "", "대상 법령 언급 회신의 조문 연결률", `${lq.in_scope.linked.toLocaleString()} / ${lq.in_scope.docs.toLocaleString()}건 · 전체 회신 기준 ${pct(lq.rate)}`)
      : tile("비조치의견", "link", pct(lq.rate), "", "조문에 연결된 회신 비율", `${(lq.linked || 0).toLocaleString()} / ${(lq.docs || 0).toLocaleString()}건 · 링크 ${(t.links || 0).toLocaleString()}개`)}
  </section>
  ${a.scope ? `<section class="card sec scope" style="margin-bottom:22px"><div class="sec-h"><h2>${I("book")} 분석 범위 · ${a.scope.phase}단계</h2><span class="faint" style="font-size:12.5px">추후 확대 예정</span></div>
    <div class="chips" style="margin:0 0 10px">${a.law_structure.map((l) => `<a class="tag" href="#/laws/${l.slug}"><b>${esc(l.name)}</b></a>`).join("")}</div>
    <p class="muted" style="font-size:13.5px;margin:0 0 8px">${esc(a.scope.note)} 대상 법령을 언급하지 않은 회신 ${((lq.docs || 0) - (lq.in_scope?.docs || 0)).toLocaleString()}건(대부업·신용정보·여신 등)은 수집은 해 두었고, 조문 연결은 범위를 넓히면 다시 계산됩니다.</p>
    <p class="faint" style="font-size:12.5px;margin:0 0 16px">2단계 후보: ${a.scope.next.map(esc).join(" · ")}</p></section>` : ""}

  <section class="card sec" style="margin-bottom:22px"><div class="sec-h"><h2>${I("globe")} 수집한 데이터와 출처</h2></div>
    <div class="tbl-x"><table class="tbl">
      <tr><th>데이터</th><th>제공 기관</th><th>수집 방식</th><th>수집 항목</th><th class="num">수집 건수</th><th>마지막 수집</th></tr>
      ${a.sources.map((s) => `<tr><td><b>${esc(s.name)}</b><br><a class="faint" href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a></td>
        <td>${esc(s.provider)}</td><td>${esc(s.method)}</td><td>${esc(s.items)}</td><td class="num">${(s.collected || 0).toLocaleString()}</td>
        <td class="num">${s.last_fetched ? fmt(s.last_fetched) : "-"}</td></tr>`).join("")}
    </table></div>
    ${t.portal_listed_total ? `<p class="faint" style="font-size:12.5px;margin:10px 0 14px">포털 목록 기준 전체 회신사례 ${t.portal_listed_total.toLocaleString()}건 (현장건의 과제 등 범위 밖 유형 포함)</p>` : '<div style="height:12px"></div>'}
  </section>

  <div class="grid-2 ins">
    <section class="card sec"><div class="sec-h"><h2>${I("clock")} 연도별 회신사례</h2><span class="faint" style="font-size:12.5px">회신일(포털 등록일) 기준</span></div>
      ${stackedCols(a.replies_by_year, [["interp", "법령해석", "--t-interp"], ["noaction", "비조치의견", "--t-noact"]])}
      ${(() => {
        const tot = a.replies_by_year.map((r) => (r.interp || 0) + (r.noaction || 0));
        const med = [...tot].sort((x, y) => x - y)[Math.floor(tot.length / 2)] || 0;
        const spikes = a.replies_by_year.filter((r, i) => med && tot[i] > med * 3).map((r) => r.year);
        return spikes.length ? `<p class="faint" style="font-size:12.5px;margin:-4px 0 14px">${spikes.join("·")}년은 다른 해의 3배 이상입니다. 날짜가 포털 등록일이라 과거 회신을 한꺼번에 등록한 영향으로 보입니다(추정).</p>` : "";
      })()}</section>
    <section class="card sec"><div class="sec-h"><h2>${I("user")} 소관부서 상위</h2></div>
      ${hbars(a.replies_by_dept.map((d) => ({ label: d.dept, value: d.n })))}</section>
  </div>
  <div class="grid-2 ins">
    <section class="card sec"><div class="sec-h"><h2>${I("book")} 많이 인용된 법령</h2><span class="faint" style="font-size:12.5px">하위법령 인용은 모법으로 합산</span></div>
      ${hbars(a.top_laws.map((l) => ({ label: l.name, value: l.docs, href: `#/laws/${l.slug}` })), { empty: "인용 연결이 아직 없습니다" })}</section>
    <section class="card sec"><div class="sec-h"><h2>${I("article")} 많이 인용된 조문</h2></div>
      ${hbars(a.top_articles.map((x) => ({ label: `${x.label} ${x.title || ""}`, sub: x.law_name, value: x.docs, href: aLink(x.key) })), { empty: "인용 연결이 아직 없습니다" })}</section>
  </div>
  <div class="grid-2 ins">
    <section class="card sec"><div class="sec-h"><h2>${I("link")} 인용 연결 품질</h2></div>
      <p class="muted" style="font-size:13.5px;margin-bottom:10px">연결 방법별 링크 수 — 위로 갈수록 확실한 표기</p>
      ${ratioBar(lq.by_method.map((m) => ({ label: METHOD_KO[m.method] || m.method, value: m.n })))}
      <p class="muted" style="font-size:13.5px;margin:18px 0 10px">연결하지 못한 인용 (버리지 않고 기록)</p>
      ${hbars(lq.unresolved.map((u) => ({ label: REASON_KO[u.reason] || u.reason, value: u.n })), { empty: "미해결 인용이 없습니다" })}
      ${lq.unknown_laws.length ? `<p class="muted" style="font-size:13.5px;margin:18px 0 8px">2단계 확대 후보 — 대상 밖 법령 인용 상위 (폐지된 옛 법령도 포함될 수 있음)</p>
        <div class="chips" style="margin:0 0 16px">${lq.unknown_laws.map((u) => `<span class="tag">${esc(u.name)} <b class="num">${u.n}</b></span>`).join("")}</div>` : ""}
    </section>
    <section class="card sec"><div class="sec-h"><h2>${I("guide")} 행정지도 현황</h2></div>
      <div class="mini-kpi">
        <div><b class="num">${g.active ?? 0}</b><span>시행 중</span></div><div><b class="num">${g.expiring_60 ?? 0}</b><span>60일 내 만료</span></div>
        <div><b class="num">${g.expired ?? 0}</b><span>존속기간 만료</span></div><div><b class="num">${g.notice ?? 0}</b><span>예고</span></div>
      </div>
      <p class="muted" style="font-size:13.5px;margin:6px 0 10px">평균 존속기간 ${g.avg_days ? `${g.avg_days}일 (약 ${Math.round(g.avg_days / 30)}개월)` : "-"} · 소관부서별</p>
      ${hbars((g.by_dept || []).map((d) => ({ label: d.dept, value: d.n })))}
    </section>
  </div>
  <section class="card sec" style="margin-top:22px"><div class="sec-h"><h2>${I("tree")} 법령 구조 (법률과 하위법령)</h2><span class="faint" style="font-size:12.5px">조문 수 · 위임 관계 · 시행 예정</span></div>
    <div class="tbl-x"><table class="tbl">
      <tr><th>법령</th><th class="num">법률</th><th class="num">시행령</th><th class="num">시행규칙</th><th class="num">감독규정·고시</th><th class="num">시행세칙</th><th class="num">위임 관계</th><th class="num">시행 예정 조문</th></tr>
      ${a.law_structure.map((l) => `<tr><td><a href="#/laws/${l.slug}"><b>${esc(l.name)}</b></a></td><td class="num">${l.law_articles}</td>
        <td class="num">${l.decree_articles}</td><td class="num">${l.rule_articles || "-"}</td><td class="num">${l.reg_articles || "-"}</td><td class="num">${l.detail_articles || "-"}</td><td class="num">${l.delegations.toLocaleString()}</td>
        <td class="num">${l.pending ? `<b>${l.pending}</b>` : "-"}</td></tr>`).join("")}
    </table></div><div style="height:16px"></div>
  </section>`;
  bindTips(view);
}

function notFound(what) {
  view.innerHTML = `<div class="card empty">${ILLUS.emptySearch()}<b>${what}을(를) 찾을 수 없습니다</b>주소가 바뀌었거나 아직 수집되지 않은 자료입니다.<br><br><a class="btn" href="#/">홈으로</a></div>`;
}

/* ============================================================ 라우터 */
const routes = [
  [/^#?\/?$/, () => viewHome(), "home"],
  [/^#\/search/, (m, p) => viewSearch(p), "search"],
  [/^#\/laws\/?([^?]*)/, (m) => viewLaws(decodeURIComponent(m[1] || "")), "laws"],
  [/^#\/a\/(.+)$/, (m) => viewArticle(decodeURIComponent(m[1])), "laws"],
  [/^#\/d\/(.+)$/, (m) => viewDocument(decodeURIComponent(m[1])), "search"],
  [/^#\/guidance/, (m, p) => viewGuidance(p), "guidance"],
  [/^#\/watch/, () => viewWatch(), "watch"],
  [/^#\/insights/, () => viewInsights(), "insights"],
];
async function route() {
  const h = location.hash || "#/";
  const [path, query] = h.split("?");
  const params = new URLSearchParams(query || "");
  for (const [re, fn, nav] of routes) {
    const m = path.match(re);
    if (m) {
      document.querySelectorAll(".nav a").forEach((a) => a.setAttribute("aria-current", a.dataset.nav === nav ? "page" : "false"));
      window.scrollTo(0, 0);
      try { await fn(m, params); } catch (e) { console.error(e); view.innerHTML = `<div class="card empty"><b>화면을 불러오지 못했습니다</b>${esc(e.message)}</div>`; }
      return;
    }
  }
  notFound("페이지");
}

/* ============================================================ 시작 */
$("#gform").onsubmit = (e) => { e.preventDefault(); const q = $("#gq").value.trim(); location.hash = `#/search?q=${encodeURIComponent(q)}`; };
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); $("#gq").focus(); }
});
$("#theme").onclick = () => {
  const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const nx = cur === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = nx;
  try { localStorage.setItem("finreg.theme", nx); } catch {}
};
document.addEventListener("api:fallback", () => {
  $("#modeBanner").hidden = false;
  $("#modeBanner").querySelector("span").textContent = "실시간 서버에 연결하지 못해, 저장된 데이터로 보여드리고 있습니다.";
});
if (api.mode === "static") $("#modeBanner").hidden = false;
window.addEventListener("hashchange", route);
updateBadge();
route();
