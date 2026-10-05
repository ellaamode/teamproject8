/* 가벼운 차트 부품 (라이브러리 없음). dataviz 원칙:
 *  - 막대는 얇고 끝만 둥글게, 값 라벨은 글자색(시리즈 색 아님), 계열이 2개 이상이면 범례 필수
 *  - 마우스를 올리면 툴팁, 모든 차트에 '표로 보기' 제공
 *  - 색: 단일 계열은 브랜드색, 해석/비조치는 검증된 유형색
 */
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n ?? 0).toLocaleString("ko-KR");

let tip;
function tooltip() {
  if (!tip) { tip = document.createElement("div"); tip.className = "ch-tip"; document.body.appendChild(tip); }
  return tip;
}
export function bindTips(root) {
  root.querySelectorAll("[data-tip]").forEach((el) => {
    el.addEventListener("mousemove", (e) => {
      const t = tooltip(); t.innerHTML = el.dataset.tip; t.style.opacity = 1;
      t.style.left = Math.min(e.clientX + 14, innerWidth - t.offsetWidth - 8) + "px"; t.style.top = e.clientY + 14 + "px";
    });
    el.addEventListener("mouseleave", () => { tooltip().style.opacity = 0; });
  });
}

const table = (head, rows) => `<details class="ch-table"><summary>표로 보기</summary><table><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>
  ${rows.map((r) => `<tr>${r.map((c, i) => `<td${i ? ' class="num"' : ""}>${typeof c === "number" ? fmt(c) : esc(c)}</td>`).join("")}</tr>`).join("")}</table></details>`;

/* 가로 막대 (단일 계열): items = [{label, sub, value, href}] */
export function hbars(items, { unit = "건", empty = "데이터가 없습니다" } = {}) {
  if (!items.length) return `<p class="faint ch-empty">${empty}</p>`;
  const max = Math.max(...items.map((i) => i.value), 1);
  return `<div class="hb">${items.map((i) => `
    <${i.href ? `a href="${i.href}"` : "div"} class="hb-row" data-tip="<b>${esc(i.label)}</b>${i.sub ? `<br>${esc(i.sub)}` : ""}<br>${fmt(i.value)}${unit}">
      <span class="hb-l"><b>${esc(i.label)}</b>${i.sub ? `<small>${esc(i.sub)}</small>` : ""}</span>
      <span class="hb-t"><span class="hb-f" style="width:${(i.value / max) * 100}%"></span></span>
      <span class="hb-v num">${fmt(i.value)}</span>
    </${i.href ? "a" : "div"}>`).join("")}</div>
    ${table(["항목", unit === "건" ? "건수" : unit], items.map((i) => [i.label + (i.sub ? ` (${i.sub})` : ""), i.value]))}`;
}

/* 세로 누적 막대 (연도별 해석/비조치): rows=[{year, a, b}], series=[[key,label,colorVar]] */
export function stackedCols(rows, series) {
  if (!rows.length) return '<p class="faint ch-empty">데이터가 없습니다</p>';
  const tot = (r) => series.reduce((s, [k]) => s + (r[k] || 0), 0);
  const max = Math.max(...rows.map(tot), 1);
  const legend = `<div class="ch-legend">${series.map(([, l, c]) => `<span><i style="background:var(${c})"></i>${esc(l)}</span>`).join("")}</div>`;
  return `${legend}<div class="sc" role="img" aria-label="연도별 건수">${rows.map((r) => `
    <div class="sc-col" data-tip="<b>${r.year}년</b>${series.map(([k, l]) => `<br>${esc(l)} ${fmt(r[k])}건`).join("")}<br>합계 ${fmt(tot(r))}건">
      <span class="sc-v num">${fmt(tot(r))}</span>
      <div class="sc-bar" style="height:${(tot(r) / max) * 100}%">${series.map(([k, , c]) => r[k] ? `<span style="flex:${r[k]};background:var(${c})"></span>` : "").join("")}</div>
      <span class="sc-x num">${String(r.year).slice(2)}</span>
    </div>`).join("")}</div>
    ${table(["연도", ...series.map(([, l]) => l), "합계"], rows.map((r) => [String(r.year), ...series.map(([k]) => r[k] || 0), tot(r)]))}`;
}

/* 비율 막대 (100% 누적): parts=[{label, value}] — 단계형 회색조 + 라벨 직접 표기 */
export function ratioBar(parts, total) {
  const sum = total || parts.reduce((s, p) => s + p.value, 0) || 1;
  return `<div class="rb-bar">${parts.map((p, i) => `<span data-tip="<b>${esc(p.label)}</b><br>${fmt(p.value)} (${Math.round((p.value / sum) * 100)}%)"
      style="flex:${p.value};opacity:${1 - i * 0.14}"></span>`).join("")}</div>
    <div class="rb-legend">${parts.map((p, i) => `<span><i style="opacity:${1 - i * 0.14}"></i>${esc(p.label)} <b class="num">${fmt(p.value)}</b></span>`).join("")}</div>`;
}
