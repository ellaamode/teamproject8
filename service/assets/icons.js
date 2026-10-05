/* 픽토그램 세트 (24×24, 선 두께 1.8, 둥근 끝). <svg class="i"><use href="#i-interp"/></svg> 로 사용 */
(function () {
  const P = {
    // 문서 유형
    article: '<path d="M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M14 3v5h5"/><path d="M13.6 11.2c-.5-.6-1.3-.9-2.1-.8-1 .1-1.6.8-1.4 1.6.3 1.3 3.6 1.2 3.8 2.8.1.9-.7 1.7-1.8 1.8-.9.1-1.8-.3-2.2-1"/><path d="M10.4 13.6c-.6.5-.7 1.2-.3 1.7"/>',
    interp: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-4.2 3.6c-.5.4-1.3 0-1.3-.6V16A2.5 2.5 0 0 1 4 13.5z"/><path d="M10 8.2a2 2 0 1 1 2.8 1.8c-.5.2-.8.7-.8 1.2v.3"/><circle cx="12" cy="13.6" r=".4" fill="currentColor"/>',
    noact: '<path d="M12 3l7 2.8v5.4c0 4.4-3 8.1-7 9.8-4-1.7-7-5.4-7-9.8V5.8z"/><path d="M8.8 12.1l2.2 2.2 4.3-4.6"/>',
    guide: '<path d="M5 21V4"/><path d="M5 4.5c2.6-1.5 5.1 1.6 7.7.4 2-.9 3.6-.9 6.3.1v8.6c-2.7-1-4.3-1-6.3-.1-2.6 1.2-5.1-1.9-7.7-.4"/>',
    notice: '<path d="M3.5 10v4a1 1 0 0 0 1 1H7l7 4V5L7 9H4.5a1 1 0 0 0-1 1z"/><path d="M17.5 8.5a5 5 0 0 1 0 7"/><path d="M7 15l1.2 4.5"/>',
    // 변화
    pending: '<rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/><path d="M3.5 9.5h17M8 3v4M16 3v4"/><circle cx="15.5" cy="15.5" r="3"/><path d="M15.5 14.2v1.4l.9.8"/>',
    amend: '<path d="M7 3h7l5 5v5"/><path d="M6 3.5V20a1 1 0 0 0 1 1h4"/><path d="M18.6 14.6l1.8 1.8-5.1 5.1-2.4.6.6-2.4z"/>',
    hourglass: '<path d="M7 3h10M7 21h10"/><path d="M8 3v3.5a4 4 0 0 0 1.6 3.2L12 12l2.4-2.3A4 4 0 0 0 16 6.5V3"/><path d="M8 21v-3.5a4 4 0 0 1 1.6-3.2L12 12l2.4 2.3a4 4 0 0 1 1.6 3.2V21"/>',
    // 탐색
    home: '<path d="M4 10.5L12 4l8 6.5V19a1.5 1.5 0 0 1-1.5 1.5H15v-6h-6v6H5.5A1.5 1.5 0 0 1 4 19z"/>',
    book: '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z"/><path d="M4 20.5A2.5 2.5 0 0 0 6.5 23H20v-5"/><path d="M8.5 7.5h7M8.5 11h5"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    star: '<path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8L3.6 9.7l5.8-.8z"/>',
    bell: '<path d="M6 9.5a6 6 0 0 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15.5 6 9.5z"/><path d="M10 20.5a2.2 2.2 0 0 0 4 0"/>',
    tree: '<rect x="3" y="3.5" width="7" height="5" rx="1.5"/><rect x="14" y="9.5" width="7" height="5" rx="1.5"/><rect x="14" y="16" width="7" height="5" rx="1.5"/><path d="M6.5 8.5v4.5a2 2 0 0 0 2 2H14M6.5 12v6a1.5 1.5 0 0 0 1.5 1.5h6"/>',
    layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
    ext: '<path d="M14 4h6v6M20 4l-8.5 8.5"/><path d="M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    chev: '<path d="M9 6l6 6-6 6"/>',
    down: '<path d="M6 9l6 6 6-6"/>',
    x: '<path d="M6 6l12 12M18 6L6 18"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><circle cx="12" cy="7.8" r=".5" fill="currentColor"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6 6 6M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
    moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z"/>',
    filter: '<path d="M4 5h16M7 12h10M10 19h4"/>',
    spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/>',
    db: '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/><path d="M4.5 5.5v13c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8v-13"/><path d="M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
    server: '<rect x="3.5" y="4" width="17" height="7" rx="2"/><rect x="3.5" y="13" width="17" height="7" rx="2"/><path d="M7.5 7.5h.01M7.5 16.5h.01"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.4 2.4 3.5 5.2 3.5 8.5s-1.1 6.1-3.5 8.5c-2.4-2.4-3.5-5.2-3.5-8.5S9.6 5.9 12 3.5z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c1-4 4-6 7.5-6s6.5 2 7.5 6"/>',
    check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    shield: '<path d="M12 3l7 2.8v5.4c0 4.4-3 8.1-7 9.8-4-1.7-7-5.4-7-9.8V5.8z"/>',
    copy: '<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V5a1.5 1.5 0 0 0-1.5-1.5H5A1.5 1.5 0 0 0 3.5 5v9A1.5 1.5 0 0 0 5 15.5h3.5"/>',
    logo: '<path d="M12 3.5v17"/><path d="M5 7.5h14"/><path d="M5 7.5l-2.5 6a3 3 0 0 0 5 0z"/><path d="M19 7.5l-2.5 6a3 3 0 0 0 5 0z"/><path d="M8.5 20.5h7"/>',
  };
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">' +
    Object.entries(P).map(([k, v]) => `<symbol id="i-${k}" viewBox="0 0 24 24">${v}</symbol>`).join("") + "</svg>";
  document.body.insertAdjacentHTML("afterbegin", svg);
  window.icon = (name, cls = "") => `<svg class="i ${cls}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  window.KIND_ICON = { "법령해석": "interp", "비조치의견": "noact", "행정지도": "guide", "입법예고": "notice", "규정변경예고": "notice", "현장건의": "interp", "조문": "article" };
})();
