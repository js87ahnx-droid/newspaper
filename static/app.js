/* ○월 ○일자 뉴스 — 쪽 나누기와 종이 넘김.
 *
 * 1. #flow 의 섹션·기사를 화면 크기에 맞춰 쪽(.page)으로 나눈다 (가로 화면은 좌우 두 쪽 펼침).
 * 2. page-flip(StPageFlip) 으로 손가락을 따라 넘어가게 한다. 동작 줄이기 설정이면 애니메이션 없이 넘긴다.
 * 3. 화면 회전·크기 변경·글자 크기 변경 때 다시 나눈다 (보던 기사 위치 유지).
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

  // ---------- 설정: 밝기·글자 크기 ----------
  function applyTheme(t) { root.setAttribute("data-theme", t); }
  applyTheme(store.get("theme", "auto"));
  var fontScale = parseFloat(store.get("fontScale", "1")) || 1;
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

  function paginate() {
    var g = geometry();
    var stage = document.createElement("div");
    stage.className = "stage";
    document.body.appendChild(stage);   // 실제 크기로 재기 위해 화면 밖에 붙인다
    var out = [];
    var mast = flow.querySelector(".masthead-block");
    var sections = flow.querySelectorAll("section.sec");
    sections.forEach(function (sec, si) {
      var id = sec.getAttribute("data-section");
      var title = sec.getAttribute("data-title");
      var page = newPage(g, id, si === 0 ? null : title, false);
      stage.appendChild(page);
      var inner = page.firstChild;
      if (si === 0) inner.appendChild(mast.cloneNode(true));
      var placedOnPage = 0;
      Array.prototype.forEach.call(sec.children, function (el) {
        var node = el.cloneNode(true);
        inner.appendChild(node);
        if (overflows(inner)) {
          if (placedOnPage === 0) {
            // 한 쪽에 다 안 들어가는 기사: 리드를 줄여 본다
            node.classList.add("compact");
            if (overflows(inner)) node.classList.add("tight");
          } else {
            inner.removeChild(node);
            out.push(page);
            page = newPage(g, id, title, true);
            stage.appendChild(page);
            inner = page.firstChild;
            inner.appendChild(node);
            placedOnPage = 0;
            if (overflows(inner)) { node.classList.add("compact"); if (overflows(inner)) node.classList.add("tight"); }
          }
        }
        placedOnPage++;
      });
      out.push(page);   // 섹션은 이어지는 다음 쪽에서 시작한다 (빈 쪽을 끼우면 지면이 성겨진다)
    });
    if (spread && out.length % 2 === 1) { var b = newPage(g, "blank", null, false); b.classList.add("blank"); out.push(b); }
    out.forEach(function (p, i) { p.querySelector(".folio").textContent = (i + 1) + " / " + out.length; p.setAttribute("data-page", i); });
    stage.remove();
    return { pages: out, g: g };
  }

  // ---------- 넘기기 ----------
  function showInfo() {
    var last = pages.length;
    var a = current + 1, b = spread ? Math.min(current + 2, last) : a;
    pageInfo.textContent = (a === b ? a : a + "–" + b) + " / " + last + "쪽";
  }

  function simpleShow(idx) {   // 동작 줄이기: 애니메이션 없이 펼침면 교체
    var step = spread ? 2 : 1;
    idx = Math.max(0, Math.min(idx - (idx % step), pages.length - 1));
    current = idx;
    pages.forEach(function (p, i) { p.style.display = (i >= idx && i < idx + step) ? "" : "none"; });
    showInfo();
  }

  function build(keepIssue) {
    if (flip) { try { flip.destroy(); } catch (e) { /* 이미 해제됨 */ } flip = null; }
    book.innerHTML = "";
    var res = paginate();
    pages = res.pages;
    var start = 0;
    if (keepIssue) {
      pages.some(function (p, i) { if (p.querySelector('[data-issue="' + keepIssue + '"]')) { start = i; return true; } return false; });
    }
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

  function go(delta) {
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
    if (e.key === "ArrowRight") go(1);
    if (e.key === "ArrowLeft") go(-1);
  });

  // 동작 줄이기 모드의 손가락 넘기기 (애니메이션 없음)
  var tx = null;
  book.addEventListener("touchstart", function (e) { if (!flip) tx = e.touches[0].clientX; }, { passive: true });
  book.addEventListener("touchend", function (e) {
    if (flip || tx === null) return;
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
    navigator.serviceWorker.register("sw.js").catch(function () { /* 오프라인 캐시는 선택 기능 */ });
  }

  function goTo(i) {
    if (flip) { flip.turnToPage(i); current = flip.getCurrentPageIndex(); showInfo(); return; }
    simpleShow(i);
  }

  window.NEWS = { rebuild: function () { build(visibleIssue()); }, go: go, goTo: goTo, state: function () { return { current: current, pages: pages.length, spread: spread, flip: !!flip }; } };
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
