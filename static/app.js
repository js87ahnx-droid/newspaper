/* ○월 ○일자 뉴스 — 쪽 나누기와 종이 넘김.
 *
 * 1. #flow 의 섹션·기사를 화면 크기에 맞춰 쪽(.page)으로 나눈다 (가로 화면은 좌우 두 쪽 펼침).
 * 2. page-flip(StPageFlip) 으로 손가락을 따라 넘어가게 한다. 동작 줄이기 설정이면 애니메이션 없이 넘긴다.
 * 3. 화면 회전·크기 변경·글자 크기 변경 때 다시 나눈다 (보던 기사 위치 유지).
 * 4. 한 면 보기(S16): 같은 쪽을 세로로 쌓아 한 쪽이 한 화면, 스크롤로 다음 쪽, 두 손가락·버튼으로 1~3배 줌.
 * 5. 전체화면(S16): 지원하면 Fullscreen API, 아니면 "홈 화면에 추가" 안내.
 */
(function () {
  "use strict";

  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 사생활 보호 모드 등 */ } }
  };

  var root = document.documentElement;
  var book = document.getElementById("book");
  var flow = document.getElementById("flow");
  var pageInfo = document.getElementById("pageInfo");
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var flip = null;      // StPageFlip 인스턴스 (동작 줄이기면 null)
  var pages = [];
  var current = 0;      // 현재 쪽 번호 (왼쪽 쪽 기준)
  var spread = true;    // 두 쪽 펼침 여부
  var overflowPages = [], clipped = 0;  // 쪽 나누기 때 잰 넘친 쪽·잘라 낸 기사 (검증용)
  var demotedCount = 0, briefCount = 0, dropped = 0, emptySummary = 0;  // 단신으로 내린 기사·단신 수·쪽이 모자라 못 실은 기사·요약 없는 기사
  var E = window.EDITION || {};
  var mode = "flip";    // flip: 펼침·종이 넘김 / scroll: 한 면 보기 (스크롤·줌)
  var zoom = 1;
  var scroller = null, sizer = null, zoomer = null, pageH = 0, pageW = 0;
  var ZMIN = 1, ZMAX = 3, GAP = 12;

  // ---------- 설정: 밝기·글자 크기 ----------
  function applyTheme(t) { root.setAttribute("data-theme", t); }
  applyTheme(store.get("theme", "auto"));
  var fontScale = parseFloat(store.get("fontScale", "1")) || 1;
  mode = store.get("viewMode", "flip") === "scroll" ? "scroll" : "flip";
  zoom = Math.max(1, Math.min(3, parseFloat(store.get("zoom", "1")) || 1));
  root.style.setProperty("--fs", fontScale);

  // ---------- 쪽 나누기 ----------
  function geometry() {
    var tb = document.getElementById("toolbar").getBoundingClientRect().height;
    var W = window.innerWidth, H = window.innerHeight - tb;
    spread = W > H && W >= 700;                // 가로 화면이면 두 쪽
    var pw = Math.floor(spread ? W / 2 : W);
    return { w: pw, h: Math.floor(H), W: W, H: H };
  }

  function newPage(g, sectionId, title, cont) {
    var p = document.createElement("div");
    p.className = "page sec-" + sectionId;
    p.style.width = g.w + "px";
    p.style.height = g.h + "px";
    var inner = document.createElement("div");
    inner.className = "page-inner";
    if (title) {
      var h = document.createElement("h2");
      h.className = "sec-title";
      h.textContent = title + (cont ? " (계속)" : "");
      inner.appendChild(h);
    }
    p.appendChild(inner);
    var foot = document.createElement("div");
    foot.className = "folio";
    p.appendChild(foot);
    return p;
  }

  function overflows(inner) { return inner.scrollHeight > inner.clientHeight + 1; }

  // 한 쪽보다 큰 기사: 리드 줄이기(compact) → 리드·점수 숨기기(tight) → 그래도 크면 쪽 높이에 맞춰 잘라 낸다(clip).
  // 잘라도 제목과 원문 링크는 위쪽에 남는다
  function fit(inner, node) {
    node.classList.add("compact");
    if (!overflows(inner)) return;
    node.classList.add("tight");
    if (!overflows(inner)) return;
    var room = inner.clientHeight - (node.offsetTop - inner.offsetTop) - 6;
    node.classList.add("clip");
    node.style.maxHeight = Math.max(80, room) + "px";
  }

  // 단신 꼴: 제목 + 한 줄 + 시각·매체 (정해진 쪽에 다 못 들어간 기사, 단신·예비 기사)
  function asBrief(el) {
    if (el.classList.contains("brief")) return el.cloneNode(true);
    var b = document.createElement("article");
    Array.prototype.forEach.call(el.attributes, function (a) { b.setAttribute(a.name, a.value); });
    b.className = "item brief demoted";
    var hl = el.querySelector(".hl");
    if (hl) b.appendChild(hl.cloneNode(true));
    var t = el.getAttribute("data-brief");
    if (t) { var p = document.createElement("p"); p.className = "lead brief-line"; p.textContent = t; b.appendChild(p); }
    var meta = el.querySelector(".meta");
    if (meta) b.appendChild(meta.cloneNode(true));
    return b;
  }

  // 섹션 하나를 최대 budget 쪽에 배치 (budget 0 = 제한 없음). 못 들어간 원본 요소는 rest 로 돌려준다
  function placeSection(stage, g, sec, first, budget, nodes, mast) {
    var id = sec.getAttribute("data-section"), title = sec.getAttribute("data-title");
    var out = [], rest = [];
    var grid = id === "briefs" && g.w >= 480;   // 단신은 폭이 넉넉하면 두 단
    var mk = function (cont) {
      var p = newPage(g, id, first && !cont ? null : title, cont);
      if (grid) p.firstChild.classList.add("brief-grid");
      return p;
    };
    var page = mk(false);
    stage.appendChild(page);
    var inner = page.firstChild;
    if (first && mast) inner.appendChild(mast.cloneNode(true));
    var placedOnPage = 0;
    var used = [];
    nodes.forEach(function (src, k) {
      if (used[k]) return;
      var node = src.node;
      inner.appendChild(node);
      if (!overflows(inner)) { placedOnPage++; return; }
      if (placedOnPage === 0) { fit(inner, node); placedOnPage++; return; }   // 한 쪽보다 큰 기사
      if (budget && out.length + 1 >= budget) {
        // 마지막 쪽: 바로 내리지 말고 줄여서(사진·요약·부가 정보) 넣어 본다 — 1면 기사가 단신으로 밀리지 않게
        node.classList.add("compact");
        if (!overflows(inner)) { placedOnPage++; return; }
        node.classList.add("tight");
        if (!overflows(inner)) { placedOnPage++; return; }
        inner.removeChild(node);
        rest.push(src);   // 그래도 안 들어가면 단신으로
        return;
      }
      inner.removeChild(node);
      // 새 쪽으로 넘기기 전에, 뒤 기사 중 남은 자리에 들어가는 것으로 빈자리를 채운다 (한 쪽 아래가 비지 않게)
      for (var j = k + 1; j < nodes.length; j++) {
        if (used[j]) continue;
        inner.appendChild(nodes[j].node);
        if (overflows(inner)) inner.removeChild(nodes[j].node); else { used[j] = true; placedOnPage++; }
      }
      out.push(page);
      page = mk(true);
      stage.appendChild(page);
      inner = page.firstChild;
      inner.appendChild(node);
      placedOnPage = 0;
      if (overflows(inner)) fit(inner, node);
      placedOnPage++;
    });
    if (inner.children.length > (title && !first ? 1 : 0) || out.length === 0) out.push(page); else page.remove();
    return { pages: out, rest: rest };
  }

  function paginate() {
    dropped = 0;
    var g = geometry();
    var stage = document.createElement("div");
    stage.className = "stage";
    document.body.appendChild(stage);   // 실제 크기로 재기 위해 화면 밖에 붙인다
    var mast = flow.querySelector(".masthead-block");
    var budgets = {};
    Object.keys(E.sectionPages || {}).forEach(function (k) { budgets[k] = E.sectionPages[k]; });
    // 휴대폰처럼 좁은 한 쪽 화면은 단신이 한 단이라 같은 쪽 수에 절반만 들어간다 → 단신 쪽을 두 배로 (기기마다 쪽수는 늘 같다)
    if (!spread && g.w < 600 && budgets.briefs) budgets.briefs *= 2;
    // 피드백으로 기사가 모두 빠진 섹션은 건너뛴다 (제목만 있는 빈 쪽 방지)
    var sections = Array.prototype.filter.call(flow.querySelectorAll("section.sec"), function (s) { return s.children.length > 0; });
    var byId = {}, order = [];
    sections.forEach(function (s) { var id = s.getAttribute("data-section"); byId[id] = s; order.push(id); });
    var built = {}, demoted = [], spare = 0, firstId = order[0];
    var kids = function (sec) {
      return Array.prototype.filter.call(sec.children, function (el) { return el.getAttribute("data-reserve") !== "1"; })
        .map(function (el) { return { el: el, node: el.cloneNode(true) }; });
    };
    // 1) 뉴스 면: 정해진 쪽 안에서, 넘친 기사는 단신으로 내린다 / 논평·가이드: 정해진 쪽 안에서만
    order.forEach(function (id) {
      if (id === "briefs") return;
      var b = budgets[id] || 0;
      var res = placeSection(stage, g, byId[id], id === firstId, b, kids(byId[id]), mast);
      built[id] = res.pages;
      if (id !== "opinion" && id !== "guide") demoted = demoted.concat(res.rest.map(function (r) { return r.el; }));
      else dropped += res.rest.length;
      if (b) spare += Math.max(0, b - res.pages.length);
    });
    // 2) 단신: 내려온 기사(점수 순) → 원래 단신 → 예비 기사. 다른 면이 남긴 쪽까지 쓴다
    var briefSec = byId.briefs || (function () {
      var s = document.createElement("section");
      s.className = "sec sec-briefs"; s.setAttribute("data-section", "briefs");
      s.setAttribute("data-title", (E.sectionTitles || {}).briefs || "단신");
      return s;
    })();
    demoted.sort(function (x, y) { return (+y.getAttribute("data-final2") || +y.getAttribute("data-final")) - (+x.getAttribute("data-final2") || +x.getAttribute("data-final")); });
    var pool = demoted.concat(Array.prototype.filter.call(briefSec.children, function (el) { return el.getAttribute("data-reserve") !== "1"; }),
      Array.prototype.filter.call(briefSec.children, function (el) { return el.getAttribute("data-reserve") === "1" && el.getAttribute("data-brief"); }));
    // 오늘 없는 면(예: 논평·사설이 없는 날)에 배정된 쪽도 단신이 쓴다
    Object.keys(budgets).forEach(function (k) { if (k !== "briefs" && k !== "compare" && !byId[k]) spare += budgets[k] || 0; });
    var bBudget = budgets.briefs ? budgets.briefs + spare : 0;
    if (pool.length) {
      var res = placeSection(stage, g, briefSec, false, bBudget, pool.map(function (el) { return { el: el, node: asBrief(el) }; }), null);
      built.briefs = res.pages;
      dropped += res.rest.length;
      if (order.indexOf("briefs") < 0) order.splice(Math.max(0, order.indexOf("opinion")) || order.length, 0, "briefs");
    }
    var out = [];
    order.forEach(function (id) { out = out.concat(built[id] || []); });
    // 쪽수 고정: 기사가 모자라 쪽이 남으면 끝 쪽으로 채운다 (같은 화면 크기면 호가 바뀌어도 쪽수가 같다)
    var total = 0;
    Object.keys(budgets).forEach(function (k) { total += budgets[k] || 0; });
    while (total && out.length < total) {
      var end = newPage(g, "end", null, false);
      end.classList.add("endpage");
      end.firstChild.innerHTML = '<p class="end-note">오늘 지면은 여기까지입니다.</p><p class="end-note"><a href="' +
        ((document.querySelector(".tb-link") || {}).getAttribute ? document.querySelector(".tb-link").getAttribute("href") : "archive/") + '">지난 호 보기</a></p>';
      out.push(end);
    }
    if (spread && out.length % 2 === 1) { var bl = newPage(g, "blank", null, false); bl.classList.add("blank"); out.push(bl); }
    out.forEach(function (p, i) { p.querySelector(".folio").textContent = (i + 1) + " / " + out.length; p.setAttribute("data-page", i); });
    // 모든 쪽이 실제로 배치된 지금 넘침을 센다 (넘김 라이브러리에 넘긴 뒤에는 안 보이는 쪽의 높이가 0으로 재어진다)
    overflowPages = out.filter(function (p) { return overflows(p.querySelector(".page-inner")); }).map(function (p) { return +p.getAttribute("data-page"); });
    clipped = stage.querySelectorAll(".item.clip").length;
    demotedCount = stage.querySelectorAll(".item.demoted").length;
    briefCount = stage.querySelectorAll(".item.brief").length;
    emptySummary = Array.prototype.filter.call(stage.querySelectorAll(".item:not(.oplist):not(.opcmp):not(.guide-intro):not(.guide-table)"), function (el) {
      return !el.querySelector(".lead");
    }).length;
    stage.remove();
    return { pages: out, g: g };
  }

  // ---------- 넘기기 ----------
  function showInfo() {
    var last = pages.length;
    var a = current + 1, b = spread && mode !== "scroll" ? Math.min(current + 2, last) : a;
    pageInfo.textContent = (a === b ? a : a + "–" + b) + " / " + last + "쪽";
  }

  function simpleShow(idx) {   // 동작 줄이기: 애니메이션 없이 펼침면 교체
    var step = spread ? 2 : 1;
    idx = Math.max(0, Math.min(idx - (idx % step), pages.length - 1));
    current = idx;
    pages.forEach(function (p, i) { p.style.display = (i >= idx && i < idx + step) ? "" : "none"; });
    showInfo();
  }

  function build(keepIssue, keepPage) {
    if (flip) { try { flip.destroy(); } catch (e) { /* 이미 해제됨 */ } flip = null; }
    book.innerHTML = "";
    scroller = sizer = zoomer = null;
    var res = paginate();
    pages = res.pages;
    var start = 0;
    if (keepIssue) {
      pages.some(function (p, i) { if (p.querySelector('[data-issue="' + keepIssue + '"]')) { start = i; return true; } return false; });
    }
    if (typeof keepPage === "number") start = Math.max(0, Math.min(keepPage, pages.length - 1));
    document.body.classList.toggle("view-scroll", mode === "scroll");
    syncToolbar();
    if (mode === "scroll") { buildScroll(res.g, start); return; }
    book.className = (spread ? "spread" : "single") + (reduced.matches ? " reduced" : "");
    book.style.width = (spread ? res.g.w * 2 : res.g.w) + "px";
    book.style.height = res.g.h + "px";
    if (reduced.matches || typeof St === "undefined") {
      pages.forEach(function (p) { book.appendChild(p); });
      simpleShow(start);
      return;
    }
    var holder = document.createElement("div");
    book.appendChild(holder);
    pages.forEach(function (p) { holder.appendChild(p); });
    flip = new St.PageFlip(holder, {
      width: res.g.w, height: res.g.h, size: "fixed",
      showCover: false, usePortrait: !spread, autoSize: false,
      maxShadowOpacity: 0.35, flippingTime: 700, drawShadow: true,
      mobileScrollSupport: false, disableFlipByClick: true, swipeDistance: 20,
      startPage: start, showPageCorners: true
    });
    flip.loadFromHTML(pages);
    flip.on("flip", function (e) { current = e.data; showInfo(); });
    current = flip.getCurrentPageIndex();
    showInfo();
  }

  // ---------- 한 면 보기 (S16) ----------
  function buildScroll(g, start) {
    pageW = g.w; pageH = g.h;
    book.className = "scroll";
    book.style.width = "100%";
    book.style.height = g.H + "px";
    scroller = document.createElement("div");
    scroller.className = "scroller";
    sizer = document.createElement("div");
    sizer.className = "zoom-sizer";
    zoomer = document.createElement("div");
    zoomer.className = "zoomer";
    pages.forEach(function (p) { p.style.display = ""; zoomer.appendChild(p); });
    sizer.appendChild(zoomer);
    scroller.appendChild(sizer);
    book.appendChild(scroller);
    applyZoom(zoom, null);
    scroller.addEventListener("scroll", onScroll, { passive: true });
    bindPinch(scroller);
    scrollToPage(start);
  }

  function applyZoom(z, focal) {
    z = Math.max(ZMIN, Math.min(ZMAX, Math.round(z * 100) / 100));
    if (!scroller) { zoom = z; return; }
    var old = zoom;
    // 손가락 사이(또는 화면 가운데)를 기준으로 키운다
    var fx = focal ? focal.x : scroller.clientWidth / 2, fy = focal ? focal.y : scroller.clientHeight / 2;
    var cx = (scroller.scrollLeft + fx) / old, cy = (scroller.scrollTop + fy) / old;
    zoom = z;
    var totalH = pages.length * (pageH + GAP);
    sizer.style.width = Math.ceil(pageW * z) + "px";
    sizer.style.height = Math.ceil(totalH * z) + "px";
    zoomer.style.transform = "scale(" + z + ")";
    scroller.classList.toggle("zoomed", z > 1.001);
    scroller.scrollLeft = cx * z - fx;
    scroller.scrollTop = cy * z - fy;
    store.set("zoom", String(z));
    syncToolbar();
  }

  function onScroll() {
    if (!scroller) return;
    // 화면 위쪽 30% 지점에 걸친 쪽 = 지금 읽는 쪽
    var idx = Math.floor((scroller.scrollTop + scroller.clientHeight * 0.3) / ((pageH + GAP) * zoom));
    idx = Math.max(0, Math.min(idx, pages.length - 1));
    if (idx !== current) { current = idx; showInfo(); }
  }

  function scrollToPage(i) {
    i = Math.max(0, Math.min(i, pages.length - 1));
    current = i;
    if (scroller) scroller.scrollTop = i * (pageH + GAP) * zoom;
    showInfo();
  }

  function bindPinch(el) {
    var d0 = 0, z0 = 1;
    function dist(t) { var dx = t[0].clientX - t[1].clientX, dy = t[0].clientY - t[1].clientY; return Math.sqrt(dx * dx + dy * dy); }
    function mid(t) { var r = el.getBoundingClientRect(); return { x: (t[0].clientX + t[1].clientX) / 2 - r.left, y: (t[0].clientY + t[1].clientY) / 2 - r.top }; }
    el.addEventListener("touchstart", function (e) {
      if (e.touches.length === 2) { d0 = dist(e.touches); z0 = zoom; }
    }, { passive: true });
    el.addEventListener("touchmove", function (e) {
      if (e.touches.length !== 2 || !d0) return;
      e.preventDefault();   // 브라우저 자체 확대 대신 지면만 키운다 (도구 막대는 그대로)
      applyZoom(z0 * dist(e.touches) / d0, mid(e.touches));
    }, { passive: false });
    el.addEventListener("touchend", function (e) { if (e.touches.length < 2) d0 = 0; }, { passive: true });
    // 트랙패드·Ctrl+휠 확대
    el.addEventListener("wheel", function (e) {
      if (!e.ctrlKey) return;
      e.preventDefault();
      var r = el.getBoundingClientRect();
      applyZoom(zoom * Math.exp(-e.deltaY / 300), { x: e.clientX - r.left, y: e.clientY - r.top });
    }, { passive: false });
  }

  function setView(m) {
    if (m !== "flip" && m !== "scroll") return;
    var keep = current;
    mode = m;
    store.set("viewMode", m);
    build(null, keep);   // 보던 쪽 그대로
  }

  // ---------- 전체화면 (S16) ----------
  function standalone() {
    return (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) || window.navigator.standalone === true;
  }
  function fsElement() { return document.fullscreenElement || document.webkitFullscreenElement || null; }
  function toggleFullscreen() {
    var el = document.documentElement;
    if (fsElement()) { (document.exitFullscreen || document.webkitExitFullscreen).call(document); return; }
    var req = el.requestFullscreen || el.webkitRequestFullscreen;
    if (req && (document.fullscreenEnabled || document.webkitFullscreenEnabled)) {
      try {
        var r = req.call(el);
        if (r && r.catch) r.catch(function () { tip(); });
      } catch (e) { tip(); }
    } else {
      tip();
    }
  }
  function tip() {
    var t = document.getElementById("fsTip");
    if (!t) {
      t = document.createElement("div");
      t.id = "fsTip";
      t.className = "fs-tip";
      t.setAttribute("role", "status");
      document.body.appendChild(t);
    }
    t.innerHTML = "이 브라우저는 전체화면을 지원하지 않습니다.<br>Safari <b>공유</b> 버튼 → <b>홈 화면에 추가</b>로 열면 주소창 없이 볼 수 있습니다.";
    t.hidden = false;
    clearTimeout(tip.timer);
    tip.timer = setTimeout(function () { t.hidden = true; }, 6000);
  }

  function syncToolbar() {
    var v = document.querySelector('[data-act="view"]');
    if (v) {
      v.textContent = mode === "scroll" ? "펼침" : "한 면";
      v.setAttribute("aria-label", mode === "scroll" ? "펼쳐서 넘겨 보기" : "한 면씩 스크롤로 보기");
      v.setAttribute("aria-pressed", mode === "scroll" ? "true" : "false");
    }
    var fs = document.querySelector('[data-act="fullscreen"]');
    if (fs) fs.hidden = standalone();   // 홈 화면 앱이면 이미 주소창이 없다
    var zi = document.querySelector('[data-act="zoom+"]'), zo = document.querySelector('[data-act="zoom-"]');
    if (zi) { zi.hidden = mode !== "scroll"; zi.disabled = zoom >= ZMAX; }
    if (zo) { zo.hidden = mode !== "scroll"; zo.disabled = zoom <= ZMIN; }
  }

  function go(delta) {
    if (mode === "scroll") { scrollToPage(current + delta); return; }
    if (flip) { delta > 0 ? flip.flipNext() : flip.flipPrev(); return; }
    simpleShow(current + delta * (spread ? 2 : 1));
  }

  // 지금 보이는 쪽의 첫 기사 (다시 나눌 때 위치 유지용)
  function visibleIssue() {
    var p = pages[current];
    var el = p && p.querySelector("[data-issue]");
    return el ? el.getAttribute("data-issue") : null;
  }

  // ---------- 이벤트 ----------
  document.getElementById("toolbar").addEventListener("click", function (e) {
    var act = e.target.getAttribute && e.target.getAttribute("data-act");
    if (!act) return;
    if (act === "prev") go(-1);
    if (act === "next") go(1);
    if (act === "view") setView(mode === "scroll" ? "flip" : "scroll");
    if (act === "zoom+") applyZoom(zoom + 0.5, null);
    if (act === "zoom-") applyZoom(zoom - 0.5, null);
    if (act === "fullscreen") toggleFullscreen();
    if (act === "font+" || act === "font-") {
      fontScale = Math.max(0.8, Math.min(1.5, Math.round((fontScale + (act === "font+" ? 0.1 : -0.1)) * 10) / 10));
      root.style.setProperty("--fs", fontScale);
      store.set("fontScale", String(fontScale));
      build(visibleIssue());
    }
    if (act === "theme") {
      var order = ["auto", "light", "dark"];
      var t = order[(order.indexOf(root.getAttribute("data-theme")) + 1) % order.length];
      applyTheme(t);
      store.set("theme", t);
    }
  });

  document.addEventListener("keydown", function (e) {
    if (reader && !reader.hidden) return;
    if (e.key === "ArrowRight") go(1);
    if (e.key === "ArrowLeft") go(-1);
  });
  // iPad·iPhone Safari 는 두 손가락 확대를 gesture 이벤트로도 처리한다 → 한 면 보기에서는 지면 줌만 쓰도록 막는다
  ["gesturestart", "gesturechange"].forEach(function (ev) {
    document.addEventListener(ev, function (e) { if (mode === "scroll") e.preventDefault(); }, { passive: false });
  });
  ["fullscreenchange", "webkitfullscreenchange"].forEach(function (ev) {
    document.addEventListener(ev, function () { document.body.classList.toggle("is-fullscreen", !!fsElement()); });
  });

  // 동작 줄이기 모드의 손가락 넘기기 (애니메이션 없음)
  var tx = null;
  book.addEventListener("touchstart", function (e) { if (!flip && mode !== "scroll" && e.touches.length === 1) tx = e.touches[0].clientX; }, { passive: true });
  book.addEventListener("touchend", function (e) {
    if (flip || mode === "scroll" || tx === null) return;
    var dx = e.changedTouches[0].clientX - tx;
    if (Math.abs(dx) > 40) go(dx < 0 ? 1 : -1);
    tx = null;
  });

  // 사진이 안 열리면(차단·삭제) 자리를 접는다
  document.addEventListener("error", function (e) {
    var t = e.target;
    if (t && t.tagName === "IMG") {
      var fig = t.closest("figure");
      if (fig) fig.remove();
    }
  }, true);

  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    var keep = visibleIssue();
    resizeTimer = setTimeout(function () { build(keep); }, 250);
  });
  reduced.addEventListener && reduced.addEventListener("change", function () { build(visibleIssue()); });

  // ---------- 기사 자세히 (S15) ----------
  // 지면에서는 머리기사만 분석을 다 펼치고, 나머지는 줄여 보인다. "자세히"는 쪽 나누기 전 원본(#flow)을 그대로 보여 준다
  var reader = document.getElementById("reader");
  function openReader(issue) {
    var src = flow.querySelector('article.item[data-issue="' + issue + '"]');
    if (!src || !reader) return;
    var node = src.cloneNode(true);
    node.classList.remove("sub", "compact", "tight", "clip", "brief", "demoted", "reserve");
    node.style.maxHeight = "";
    var mb = node.querySelector("[data-more]");
    if (mb) mb.remove();
    var body = reader.querySelector(".reader-body");
    body.innerHTML = "";
    body.appendChild(node);
    reader.hidden = false;
    reader.querySelector(".reader-panel").scrollTop = 0;
    reader.querySelector("[data-reader-close]").focus();
  }
  function closeReader() { if (reader) reader.hidden = true; }
  document.addEventListener("click", function (e) {
    var m = e.target.closest && e.target.closest("[data-more]");
    if (m) { var art = m.closest("[data-issue]"); if (art) openReader(art.getAttribute("data-issue")); return; }
    if (e.target.closest && (e.target.closest("[data-reader-close]") || e.target === reader)) closeReader();
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && reader && !reader.hidden) closeReader(); }, true);

  // 피드백 버튼은 feedback.js(S9)가 처리한다. 여기서는 이벤트만 알린다.
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-fb]");
    if (!b) return;
    var art = b.closest("[data-issue]");
    document.dispatchEvent(new CustomEvent("news:feedback", {
      detail: { kind: b.getAttribute("data-fb"), issue: art.getAttribute("data-issue"), topic: art.getAttribute("data-topic") }
    }));
    b.classList.add("pressed");
  });

  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register((window.EDITION && window.EDITION.base || "") + "sw.js").catch(function () { /* 오프라인 캐시는 선택 기능 */ });
  }

  function goTo(i) {
    if (mode === "scroll") { scrollToPage(i); return; }
    if (flip) { flip.turnToPage(i); current = flip.getCurrentPageIndex(); showInfo(); return; }
    simpleShow(i);
  }

  window.NEWS = { rebuild: function () { build(visibleIssue()); }, go: go, goTo: goTo, openReader: openReader, setView: setView, setZoom: function (z) { applyZoom(z, null); }, fullscreen: toggleFullscreen, state: function () { return { mode: mode, zoom: zoom, current: current, pages: pages.length, spread: spread, flip: !!flip, overflow: overflowPages.slice(), clipped: clipped, demoted: demotedCount, briefs: briefCount, dropped: dropped, emptySummary: emptySummary }; } };
  // 글꼴(Noto Sans·Noto Sans KR)을 받은 뒤 쪽을 나눈다 — 먼저 나누면 글꼴이 바뀌며 글 길이가 달라져 쪽이 넘친다.
  // 한글 글꼴은 글자 범위별 조각으로 나뉘어 필요할 때 받으므로, 지면에 쓰인 글자를 넘겨 필요한 조각을 미리 받는다.
  // 글꼴 서버에 닿지 못하면(오프라인) 2.5초 뒤 기본 글꼴로 나눈다 (그 뒤 글꼴이 오면 한 번만 다시 나눈다)
  var started = false, fallback = false;
  function start() { if (!started) { started = true; build(null); } }
  if (document.fonts && document.fonts.load) {
    var text = flow.textContent.replace(/\s+/g, " ");
    var loads = ["400", "500", "700"].map(function (w) {
      return Promise.all([document.fonts.load(w + ' 16px "Noto Sans KR"', text), document.fonts.load(w + ' 16px "Noto Sans"', text)]);
    });
    var timer = setTimeout(function () { fallback = true; start(); }, 2500);
    Promise.all(loads).then(function () { clearTimeout(timer); if (fallback) build(visibleIssue()); else start(); },
                            function () { clearTimeout(timer); start(); });
  } else {
    start();
  }
})();
