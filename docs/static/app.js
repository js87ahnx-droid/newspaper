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
    document.body.classList.toggle("narrow-page", pw < 560);   // 1면 3구역(S26b)을 세로로 쌓는 폭
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
    // "내려온 기사" 표시는 다른 면에서 넘쳐 온 것만 — 예비 기사(S21c)·원래 단신(S22a: 원본도 일반 기사 꼴)은 아님
    b.className = "item brief" + (el.getAttribute("data-reserve") === "1" || el.getAttribute("data-section") === "briefs" ? "" : " demoted");
    var hl = el.querySelector(".hl");
    if (hl) b.appendChild(hl.cloneNode(true));
    var t = el.getAttribute("data-brief");
    if (t) { var p = document.createElement("p"); p.className = "lead brief-line"; p.textContent = t; b.appendChild(p); }
    var meta = el.querySelector(".meta");
    if (meta) b.appendChild(meta.cloneNode(true));
    return b;
  }

  // 단신 분야 묶음 (S19c): 분야 소제목 + 그 분야 첫 단신을 한 덩어리로 (소제목만 쪽 끝에 남지 않게)
  function topicHead(name, cont, node) {
    var w = document.createElement("div");
    w.className = "brief-group";
    var h = document.createElement("h4");
    h.className = "brief-topic";
    h.textContent = name + (cont ? " (이어서)" : "");
    w.appendChild(h);
    w.appendChild(node);
    return w;
  }
  // 실을 단신(우선순위 순)을 분야 순서(분야 중요도 순)로 다시 늘어놓는다. 분야 안은 원래 순서
  function groupBriefs(els) {
    var rank = {};
    (E.briefTopics || []).forEach(function (t, i) { rank[t] = i; });
    var idx = els.map(function (el, i) { return { el: el, i: i, r: rank[el.getAttribute("data-topic")] !== undefined ? rank[el.getAttribute("data-topic")] : 99 }; });
    idx.sort(function (a, b) { return a.r - b.r || a.i - b.i; });
    var last = null;
    return idx.map(function (x) {
      var t = x.el.getAttribute("data-topic"), name = (E.topics || {})[t] || "기타";
      var node = asBrief(x.el);
      node.setAttribute("data-topic-name", name);
      var start = t !== last;
      last = t;
      return { el: x.el, node: start ? topicHead(name, false, node) : node };
    });
  }
  // 묶음 배치에서 쪽이 바뀌면, 새 쪽 첫 단신이 묶음 첫 줄이 아니어도 소제목을 "(이어서)"로 다시 단다
  function contHead(node) {
    return node.classList.contains("brief-group") ? node : topicHead(node.getAttribute("data-topic-name") || "기타", true, node);
  }

  // 섹션 하나를 최대 budget 쪽에 배치 (budget 0 = 제한 없음). 못 들어간 원본 요소는 rest 로 돌려준다
  // opts.grouped: 단신 분야 묶음 — 뒤 기사로 빈자리 채우기를 하지 않고(분야 순서 유지), 새 쪽엔 소제목을 다시 단다
  function placeSection(stage, g, sec, first, budget, nodes, mast, opts) {
    var grouped = opts && opts.grouped;
    var id = sec.getAttribute("data-section"), title = sec.getAttribute("data-title");
    var out = [], rest = [];
    var grid = false;   // 단신은 기사마다 가로 한 줄 (S17e — 예전엔 폭이 넉넉하면 두 단)
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
      for (var j = k + 1; j < nodes.length && !grouped; j++) {
        if (used[j]) continue;
        inner.appendChild(nodes[j].node);
        if (overflows(inner)) inner.removeChild(nodes[j].node); else { used[j] = true; placedOnPage++; }
      }
      out.push(page);
      page = mk(true);
      stage.appendChild(page);
      inner = page.firstChild;
      if (grouped) node = src.node = contHead(node);
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
    var opRest = 0;
    var g = geometry();
    var stage = document.createElement("div");
    stage.className = "stage";
    document.body.appendChild(stage);   // 실제 크기로 재기 위해 화면 밖에 붙인다
    var mast = flow.querySelector(".masthead-block");
    var budgets = {};
    Object.keys(E.sectionPages || {}).forEach(function (k) { budgets[k] = E.sectionPages[k]; });
    // 휴대폰처럼 좁은 한 쪽 화면은 단신이 한 단이라 같은 쪽 수에 절반만 들어간다 → 단신 쪽을 두 배로 (기기마다 쪽수는 늘 같다)
    // (S15 에선 휴대폰 단신 쪽을 두 배로 했다 — S17e 에서 단신이 한 줄이 되어 없앰)
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
      // B안 이슈 면(S26d): 1면에서 이어받는 칸은 단신으로 내리지 않는다 — 쪽이 모자라면 쪽을 늘린다
      var res = placeSection(stage, g, byId[id], id === firstId, id === "issue" ? 0 : b, kids(byId[id]), mast);
      built[id] = res.pages;
      if (id !== "opinion" && id !== "guide" && id !== "analysis") demoted = demoted.concat(res.rest.map(function (r) { return r.el; }));
      else { dropped += res.rest.length; if (id === "opinion") opRest = res.rest.length; }
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
      Array.prototype.filter.call(briefSec.children, function (el) { return el.getAttribute("data-reserve") === "1"; }));   // 한 줄 단신은 제목만으로도 된다 (S17e)
    // 오늘 없는 면(예: 논평·사설이 없는 날)에 배정된 쪽도 단신이 쓴다
    Object.keys(budgets).forEach(function (k) { if (k !== "briefs" && k !== "compare" && !byId[k]) spare += budgets[k] || 0; });
    // 남는 쪽은 논평면이 못 실은 사설·칼럼이 먼저 쓴다 (예비 기사보다 우선 — S17e: 사설이 많은 날 사설이 빠지고 예비 단신이 실리던 것)
    if (opRest && byId.opinion && spare > 0) {
      var had = built.opinion.length;
      built.opinion.forEach(function (p) { p.remove(); });
      var more = placeSection(stage, g, byId.opinion, false, (budgets.opinion || 0) + spare, kids(byId.opinion), null);
      built.opinion = more.pages;
      spare -= more.pages.length - had;
      dropped += more.rest.length - opRest;
    }
    // 남는 쪽은 예비 기사를 일반 기사 모양으로 "더 읽을 기사" 면에 (S21c — 단신을 줄이자 얇은 날 끝 빈 쪽이 생김).
    // 원래 단신이 단신 쪽에 다 들어갈 만큼은 남겨 두고, 그 나머지 쪽만 쓴다.
    // 다른 면에서 내려온 기사가 예비 기사보다 먼저 (S18 — 1면 다섯째 기사가 단신으로, 점수 낮은 예비 기사는 일반 기사 꼴로 실리던 것)
    var reservesEl = demoted.concat(pool.filter(function (el) { return el.getAttribute("data-reserve") === "1"; }));
    if (budgets.briefs && spare > 0 && reservesEl.length) {
      var must = pool.filter(function (el) { return el.getAttribute("data-reserve") !== "1" && demoted.indexOf(el) < 0; });
      var need = 0;
      if (must.length) {
        var trial = placeSection(stage, g, briefSec, false, 0, groupBriefs(must), null, { grouped: true });
        need = trial.pages.length;
        trial.pages.forEach(function (p) { p.remove(); });
      }
      var moreBudget = Math.min(spare, budgets.briefs + spare - need);
      if (moreBudget > 0) {
        var moreSec = document.createElement("section");
        moreSec.className = "sec sec-more"; moreSec.setAttribute("data-section", "more");
        moreSec.setAttribute("data-title", "더 읽을 기사");
        var mres = placeSection(stage, g, moreSec, false, moreBudget,
          reservesEl.map(function (el) { return { el: el, node: el.cloneNode(true) }; }), null);
        var placedMore = reservesEl.filter(function (el) { return !mres.rest.some(function (r) { return r.el === el; }); });
        built.more = mres.pages;
        spare -= mres.pages.length;
        pool = pool.filter(function (el) { return placedMore.indexOf(el) < 0; });
        if (order.indexOf("more") < 0) order.splice(order.indexOf("briefs") >= 0 ? order.indexOf("briefs") : (order.indexOf("opinion") >= 0 ? order.indexOf("opinion") : order.length), 0, "more");
      }
    }
    var bBudget = budgets.briefs ? budgets.briefs + spare : 0;
    if (pool.length) {
      var placeBriefs = function (budget) { return placeSection(stage, g, briefSec, false, budget, pool.map(function (el) { return { el: el, node: asBrief(el) }; }), null); };
      var res = placeBriefs(bBudget);
      // 논평면이 아직 못 실은 게 있고 단신 쪽에 예비 기사가 실렸으면, 단신 쪽 하나를 논평면에 넘긴다 — 원래 단신(예비 아님)이 다 실릴 때만 (S17e)
      while (opRest && byId.opinion && bBudget > 1 && res.rest.every(function (r) { return r.el.getAttribute("data-reserve") === "1"; })
             && res.pages.some(function (p) { return p.querySelector('[data-reserve="1"]'); })) {
        var fewer = (res.pages.forEach(function (p) { p.remove(); }), placeBriefs(bBudget - 1));
        if (!fewer.rest.every(function (r) { return r.el.getAttribute("data-reserve") === "1"; })) {
          fewer.pages.forEach(function (p) { p.remove(); }); res = placeBriefs(bBudget); break;
        }
        built.opinion.forEach(function (p) { p.remove(); });
        var op = placeSection(stage, g, byId.opinion, false, built.opinion.length + 1, kids(byId.opinion), null);
        built.opinion = op.pages;
        dropped += op.rest.length - opRest;
        opRest = op.rest.length;
        res = fewer; bBudget -= 1;
      }
      // 실을 단신이 정해졌으면 분야별로 묶어 다시 배치 (S19c). 소제목 몫만큼 넘치면 우선순위가 가장 낮은 단신부터 뺀다
      var cut = res.rest.map(function (r) { return r.el; });
      var keep = pool.filter(function (el) { return cut.indexOf(el) < 0; });
      res.pages.forEach(function (p) { p.remove(); });
      var grp;
      while (true) {
        grp = placeSection(stage, g, briefSec, false, bBudget, groupBriefs(keep), null, { grouped: true });   // 쪽 한도는 그대로(bBudget)
        if (!grp.rest.length || !keep.length) break;
        grp.pages.forEach(function (p) { p.remove(); });
        cut.push(keep.pop());
      }
      res = { pages: grp.pages, rest: cut.map(function (el) { return { el: el }; }).concat(grp.rest) };
      built.briefs = res.pages;
      dropped += res.rest.length;
      if (order.indexOf("briefs") < 0) order.splice(Math.max(0, order.indexOf("opinion")) || order.length, 0, "briefs");
    }
    var total = 0;
    Object.keys(budgets).forEach(function (k) { total += budgets[k] || 0; });
    var out = [];
    order.forEach(function (id) { out = out.concat(built[id] || []); });
    // 쪽수 고정: 기사가 모자라 쪽이 남으면 끝 쪽으로 채운다 (같은 화면 크기면 호가 바뀌어도 쪽수가 같다)
    while (total && out.length < total) {
      var end = newPage(g, "end", null, false);
      end.classList.add("endpage");
      end.firstChild.innerHTML = '<p class="end-note">오늘 지면은 여기까지입니다.</p><p class="end-note"><a href="' +
        ((document.querySelector(".tb-link") || {}).getAttribute ? document.querySelector(".tb-link").getAttribute("href") : "archive/") + '">지난 호 보기</a></p>';
      out.push(end);
    }
    if (spread && out.length % 2 === 1) { var bl = newPage(g, "blank", null, false); bl.classList.add("blank"); out.push(bl); }
    out.forEach(function (p, i) { p.querySelector(".folio").textContent = (i + 1) + " / " + out.length; p.setAttribute("data-page", i); });
    linkPages(out);
    // 모든 쪽이 실제로 배치된 지금 넘침을 센다 (넘김 라이브러리에 넘긴 뒤에는 안 보이는 쪽의 높이가 0으로 재어진다)
    overflowPages = out.filter(function (p) { return overflows(p.querySelector(".page-inner")); }).map(function (p) { return +p.getAttribute("data-page"); });
    clipped = stage.querySelectorAll(".item.clip").length;
    demotedCount = stage.querySelectorAll(".item.demoted").length;
    briefCount = stage.querySelectorAll(".item.brief").length;
    emptySummary = Array.prototype.filter.call(stage.querySelectorAll(".item:not(.oplist):not(.opcmp):not(.oppick):not(.an):not(.guide-intro):not(.guide-table)"), function (el) {
      return !el.querySelector(".lead");
    }).length;
    stage.remove();
    return { pages: out, g: g };
  }

  // 1면 3구역(S26b): "▶ N쪽 ○○로 계속"·"오늘의 면" 색인의 쪽 번호를 실제로 나뉜 쪽에서 채운다 (기기마다 쪽이 달라서)
  function linkPages(out) {
    var pageOf = function (sel) {
      for (var i = 0; i < out.length; i++) if (out[i].querySelector(sel)) return i;
      return -1;
    };
    out.forEach(function (p) {
      Array.prototype.forEach.call(p.querySelectorAll(".jump[data-jump]"), function (b) {
        var id = b.getAttribute("data-jump");
        var i = pageOf('article.cont[data-issue="' + id + '"]');
        if (i < 0) i = pageOf('article.item[data-issue="' + id + '"]');   // 이어받는 칸이 단신으로 내려갔을 때
        var n = b.querySelector(".jn");
        if (i < 0) { b.hidden = true; return; }
        b.hidden = false;
        b.setAttribute("data-page", i);
        if (n) n.textContent = (i + 1) + "쪽 ";
      });
    });
    var lists = [];
    out.forEach(function (p) { lists = lists.concat(Array.prototype.slice.call(p.querySelectorAll("[data-index-list]"))); });
    if (!lists.length) return;
    var seen = {}, html = [];
    var extra = { more: "더 읽을 기사", briefs: "단신" };
    out.forEach(function (p, i) {
      var m = /(?:^|\s)sec-([\w-]+)/.exec(p.className), id = m && m[1];
      if (!id || seen[id] || id === "front" || id === "blank" || id === "end") return;
      seen[id] = true;
      var t = (E.sectionTitles || {})[id] || extra[id] || id;
      html.push('<button type="button" class="ix" data-goto="' + i + '">' + t + " <b>" + (i + 1) + "</b></button>");
    });
    lists.forEach(function (l) { l.innerHTML = html.join(""); });
  }

  // ---------- 넘기기 ----------
  function showInfo() {
    var last = pages.length;
    var a = current + 1, b = spread && mode !== "scroll" ? Math.min(current + 2, last) : a;
    pageInfo.textContent = (a === b ? a : a + "–" + b) + " / " + last + "쪽";
    var fr = document.querySelector('[data-act="front"]');
    if (fr) fr.disabled = current === 0;   // 이미 1면이면 누를 일이 없다
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
    if (act === "front") goTo(0);   // 1면으로 (S23d)
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
    readSeq++;
    reader.setAttribute("aria-label", "기사 자세히");
    reader.hidden = false;
    reader.querySelector(".reader-panel").scrollTop = 0;
    reader.querySelector("[data-reader-close]").focus();
  }
  function closeReader() { if (reader) { reader.hidden = true; readSeq++; } }

  // ---------- 원문 창 (S17·S17b) ----------
  // "원문"(또는 입장 차이·사설의 작은 제목)을 누르면 이 창에서 원문을 본다: 중계 서버가 그 자리에서 받아 사진·글만 돌려준다(저장 안 함).
  // 중계 서버가 못 여는 매체(유료 벽·봇 차단)나 실패하면 피드 리드·AI 정리와 안내를 보인다. 한국 매체가 아니면 한국어 번역을 붙인다.
  // 실제 기사 페이지는 "링크"(새 탭)
  var RD = E.reader, readSeq = 0;
  function mk(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text) n.textContent = text; return n; }
  function linkBtn(href, label, big) {
    var a = mk("a", big ? "rv-link rv-link-big" : "rv-link", label);
    a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer";
    return a;
  }
  function figure(im) {
    var f = mk("figure", "rv-photo"), img = document.createElement("img");
    img.src = im.src; img.alt = im.caption || ""; img.loading = "lazy"; img.decoding = "async"; img.referrerPolicy = "no-referrer";
    f.appendChild(img);
    if (im.caption) f.appendChild(mk("figcaption", null, im.caption));
    return f;
  }
  // 중계 서버 부르기. 막 깨어날 때 Cloudflare 가 가끔 503(JSON 아닌 오류 페이지)을 낸다 — 그때만 한 번 더 (실측: 다시 부르면 성공)
  function relay(path, opts, seq, signal) {
    var load = function (left) {
      var o = { headers: { "X-Reader-Key": RD.key }, cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer", signal: signal };
      if (opts && opts.body) { o.method = "POST"; o.body = opts.body; o.headers["Content-Type"] = "application/json"; }
      return fetch(RD.url + path, o).then(function (r) {
        var isJson = /json/.test(r.headers.get("Content-Type") || "");
        if (!isJson && r.status >= 500 && left > 0 && seq === readSeq) return load(left - 1);
        return r.json();
      });
    };
    return load(1);
  }
  // 번역: 문단 요소들(원문 글)을 한국어로 바꿔 보이고, 한국어/원문 전환 단추를 단다
  function translateInto(view, nodes, lang, seq) {
    if (!RD || !lang || lang === "ko" || !nodes.length) return;
    var bar = mk("div", "rv-lang");
    var note = mk("span", "rv-lang-note", "한국어로 옮기는 중…");
    bar.appendChild(note);
    view.insertBefore(bar, view.querySelector(".rv-body"));
    var texts = nodes.map(function (n) { return n.textContent; });
    relay("/translate", { body: JSON.stringify({ lang: lang, texts: texts }) }, seq).then(function (j) {
      if (seq !== readSeq) return;
      if (!j || !j.ok || !j.texts || j.texts.length !== texts.length) { note.textContent = "번역하지 못했습니다" + (j && j.reason ? " (" + j.reason + ")" : ""); return; }
      nodes.forEach(function (n, i) { n.setAttribute("data-orig", texts[i]); n.setAttribute("data-ko", j.texts[i] || texts[i]); n.textContent = j.texts[i] || texts[i]; });
      bar.innerHTML = "";
      ["한국어", "원문"].forEach(function (label, k) {
        var b = mk("button", "rv-tab" + (k === 0 ? " on" : ""), label);
        b.type = "button";
        b.setAttribute("aria-pressed", k === 0 ? "true" : "false");
        b.addEventListener("click", function () {
          nodes.forEach(function (n) { n.textContent = n.getAttribute(k === 0 ? "data-ko" : "data-orig"); });
          Array.prototype.forEach.call(bar.querySelectorAll(".rv-tab"), function (x, m) { x.classList.toggle("on", m === k); x.setAttribute("aria-pressed", m === k ? "true" : "false"); });
        });
        bar.appendChild(b);
      });
      bar.appendChild(mk("span", "rv-lang-note", "AI 번역"));
    }, function () { if (seq === readSeq) note.textContent = "번역하지 못했습니다 (연결 실패)"; });
  }
  function openArticle(el) {
    if (!reader) return;
    var body = reader.querySelector(".reader-body");
    var back = reader.hidden ? null : Array.prototype.slice.call(body.childNodes);   // 자세히 창에서 열었으면 돌아갈 수 있게
    var url = el.getAttribute("data-read"), href = el.getAttribute("data-href") || el.getAttribute("href");
    var lang = el.getAttribute("data-lang") || "ko", srcName = el.getAttribute("data-src") || "";
    var art = el.closest("article.item");
    var isBtn = el.tagName !== "A";   // 메타 줄 "원문" 단추면 그 기사의 (원)제목·리드를 쓴다
    var titleText = isBtn && art ? ((art.querySelector(".orig") || art.querySelector(".hl a") || el).textContent) : el.textContent;
    var leadEl = isBtn && art ? art.querySelector(".lead") : null;
    var view = mk("article", "readview");
    if (back) {
      var bb = mk("button", "rv-back", "← 돌아가기");
      bb.type = "button";
      bb.addEventListener("click", function () { readSeq++; body.innerHTML = ""; back.forEach(function (n) { body.appendChild(n); }); });
      view.appendChild(bb);
    }
    var top = mk("div", "rv-top");
    top.appendChild(mk("span", "rv-src", srcName));
    top.appendChild(linkBtn(href, "링크 ↗"));
    view.appendChild(top);
    var h = mk("h2", "rv-title", titleText.trim());
    view.appendChild(h);
    var status = mk("p", "rv-status", url && RD ? "원문을 불러오는 중…" : "");
    view.appendChild(status);
    var main = mk("div", "rv-body");
    view.appendChild(main);
    body.innerHTML = "";
    body.appendChild(view);
    reader.setAttribute("aria-label", "원문 보기");
    reader.hidden = false;
    reader.querySelector(".reader-panel").scrollTop = 0;
    var seq = ++readSeq;
    // 본문을 못 가져올 때: 피드 리드(또는 AI 정리)와 안내, 링크
    var fallback = function (why) {
      if (seq !== readSeq) return;
      status.textContent = why;
      status.className = "rv-status rv-fail";
      var nodes = [h];
      if (leadEl && leadEl.textContent.trim()) {
        var note = leadEl.getAttribute("data-note");
        if (note) main.appendChild(mk("p", "rv-note", note));
        var lp = mk("p", "rv-p", leadEl.textContent.trim());
        main.appendChild(lp);
        if (!note) nodes.push(lp);   // AI 정리·요약은 이미 한국어
      }
      main.appendChild(linkBtn(href, "원래 기사 열기 ↗", true));
      translateInto(view, nodes, lang, seq);
    };
    if (!url || !RD) {
      fallback(RD && url === "" ? "이 매체는 외부에서 본문을 읽지 못하게 막아 두었습니다(유료 구독·봇 차단). 피드에 실린 내용만 보여 드립니다."
                                 : "본문을 불러올 수 없어 피드에 실린 내용만 보여 드립니다.");
      return;
    }
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); fallback("원문 사이트가 응답하지 않습니다. 피드에 실린 내용만 보여 드립니다."); }, 20000);
    relay("/?url=" + encodeURIComponent(url), null, seq, ctrl ? ctrl.signal : undefined).then(function (j) {
      clearTimeout(timer);
      if (seq !== readSeq) return;
      if (!j || !j.ok || !j.paragraphs || !j.paragraphs.length) {
        fallback("원문을 가져오지 못했습니다" + (j && j.reason ? " (" + j.reason + ")" : "") + ". 피드에 실린 내용만 보여 드립니다.");
        return;
      }
      if (j.title) h.textContent = j.title;
      var when = j.published ? new Date(j.published) : null;
      status.textContent = [j.site, when && !isNaN(when) ? when.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" }) : ""].filter(Boolean).join(" · ");
      var imgs = (j.images || []).slice(), ps = [];
      if (imgs.length) main.appendChild(figure(imgs.shift()));
      j.paragraphs.forEach(function (p, i) {
        var n = mk("p", "rv-p", p);   // textContent 로만 넣는다 (원문 HTML 은 쓰지 않음)
        ps.push(n);
        main.appendChild(n);
        if (imgs.length && i % 4 === 3) main.appendChild(figure(imgs.shift()));
      });
      var foot = mk("p", "rv-foot", "원문을 그 자리에서 받아 사진과 글만 다시 보여 준 화면입니다(저장하지 않음). 저작권은 " + (j.site || srcName || "해당 매체") + "에 있습니다. ");
      foot.appendChild(linkBtn(j.url || href, "원래 기사 열기 ↗"));
      main.appendChild(foot);
      translateInto(view, [h].concat(ps), lang, seq);
    }, function () { clearTimeout(timer); fallback("연결하지 못했습니다. 피드에 실린 내용만 보여 드립니다."); });
  }

  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    var mod = e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0;
    var d = t.closest("a[data-detail]");                      // 기사 제목 → AI 정리(자세히 창)
    if (d && !mod) { e.preventDefault(); var ai = d.closest("[data-issue]"); if (ai) openReader(ai.getAttribute("data-issue")); return; }
    var o = t.closest("[data-art]");                           // "원문"·작은 제목 → 원문 창
    if (o && !mod) { e.preventDefault(); openArticle(o); return; }
    var j = t.closest(".jump[data-page], [data-goto]");          // 1면 "계속"·색인 → 그 쪽으로 (S26b)
    if (j) { e.preventDefault(); goTo(+(j.getAttribute("data-page") || j.getAttribute("data-goto"))); return; }
    var m = t.closest("[data-more]");
    if (m) { var art = m.closest("[data-issue]"); if (art) openReader(art.getAttribute("data-issue")); return; }
    if (t.closest("[data-reader-close]") || t === reader) closeReader();
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && reader && !reader.hidden) closeReader(); }, true);

  // 피드백 버튼은 feedback.js(S9)가 처리한다. 여기서는 이벤트만 알린다.
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("[data-fb]");
    if (!b) return;
    var art = b.closest("[data-issue]");
    document.dispatchEvent(new CustomEvent("news:feedback", {
      detail: { kind: b.getAttribute("data-fb"), issue: art.getAttribute("data-issue"), topic: art.getAttribute("data-topic") }
    }));   // 누른 표시(다시 누르면 취소, S24b)도 feedback.js 가 정한다
  });

  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register((window.EDITION && window.EDITION.base || "") + "sw.js").catch(function () { /* 오프라인 캐시는 선택 기능 */ });
  }

  function goTo(i) {
    if (mode === "scroll") { scrollToPage(i); return; }
    if (flip) { flip.turnToPage(i); current = flip.getCurrentPageIndex(); showInfo(); return; }
    simpleShow(i);
  }

  window.NEWS = { rebuild: function () { build(visibleIssue()); }, go: go, goTo: goTo, openReader: openReader, openArticle: openArticle, setView: setView, setZoom: function (z) { applyZoom(z, null); }, fullscreen: toggleFullscreen, state: function () { return { mode: mode, zoom: zoom, current: current, pages: pages.length, spread: spread, flip: !!flip, overflow: overflowPages.slice(), clipped: clipped, demoted: demotedCount, briefs: briefCount, dropped: dropped, emptySummary: emptySummary }; } };
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
