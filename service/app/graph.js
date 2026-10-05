/* 조문 연결 지도: GET /articles/{key}/graph 응답(점·선 목록)을 SVG 그림으로 그린다.
 * 배치 규칙
 *  - 왼쪽: 조문을 계층별 가로줄로 (법률 → 시행령·시행규칙 → 감독규정·고시 → 시행세칙), 중심 조문은 진한 남색
 *  - 오른쪽: 중심 조문을 인용한 문서를 세로로, 유형 색 + 픽토그램 + 라벨
 *  - 위임 선은 위→아래 화살표, 인용 선은 문서 색. 선을 먼저 그려 상자 아래로 지나가게 한다
 *  - 점에 마우스를 올리면 연결된 선만 강조
 */
const TIER_NAME = ["법률", "시행령·규칙", "감독규정·고시", "시행세칙"];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cut = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + "…" : s || "");
const href = (n) => (n.type === "article" ? `#/a/${encodeURIComponent(n.id)}` : `#/d/${encodeURIComponent(n.id)}`);

export function renderGraph(el, g) {
  const arts = g.nodes.filter((n) => n.type === "article");
  const docs = g.nodes.filter((n) => n.type === "document");
  if (arts.length <= 1 && !docs.length) {
    el.innerHTML = `<p class="faint" style="font-size:13.5px;padding:8px 2px 4px">이 조문에는 아직 위임 관계나 인용한 자료가 없습니다.</p>`;
    return;
  }
  // 폭: 컨테이너 폭을 쓰되, 가장 긴 줄이 겹치지 않을 만큼은 확보(넘치면 가로 스크롤)
  const DOC_W = docs.length ? 250 : 0, GAP = docs.length ? 64 : 0, LABEL_W = 84, PAD = 16;   // 줄 이름 '감독규정·고시'가 들어갈 폭
  const MIN_W = 128, NGAP = 14, NODE_H = 58, ROW_GAP = 60, TOP = 18;
  const W = Math.max(el.clientWidth, LABEL_W + 3 * (MIN_W + NGAP) + GAP + DOC_W + PAD);
  const areaX = LABEL_W, areaW = W - LABEL_W - DOC_W - GAP - PAD;
  const perRow = Math.max(1, Math.floor((areaW + NGAP) / (MIN_W + NGAP)));

  // ---- 조문 배치: 계층별 줄(길면 여러 줄로 접음), 자식은 부모 아래쪽으로 오도록 정렬
  const tiers = [...new Set(arts.map((n) => n.tier))].sort((a, b) => a - b);
  const pos = {}, tierLabelY = [];
  const parentsOf = (id) => g.edges.filter((e) => e.type === "delegation" && e.to === id).map((e) => e.from);
  let y = TOP;
  tiers.forEach((t) => {
    const list = arts.filter((n) => n.tier === t);
    const bary = (n) => {
      const xs = parentsOf(n.id).map((p) => pos[p]?.cx).filter((x) => x !== undefined);
      return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : (n.center ? -1 : 1e9);
    };
    list.sort((a, b) => bary(a) - bary(b) || a.label.localeCompare(b.label, "ko", { numeric: true }));
    tierLabelY.push([t, y]);
    for (let i = 0; i < list.length; i += perRow) {
      const chunk = list.slice(i, i + perRow), n = chunk.length;
      const w = chunk.some((c) => c.center) ? Math.min(areaW, 260) : Math.min(190, (areaW - NGAP * (perRow - 1)) / Math.min(perRow, Math.max(n, 1)));
      const total = n * w + NGAP * (n - 1);
      const x0 = areaX + Math.max(0, (areaW - total) / 2);
      chunk.forEach((node, j) => {
        const x = x0 + j * (w + NGAP);
        pos[node.id] = { x, y, w, h: NODE_H, cx: x + w / 2, node };
      });
      y += NODE_H + (i + perRow < list.length ? 16 : ROW_GAP);
    }
  });
  const artBottom = y - ROW_GAP;

  // ---- 문서 배치: 오른쪽 세로 줄 (세로 가운데 맞춤)
  const DOC_H = 52, DOC_GAP = 12;
  const moreKinds = Object.entries(g.more || {});
  const docsH = docs.length * (DOC_H + DOC_GAP) - DOC_GAP + (moreKinds.length ? 26 : 0);
  const H = Math.max(artBottom, docsH) + TOP * 2;
  const dx = W - DOC_W - PAD;
  let dy = TOP + Math.max(0, (Math.max(artBottom, docsH) - docsH) / 2);
  docs.forEach((d) => { pos[d.id] = { x: dx, y: dy, w: DOC_W, h: DOC_H, node: d }; dy += DOC_H + DOC_GAP; });

  // ---- 선
  const lines = g.edges.map((e) => {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) return "";
    if (e.type === "delegation") {
      const x1 = a.cx, y1 = a.y + a.h, x2 = b.cx, y2 = b.y - 6, my = (y1 + y2) / 2;
      return `<path class="ge del" data-a="${esc(e.from)}" data-b="${esc(e.to)}" d="M${x1} ${y1} C${x1} ${my} ${x2} ${my} ${x2} ${y2}" marker-end="url(#gar)"><title>위임 (${e.origin === "thdcmp" ? "법제처 3단비교" : "본문 인용으로 추정"})</title></path>`;
    }
    // 인용: 조문 오른쪽 → 문서 왼쪽
    const x1 = b.x + b.w, y1 = b.y + b.h / 2, x2 = a.x, y2 = a.y + a.h / 2, mx = x1 + (x2 - x1) * 0.55;
    return `<path class="ge cit" data-k="${esc(a.node.kind)}" data-a="${esc(e.from)}" data-b="${esc(e.to)}" d="M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}"><title>인용 · 신뢰도 ${Math.round((e.confidence || 0) * 100)}%</title></path>`;
  }).join("");

  // ---- 상자
  const artBox = (p) => {
    const n = p.node, c = n.center, chars = Math.floor((p.w - 20) / 12.5);
    return `<a href="${href(n)}" class="gn ${c ? "center" : ""}" data-id="${esc(n.id)}">
      <title>${esc(n.law_name)} ${esc(n.label)} ${esc(n.title || "")}</title>
      <rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="12"/>
      <text x="${p.x + 11}" y="${p.y + 22}" class="t1">${esc(cut(c ? `${n.label} ${n.title || ""}` : n.label, chars))}</text>
      <text x="${p.x + 11}" y="${p.y + 41}" class="t2">${esc(cut(c ? n.law_name : n.title, chars + 2))}</text>
    </a>`;
  };
  const docBox = (p) => {
    const n = p.node;
    return `<a href="${href(n)}" class="gn doc" data-id="${esc(n.id)}" data-k="${esc(n.kind)}">
      <title>${esc(n.kind)} · ${esc(n.title)} (${esc(String(n.published_on).slice(0, 10))})</title>
      <rect x="${p.x}" y="${p.y}" width="${p.w}" height="${p.h}" rx="12"/>
      <rect x="${p.x + 10}" y="${p.y + 10}" width="32" height="32" rx="9" class="ic"/>
      <svg x="${p.x + 17}" y="${p.y + 17}" width="18" height="18" viewBox="0 0 24 24" class="icg"><use href="#i-${window.KIND_ICON[n.kind] || "article"}"/></svg>
      <text x="${p.x + 52}" y="${p.y + 21}" class="t3">${esc(n.kind)} · ${esc(String(n.published_on).slice(0, 7).replace("-", "."))}</text>
      <text x="${p.x + 52}" y="${p.y + 39}" class="t1 s">${esc(cut(n.title, 15))}</text>
    </a>`;
  };
  const labels = tierLabelY.map(([t, ty]) => `<text x="0" y="${ty + NODE_H / 2 + 4}" class="tier">${TIER_NAME[t] || ""}</text>`).join("");
  const more = moreKinds.length
    ? `<text x="${dx + 4}" y="${dy + 12}" class="t3">${moreKinds.map(([k, n]) => `${esc(k)} 외 ${n}건`).join(" · ")} — 아래 목록에서 전체 보기</text>` : "";

  el.innerHTML = `<div class="graph-scroll"><svg class="graph" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img"
      aria-label="조문 연결 지도: 조문 ${arts.length}개, 문서 ${docs.length}건">
    <defs><marker id="gar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M1 1L9 5L1 9" fill="none" stroke="var(--ink-3)" stroke-width="1.6"/></marker></defs>
    <g>${lines}</g>${labels}
    <g>${Object.values(pos).filter((p) => p.node.type === "article").map(artBox).join("")}</g>
    <g>${Object.values(pos).filter((p) => p.node.type === "document").map(docBox).join("")}</g>
    ${more}
  </svg></div>`;

  // 마우스를 올린 점과 연결된 선만 강조
  const svg = el.querySelector("svg");
  svg.querySelectorAll(".gn").forEach((a) => {
    const id = a.dataset.id;
    a.addEventListener("mouseenter", () => {
      svg.classList.add("focus");
      svg.querySelectorAll(".ge").forEach((p) => p.classList.toggle("on", p.dataset.a === id || p.dataset.b === id));
    });
    a.addEventListener("mouseleave", () => { svg.classList.remove("focus"); svg.querySelectorAll(".ge.on").forEach((p) => p.classList.remove("on")); });
  });
}
