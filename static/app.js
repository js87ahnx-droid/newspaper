/* ○월 ○일자 뉴스 — 쪽 나누기와 종이 넘김.
 *
 * 1. #flow 의 섹션·기사를 화면 크기에 맞춰 쪽(.page)으로 나눈다 (가로 화면은 좌우 두 쪽 펼침).
 * 2. 손가락을 따라 종이가 접히며 넘어가게 한다 (S30d: 모서리 접힘, 펼침·한 쪽 화면 모두). 동작 줄이기 설정이면 애니메이션 없이 넘긴다.
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
  var anim = false;     // 종이 넘김 사용 중 (펼침 보기면 늘 — 동작 줄이기 설정이어도, S32a. 한 면 보기·쪽 나누는 중엔 false)
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
    document.body.classList.toggle("narrow-page", pw < 560);   // 1면 메인 기사(S26) 글자·사진 크기
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

  // 빈자리 줄이기 (2026-11-03 사용자 "1면·4면·7면·11면처럼 공백이 많이 남지 않게 — 기사를 하나 더 넣거나 글을 더 길게"):
  // 덜 찬 쪽은 ① 면의 마지막 쪽이면 같은 면 분야의 단신·예비 기사를 일반 기사 꼴로 더 싣고 ② 그래도 남으면 위 기사부터 리드를 더 보여 준다(roomy 단계)
  var FILL_MIN = 0.88;   // 이만큼 차면 그대로
  var ROOMY = ["roomy", "roomier", "roomiest"];
  var SECTION_TOPICS = { politics: ["politics"], economy: ["economy", "industry", "semis_ai"], international: ["international"], society: ["society", "science"] };
  function usedRatio(inner) {
    var r = inner.getBoundingClientRect(), bottom = r.top;
    Array.prototype.forEach.call(inner.children, function (c) { var b = c.getBoundingClientRect(); if (b.height > 0) bottom = Math.max(bottom, b.bottom); });
    return r.height ? (bottom - r.top) / r.height : 1;
  }
  function roomier(inner) {
    if (usedRatio(inner) >= FILL_MIN) return;
    var items = Array.prototype.filter.call(inner.querySelectorAll(".item"), function (it) {
      return !/(^|\s)(brief|compact|tight|clip)(\s|$)/.test(it.className) && it.querySelector(".lead");
    });
    for (var lv = 0; lv < ROOMY.length; lv++) {
      for (var i = 0; i < items.length; i++) {
        if (usedRatio(inner) >= FILL_MIN) return;
        var it = items[i];
        if (lv > 0 && !it.classList.contains(ROOMY[lv - 1])) continue;   // 앞 단계가 넘쳤던 기사는 더 늘리지 않는다
        it.classList.add(ROOMY[lv]);
        if (overflows(inner)) it.classList.remove(ROOMY[lv]);
      }
    }
    // S48: 요약을 다 보여 줘도 남으면(요약이 짧은 기사) 지면에서 접어 둔 배경 → 매체별 관점·입장 차이를 편다
    for (var lx = 0; lx < MORE.length; lx++) {
      for (var j = 0; j < items.length; j++) {
        if (usedRatio(inner) >= FILL_MIN) return;
        var x = items[j];
        if (lx > 0 && !x.classList.contains(MORE[lx - 1])) continue;
        if (!x.querySelector(MORE_SEL[lx])) { if (lx === 0) x.classList.add(MORE[0]); continue; }   // 배경이 없으면 관점 단계로 바로
        x.classList.add(MORE[lx]);
        if (overflows(inner)) x.classList.remove(MORE[lx]);
      }
    }
  }
  var MORE = ["more-bg", "more-views"], MORE_SEL = [".an-bg", ".an-views, .cmp-inline"];
  function unroom(inner) {
    Array.prototype.forEach.call(inner.querySelectorAll(".item"), function (it) {
      ROOMY.concat(MORE).forEach(function (c) { it.classList.remove(c); });
    });
  }
  // S48 (2026-11-14 사용자 "패드에서 4면에 기사 하나만 짧게 — 3면 마지막 기사를 넘기든지, 미리보기를 늘리든지, 기기별로"):
  // 면 안에서 덜 찬 쪽이 있으면 앞 쪽의 마지막 기사를 이 쪽 맨 앞으로 옮겨 보고, 두 쪽 모두 다시 늘려(roomier) 덜 찬 쪽이 나아질 때만 남긴다.
  // 쪽 크기에서 재므로 휴대폰·패드가 저마다 다르게 맞춰진다. 기사 순서는 그대로
  // 한 쪽이 덜 찼으면 이웃 쪽 기사 하나를 옮겨 본다: 덜 찬 쪽이 뒤면 앞 쪽의 마지막 기사를 맨 앞으로, 앞이면 뒤 쪽의 첫 기사를 맨 끝으로.
  // 옮긴 뒤 두 쪽 모두 넘치지 않고 덜 찬 쪽 비율이 나아질 때만 남긴다 (아니면 되돌림)
  function bodyItems(inner) { return Array.prototype.filter.call(inner.children, function (c) { return c.classList.contains("item"); }); }
  function tryMove(prev, cur, backward) {
    var from = backward ? prev : cur, to = backward ? cur : prev;
    if (prev.querySelector("[data-page-end]")) return false;   // 1면 첫 쪽은 메인 기사 하나 (S26)
    var its = bodyItems(from);
    var mv = backward ? from.lastElementChild : its[0];
    if (!mv || !mv.classList.contains("item") || mv.classList.contains("clip") || its.length < 2) return false;
    var before = Math.min(usedRatio(prev), usedRatio(cur));
    var snap = Array.prototype.map.call(prev.querySelectorAll(".item"), function (it) { return [it, it.className]; })
      .concat(Array.prototype.map.call(cur.querySelectorAll(".item"), function (it) { return [it, it.className]; }));
    var home = mv.nextSibling;
    unroom(prev); unroom(cur);
    if (backward) {
      var at = Array.prototype.filter.call(cur.children, function (c) { return !c.classList.contains("sec-title"); })[0] || null;
      cur.insertBefore(mv, at);
    } else prev.appendChild(mv);
    // 앞 쪽 끝에 맞추느라 줄였던 기사(compact·tight)는 새 쪽에서 원래 꼴로 되돌려 본다 (리뷰 Major 1)
    mv.classList.remove("compact", "tight");
    if (overflows(to)) mv.classList.add("compact");
    if (overflows(to)) mv.classList.add("tight");
    var ok = !overflows(to);
    if (ok) { roomier(prev); roomier(cur); ok = !overflows(prev) && !overflows(cur) && Math.min(usedRatio(prev), usedRatio(cur)) > before + 0.02; }
    if (!ok) {
      from.insertBefore(mv, home);
      snap.forEach(function (s) { s[0].className = s[1]; });
    }
    return ok;
  }
  function balance(pages) {
    pages.forEach(function (p) { roomier(p.firstChild); });
    var i, tries;
    for (i = pages.length - 1; i >= 1; i--)      // 뒤 쪽이 덜 찼으면 앞 쪽 끝 기사를 넘겨 받는다
      for (tries = 0; tries < 3 && usedRatio(pages[i].firstChild) < FILL_MIN; tries++)
        if (!tryMove(pages[i - 1].firstChild, pages[i].firstChild, true)) break;
    for (i = 0; i < pages.length - 1; i++)       // 앞 쪽이 덜 찼으면 뒤 쪽 첫 기사를 당겨 온다 (S48 재시험: 종합면 첫 쪽 70%)
      for (tries = 0; tries < 3 && usedRatio(pages[i].firstChild) < FILL_MIN; tries++)
        if (!tryMove(pages[i].firstChild, pages[i + 1].firstChild, false)) break;
  }
  // 면의 끝 쪽에 기사가 조금만 남았으면(절반 못 참) 앞 쪽 기사를 줄여(compact → tight, 아래 기사부터) 그 쪽으로 합치고 끝 쪽을 없앤다.
  // 비게 된 쪽은 단신·더 읽을 기사가 쓴다. 다 안 들어가는데 끝 쪽이 40% 도 못 차고 기사가 둘 이하면 그 기사들을 단신으로 내리고
  // 쪽을 없앤다 (면의 점수 낮은 기사 — 쪽 수를 줄이는 쪽이 빈 쪽보다 낫다). 단신으로 내린 기사의 data-issue 를 돌려준다
  function mergeOrphan(pages) {
    if (pages.length < 2) return [];
    var li = pages[pages.length - 1].firstChild, pi = pages[pages.length - 2].firstChild;
    var ratio = usedRatio(li);
    if (ratio >= 0.5) return [];
    var moving = Array.prototype.filter.call(li.children, function (c) { return c.classList.contains("item"); });
    if (!moving.length || moving.length !== li.children.length - (li.querySelector(".sec-title") ? 1 : 0)) return [];
    var added = [];
    moving.forEach(function (n) { pi.appendChild(n); });
    var items = Array.prototype.slice.call(pi.querySelectorAll(":scope > .item")).reverse();
    ["compact", "tight"].forEach(function (cls) {
      items.forEach(function (it) {
        if (!overflows(pi) || it.classList.contains(cls) || it.classList.contains("fz")) return;
        it.classList.add(cls); added.push([it, cls]);
      });
    });
    if (overflows(pi)) {
      added.forEach(function (x) { x[0].classList.remove(x[1]); });
      moving.forEach(function (n) { li.appendChild(n); });
      if (ratio >= 0.4 || moving.length > 2) return [];
      pages.pop().remove();
      return moving.map(function (n) { return n.getAttribute("data-issue"); });
    }
    pages.pop().remove();
    return [];
  }
  function pullReserves(id, pages, reserves, pulled) {
    var topics = SECTION_TOPICS[id];
    if (!topics || !pages.length) return;
    var inner = pages[pages.length - 1].firstChild;
    for (var k = 0; k < reserves.length && usedRatio(inner) < FILL_MIN; k++) {
      var el = reserves[k];
      if (pulled.indexOf(el) >= 0 || topics.indexOf(el.getAttribute("data-topic")) < 0) continue;
      var node = el.cloneNode(true);
      node.setAttribute("data-pulled", "1");
      inner.appendChild(node);
      if (overflows(inner)) node.classList.add("compact");
      if (overflows(inner)) { inner.removeChild(node); continue; }
      pulled.push(el);
    }
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

  // ---------- 단신 탭 쪽 (S47, 사용자 시안 B) ----------
  // 분야 탭(전체·분야별 건수) + 고른 탭의 위 기사를 쪽에 들어가는 만큼 한 줄씩 (S48: 기기마다 — 휴대폰 10건 안팎, 패드 20건 안팎).
  // 탭마다 "○○ 전체 보기"(그 탭 목록 → 자세히 창). 그 탭을 다 보여 줬으면 단추를 끈다
  var BRIEF_TOP = 40;   // 쪽이 아무리 커도 이 이상은 창으로
  var briefAll = [], briefTabSeq = 0;
  function selectBriefTab(bt, focus) {
    var box = bt.closest(".btabs");
    Array.prototype.forEach.call(box.querySelectorAll("[data-bt]"), function (x) {
      var on = x === bt;
      x.setAttribute("aria-selected", on ? "true" : "false");
      x.tabIndex = on ? 0 : -1;
    });
    Array.prototype.forEach.call(box.querySelectorAll(".bt-list, .bt-all"), function (x) {
      x.hidden = (x.getAttribute("data-bt-list") || x.getAttribute("data-bt-all")) !== bt.getAttribute("data-bt");
    });
    if (focus) bt.focus();
  }
  document.addEventListener("keydown", function (e) {   // 탭: 좌우 화살표·Home·End
    var bt = e.target && e.target.closest ? e.target.closest("[data-bt]") : null;
    if (!bt) return;
    var all = Array.prototype.slice.call(bt.closest(".bt-tabs").querySelectorAll("[data-bt]"));
    var i = all.indexOf(bt), to = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: all.length - 1 }[e.key];
    if (to === undefined) return;
    e.preventDefault();
    e.stopPropagation();   // 지면 넘기기 화살표와 겹치지 않게
    selectBriefTab(all[(to + all.length) % all.length], true);
  }, true);
  function briefRow(el) {
    var li = mk("li", "bt-row");
    li.setAttribute("data-issue", el.getAttribute("data-issue"));
    var a = el.querySelector(".hl a");
    li.appendChild(a ? a.cloneNode(true) : mk("span", "bt-t", el.getAttribute("data-brief") || ""));
    var src = el.querySelector(".meta .src");
    if (src) li.appendChild(mk("span", "bt-src", src.textContent));
    return li;
  }
  function briefGroups(els) {
    var by = {}, keys = [];
    (E.briefTopics || []).forEach(function (t) { by[t] = []; keys.push(t); });
    els.forEach(function (el) {
      var t = el.getAttribute("data-topic");
      if (!by[t]) { by[t] = []; keys.push(t); }
      by[t].push(el);
    });
    return keys.filter(function (t) { return by[t].length; }).map(function (t) { return { key: t, name: (E.topics || {})[t] || "기타", els: by[t] }; });
  }
  function briefTabsPage(stage, g, title, els) {
    var page = newPage(g, "briefs", title || "단신", false);
    stage.appendChild(page);
    var inner = page.firstChild;
    var box = mk("div", "btabs");
    var tabs = mk("div", "bt-tabs");
    tabs.setAttribute("role", "tablist");
    box.appendChild(tabs);
    inner.appendChild(box);
    var groups = [{ key: "all", name: "전체", els: els }].concat(briefGroups(els));
    briefTabSeq++;
    groups.forEach(function (gr, i) {
      var b = mk("button", "bt-tab", gr.name + " " + gr.els.length);
      b.type = "button";
      b.id = "bt-" + briefTabSeq + "-" + gr.key;
      b.setAttribute("role", "tab");
      b.setAttribute("data-bt", gr.key);
      b.setAttribute("aria-controls", "btl-" + briefTabSeq + "-" + gr.key);
      b.setAttribute("aria-selected", i === 0 ? "true" : "false");
      b.tabIndex = i === 0 ? 0 : -1;   // 탭 목록은 한 번에 들어가고, 안에서는 화살표로 (roving tabindex)
      tabs.appendChild(b);
    });
    groups.forEach(function (gr) {
      var ol = mk("ol", "bt-list");
      ol.id = "btl-" + briefTabSeq + "-" + gr.key;
      ol.setAttribute("data-bt-list", gr.key);
      ol.setAttribute("role", "tabpanel");
      ol.setAttribute("aria-labelledby", "bt-" + briefTabSeq + "-" + gr.key);
      box.appendChild(ol);
      var more = mk("button", "bt-all", (gr.key === "all" ? "" : gr.name + " ") + "전체 보기 · " + gr.els.length + "건");
      more.type = "button";
      more.setAttribute("data-bt-all", gr.key);
      box.appendChild(more);
      // 쪽에 들어가는 만큼만 (S48: 기기마다 다름) — 재는 동안은 이 목록·단추만 보인다
      Array.prototype.forEach.call(box.querySelectorAll(".bt-list, .bt-all"), function (x) { x.hidden = x !== ol && x !== more; });
      var k = 0;
      for (; k < gr.els.length && k < BRIEF_TOP; k++) {
        var li = briefRow(gr.els[k]);
        ol.appendChild(li);
        if (overflows(inner)) { ol.removeChild(li); break; }
      }
      if (k >= gr.els.length) {   // 이 탭은 쪽에 다 보였다 → 더 볼 것 없음
        more.disabled = true;
        more.textContent = (gr.key === "all" ? "" : gr.name + " ") + gr.els.length + "건 모두 보임";
        if (overflows(inner) && ol.lastChild) {   // 글이 바뀌어 넘치면 한 줄 빼고 단추를 다시 켠다 (리뷰 Nit 8)
          ol.removeChild(ol.lastChild);
          more.disabled = false;
          more.textContent = (gr.key === "all" ? "" : gr.name + " ") + "전체 보기 · " + gr.els.length + "건";
        }
      }
    });
    Array.prototype.forEach.call(box.querySelectorAll(".bt-list, .bt-all"), function (x) {
      x.hidden = (x.getAttribute("data-bt-list") || x.getAttribute("data-bt-all")) !== "all";
    });
    return page;
  }
  // 단신 전체 보기 창: key 가 "all" 이면 분야별로 모두, 분야면 그 분야만 (S48)
  function openBriefAll(key) {
    if (!reader) return;
    var groups = briefGroups(briefAll);
    if (key && key !== "all") groups = groups.filter(function (gr) { return gr.key === key; });
    if (!groups.length) return;
    var n = groups.reduce(function (s, gr) { return s + gr.els.length; }, 0);
    var body = reader.querySelector(".reader-body");
    body.innerHTML = "";
    var wrap = mk("div", "bt-full");
    var label = (key && key !== "all" ? groups[0].name + " 단신 " : "단신 ") + n + "건";
    wrap.appendChild(mk("h3", "bt-full-h", label));
    groups.forEach(function (gr) {
      wrap.appendChild(mk("h4", "brief-topic", gr.name + " " + gr.els.length));
      gr.els.forEach(function (el) { var b = asBrief(el); b.classList.remove("demoted"); wrap.appendChild(b); });
    });
    body.appendChild(wrap);
    readSeq++;
    reader.setAttribute("aria-label", label);
    reader.setAttribute("data-list-label", label);
    showReader();
  }

  // 논평면 (S55): 1편 덩어리 순서를 지키되, 큰 비교 덩어리가 안 들어가 쪽 아래가 비면 다음 묶음의 첫 덩어리부터 당겨 채운다
  var OP_ORDER = { keepOrder: true, groupKey: function (n) { return (n.getAttribute("data-issue") || "").replace(/-\d+$/, "").replace(/^(op-cmp|op-ed|op-col|op-pick).*/, "$1"); } };
  // 섹션 하나를 최대 budget 쪽에 배치 (budget 0 = 제한 없음). 못 들어간 원본 요소는 rest 로 돌려준다
  // opts.grouped: 단신 분야 묶음 — 뒤 기사로 빈자리 채우기를 하지 않고(분야 순서 유지), 새 쪽엔 소제목을 다시 단다
  function placeSection(stage, g, sec, first, budget, nodes, mast, opts) {
    var grouped = opts && opts.grouped;
    var keepOrder = grouped || (opts && opts.keepOrder);   // S49 종합면: 묶음·띠 순서가 흐트러지지 않게 뒤 기사 끼워 넣기만 끈다
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
      if (placedOnPage > 0 && inner.querySelector("[data-page-end]")) {   // 1면 첫 쪽은 메인 기사 하나로 끝낸다 (S26)
        out.push(page);
        page = mk(true);
        stage.appendChild(page);
        inner = page.firstChild;
        placedOnPage = 0;
      }
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
      // 빈자리가 크면(쪽의 30% 넘게 남음) 이 기사를 줄여서라도 이 쪽에 싣는다 (2026-11-03 "공백이 많이 남지 않게")
      if (!grouped && usedRatio(inner) < 0.7) {
        inner.appendChild(node);
        node.classList.add("compact");
        if (!overflows(inner)) { placedOnPage++; return; }
        node.classList.add("tight");
        if (!overflows(inner)) { placedOnPage++; return; }
        node.classList.remove("compact", "tight");
        inner.removeChild(node);
      }
      // 새 쪽으로 넘기기 전에, 뒤 기사 중 남은 자리에 들어가는 것으로 빈자리를 채운다 (한 쪽 아래가 비지 않게)
      // opts.groupKey(S55 논평면): 순서를 지키되 묶음(지정 칼럼·비교·사설 목록·칼럼 목록)마다 아직 안 실은 첫 덩어리는 당겨 올 수 있다
      var gk = opts && opts.groupKey;
      for (var j = k + 1; j < nodes.length && (!keepOrder || gk); j++) {
        if (used[j]) continue;
        if (gk) {
          var gkey = gk(nodes[j].node), headOfGroup = true;
          for (var q = k; q < j && headOfGroup; q++) if (!used[q] && gk(nodes[q].node) === gkey) headOfGroup = false;
          if (!headOfGroup) continue;
        }
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

  // 논평면 이어지는 덩어리 (S55 리뷰 M1): 앞이 같은 묶음이 아니면(다른 묶음이 끼어듦·쪽 첫머리) "○○ (계속)" 소제목을 단다
  function opinionHeads(pages) {
    pages.forEach(function (page) {
      Array.prototype.forEach.call(page.querySelectorAll(".page-inner > article.op-cont"), function (a) {
        var g = a.getAttribute("data-group"), prev = a.previousElementSibling;
        if (prev && (prev.getAttribute("data-group") === g || prev.classList.contains("sec-title"))) return;   // 쪽 첫머리는 쪽 머리 "(계속)"으로 충분 (재리뷰 M2)
        var h = mk("h3", "hl op-conth", (a.getAttribute("data-group-title") || "") + " (계속)");
        a.insertBefore(h, a.firstChild);
        a.classList.add("op-restart");   // 위 테두리로 앞 묶음과 갈라 보이게
        if (overflows(page.firstChild)) { h.remove(); a.classList.remove("op-restart"); a.classList.add("op-gap"); }   // 소제목 때문에 넘치면 빼고 원래대로 (앞 묶음의 아래 실선이 갈라 줌)
      });
    });
  }
  // 중국은 지금 한 쪽 (S54 ②): 지면 쪽엔 앞부분 + 들어가는 만큼의 "다른 나라 매체" 줄. 넘치면 핵심어 → 강조·말하지 않은 것 3개
  // → 해석 4줄 → 강조·말하지 않은 것 2개 순으로 줄이고, 그래도 넘치면(글자를 키운 경우) 지금처럼 fit. 숨긴 것은 #flow 원본엔 있어 창에선 모두 보인다
  function fitChina(pages) {
    var page = pages[0];
    if (!page) return;
    var inner = page.firstChild, node = inner.querySelector("article.cn-view");
    if (!node || mode === "scroll") return;   // 스크롤 보기는 쪽 높이가 없으니 전부 (구현 리뷰 B1)
    node.classList.remove("compact", "tight", "clip");
    node.style.maxHeight = "";
    var hide = function (el) { if (el) el.setAttribute("data-cn-hide", ""); };
    var show = function (el) { if (el) el.removeAttribute("data-cn-hide"); };
    var keep = function (n) {
      Array.prototype.forEach.call(node.querySelectorAll(".cn-own ul"), function (ul) {
        Array.prototype.forEach.call(ul.children, function (li, i) { if (i >= n) hide(li); });
      });
    };
    Array.prototype.forEach.call(node.querySelectorAll(".cn-agenda, .cn-ev, .cn-cmpbox, .cn-row"), hide);
    var steps = [
      function () { hide(node.querySelector(".cn-words")); },
      function () { keep(3); },
      function () { node.classList.add("cn-lead4"); },
      function () { keep(2); },
    ];
    for (var i = 0; i < steps.length && overflows(inner); i++) steps[i]();
    if (overflows(inner)) { fit(inner, node); return; }
    var box = node.querySelector(".cn-cmpbox");
    if (!box) return;
    show(box);
    var rows = node.querySelectorAll(".cn-row"), shown = 0;
    for (var k = 0; k < rows.length; k++) {
      show(rows[k]);
      if (overflows(inner)) { hide(rows[k]); break; }
      shown++;
    }
    if (!shown) hide(box);
  }

  // 종합면 묶음 정리 (S49): 둘째 묶음의 띠 기사가 쪽에 못 실렸으면 그 묶음 나머지도 빼고(띠 없이 메인 묶음처럼 보이지 않게),
  // 띠의 "기사 n건"을 실제로 실린 수로 고친다
  function fixJonghap(pages) {
    var items = [];
    pages.forEach(function (p) { Array.prototype.push.apply(items, p.firstChild.querySelectorAll(":scope > .item[data-jh-group]")); });
    var g1 = items.filter(function (el) { return el.getAttribute("data-jh-group") === "1"; });
    if (g1.length && !g1.some(function (el) { return el.querySelector(".jh-band"); })) {
      g1.forEach(function (el) { el.remove(); dropped++; });
      g1 = [];
    }
    var n0 = items.filter(function (el) { return el.getAttribute("data-jh-group") === "0"; }).length;
    pages.forEach(function (p) {
      var th = p.firstChild.querySelector(".jh-theme.jh-named .jh-n");
      if (th) th.textContent = " · 기사 " + n0 + "건";
      var bd = p.firstChild.querySelector(".jh-band .jh-n");
      if (bd) bd.textContent = " · 기사 " + g1.length + "건";
    });
  }

  // 큐레이션 판 (S50): 면마다 핵심 기사 + 면 끝 "함께 볼 기사" 목록 칸(.more-list, 기사 원본은 #flow 의 숨은 .curated-src)
  var CURATED = !!E.curated;
  var CURATE_IDS = ["politics", "economy", "international", "society", "interest"];   // 종합면은 큐레이션 판에서 창으로 접힘 (S51)
  function listSources(list) {   // 목록 칸 줄이 가리키는 숨은 원본 기사들
    return Array.prototype.map.call(list.querySelectorAll("[data-open]"), function (a) {
      return flow.querySelector('.curated-src > article.item[data-issue="' + a.getAttribute("data-open") + '"]');
    }).filter(Boolean);
  }
  // 목록 칸이 넘쳤거나 기사 없이 혼자 끝 쪽에 남았으면: 앞 쪽 끝에 들어가는 줄만 남기고(아래 줄부터 뺌), 뺀 줄의 기사는
  // 단신 후보로 돌려준다 (S50 결정 22·28, 계획 리뷰 4차 M2 — 제목 한 줄을 기사 꼴로 키우지 않게)
  function fitList(ml, inner) {
    var out = [];
    inner.appendChild(ml);
    var lis = Array.prototype.slice.call(ml.querySelectorAll("li"));
    while (overflows(inner) && lis.length) { out = out.concat(listSources(lis[lis.length - 1])); lis.pop().remove(); }
    if (!lis.length) ml.remove();
    return out;
  }
  // 큐레이션 면 끝 쪽에 기사가 1건 이하·절반도 안 차면(S51 ⑤ — 11/17 정치면 둘째 쪽 30%) 끝 쪽의 기사·목록 칸을 앞 쪽으로 옮기고
  // 아래 기사부터 줄여(compact → tight) 맞춘다. 그래도 넘치면 목록 줄을 아래부터 빼 보고(뺀 기사는 단신 후보), 안 되면 되돌린다
  function mergeTail(res) {
    var pages = res.pages, out = [];
    if (pages.length < 2) return out;
    var li = pages[pages.length - 1].firstChild, pi = pages[pages.length - 2].firstChild;
    if (li.querySelectorAll(":scope > article.item").length > 1 || usedRatio(li) >= 0.5) return out;
    var moving = Array.prototype.filter.call(li.children, function (c) { return c.matches("article.item, .more-list"); });
    if (!moving.length || moving.length !== li.children.length - (li.querySelector(".sec-title") ? 1 : 0)) return out;   // 다른 칸이 있으면 손대지 않음 (재리뷰 N1)
    moving.forEach(function (n) { pi.appendChild(n); });
    var added = [], cut = [];
    var items = Array.prototype.slice.call(pi.querySelectorAll(":scope > article.item")).reverse();
    ["compact", "tight"].forEach(function (cls) {
      items.forEach(function (it) {
        if (!overflows(pi) || it.classList.contains(cls)) return;
        it.classList.add(cls); added.push([it, cls]);
      });
    });
    var ml = pi.querySelector(":scope > .more-list");
    var lis = ml ? Array.prototype.slice.call(ml.querySelectorAll("li")) : [];
    while (overflows(pi) && lis.length) { var l = lis.pop(); cut.push(l); l.remove(); }
    if (overflows(pi)) {   // 못 합침 — 그대로
      cut.reverse().forEach(function (l) { ml.querySelector("ul").appendChild(l); });
      added.forEach(function (x) { x[0].classList.remove(x[1]); });
      moving.forEach(function (n) { li.appendChild(n); });
      return out;
    }
    cut.forEach(function (l) { out = out.concat(listSources(l)); });
    if (ml && !ml.querySelector("li")) ml.remove();
    pages.pop().remove();
    return out;
  }
  function fixMoreList(res) {
    var out = [];
    res.rest = res.rest.filter(function (r) {
      if (!(r.el.classList && r.el.classList.contains("more-list"))) return true;
      var last = res.pages[res.pages.length - 1];
      out = out.concat(last ? fitList(r.node || r.el.cloneNode(true), last.firstChild) : listSources(r.el));
      return false;
    });
    var last = res.pages[res.pages.length - 1];
    var ml = last && last.firstChild.querySelector(":scope > .more-list");
    if (ml && res.pages.length > 1 && !last.firstChild.querySelector(":scope > .item")) {
      res.pages.pop().remove();
      out = out.concat(fitList(ml, res.pages[res.pages.length - 1].firstChild));
    }
    return out;
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
    var built = {}, demoted = [], listOver = [], spare = 0, firstId = order[0];   // listOver: 목록 칸에서 넘친 기사 — 단신 탭으로만 (S50)
    // 덜 찬 면 끝 쪽으로 올릴 후보: 같은 분야의 단신(원래 단신 먼저) → 예비 기사. 올린 것은 단신·더 읽을 기사에서 뺀다
    var bkids = byId.briefs ? Array.prototype.slice.call(byId.briefs.children) : [];
    var reserveEls = bkids.filter(function (el) { return el.getAttribute("data-reserve") !== "1"; })
      .concat(bkids.filter(function (el) { return el.getAttribute("data-reserve") === "1"; }));
    var pulled = [];
    var kids = function (sec) {
      return Array.prototype.filter.call(sec.children, function (el) { return el.getAttribute("data-reserve") !== "1"; })
        .map(function (el) { return { el: el, node: el.cloneNode(true) }; });
    };
    // 1) 뉴스 면: 정해진 쪽 안에서, 넘친 기사는 단신으로 내린다 / 논평·가이드: 정해진 쪽 안에서만
    order.forEach(function (id) {
      if (id === "briefs") return;
      var b = budgets[id] || 0;
      var cur = CURATED && CURATE_IDS.indexOf(id) >= 0;
      var res = placeSection(stage, g, byId[id], id === firstId, b, kids(byId[id]), mast, id === "opinion" ? OP_ORDER : id === "jonghap" || cur ? { keepOrder: true } : null);   // S55: 논평면 1편 덩어리는 순서대로 (뒤 덩어리를 앞 빈자리로 당기면 목록이 흩어짐)
      built[id] = res.pages;
      var fromList = cur ? fixMoreList(res) : [];
      if (cur) fromList = fromList.concat(mergeTail(res));   // S51 ⑤
      if (["opinion", "guide", "analysis", "china", "jonghap"].indexOf(id) < 0 && !cur) {   // 종합면(S47)은 두 쪽 그대로 — 끝 쪽 기사를 단신으로 내리지 않는다
        mergeOrphan(res.pages).forEach(function (iss) {
          var el = byId[id].querySelector(':scope > [data-issue="' + iss + '"]');
          if (el) res.rest.push({ el: el });
        });
      }
      if (!res.rest.length && !CURATED) pullReserves(id, res.pages, reserveEls, pulled);   // 큐레이션 판은 예비 기사를 면에 끌어오지 않는다 (S50)   // 넘쳐 내린 기사가 없는 면만 (끝 쪽이 남은 것)
      if (["opinion", "guide", "analysis", "china"].indexOf(id) < 0) balance(res.pages);
      if (cur) fromList = fromList.concat(mergeTail(res), fixMoreList(res));   // 쪽 고르기(balance)가 끝 쪽을 다시 1건으로 만들 수 있어 한 번 더 (재리뷰 M2), 목록 칸만 남은 끝 쪽도 (S50)
      if (id === "jonghap") fixJonghap(res.pages);
      if (id === "china") fitChina(res.pages);
      if (id === "opinion") opinionHeads(res.pages);
      if (id !== "opinion" && id !== "guide" && id !== "analysis" && id !== "jonghap") demoted = demoted.concat(res.rest.map(function (r) { return r.el; }));
      else { dropped += res.rest.length; if (id === "opinion") opRest = res.rest.length; }
      listOver = listOver.concat(fromList);   // 제목 한 줄이던 목록 기사를 기사 꼴로 키우지 않게 단신으로만 (S50 계획 리뷰 4차 M2)
      if (b) spare += Math.max(0, b - res.pages.length);
    });
    // 2) 단신 (S47, 사용자 시안 B): 1쪽 — 분야 탭 + 고른 탭의 위 기사(쪽에 들어가는 만큼, S48), 탭마다 "전체 보기" 창. 단신 예산의 나머지 쪽은 남는 쪽으로:
    //    ① 논평면이 못 실은 사설·칼럼 ② "더 읽을 기사"(다른 면에서 내려온 기사 → 예비 기사, 일반 기사 꼴) ③ 끝 쪽
    var briefSec = byId.briefs || (function () {
      var s = document.createElement("section");
      s.className = "sec sec-briefs"; s.setAttribute("data-section", "briefs");
      s.setAttribute("data-title", (E.sectionTitles || {}).briefs || "단신");
      return s;
    })();
    demoted.sort(function (x, y) { return (+y.getAttribute("data-final2") || +y.getAttribute("data-final")) - (+x.getAttribute("data-final2") || +x.getAttribute("data-final")); });
    var pool = demoted.concat(listOver, Array.prototype.filter.call(briefSec.children, function (el) { return el.getAttribute("data-reserve") !== "1" && pulled.indexOf(el) < 0; }),
      Array.prototype.filter.call(briefSec.children, function (el) { return el.getAttribute("data-reserve") === "1" && pulled.indexOf(el) < 0; }));
    // 오늘 없는 면(종합면·중국은 지금·논평이 없는 날)에 배정된 쪽도 남는 쪽
    Object.keys(budgets).forEach(function (k) { if (k !== "briefs" && k !== "compare" && !byId[k]) spare += budgets[k] || 0; });
    var briefPages = budgets.briefs ? 1 : 0;
    spare += Math.max(0, (budgets.briefs || 0) - briefPages);
    // ① 남는 쪽은 논평면이 못 실은 사설·칼럼이 먼저 쓴다 (S17e)
    if (opRest && byId.opinion && spare > 0) {
      var had = built.opinion.length;
      built.opinion.forEach(function (p) { p.remove(); });
      var more = placeSection(stage, g, byId.opinion, false, (budgets.opinion || 0) + spare, kids(byId.opinion), null, OP_ORDER);   // S55: 순서대로
      built.opinion = more.pages;
      opinionHeads(more.pages);   // 다시 놓은 쪽에도 "(계속)" (재리뷰 M1)
      spare -= more.pages.length - had;
      dropped += more.rest.length - opRest;
    }
    // ② 더 읽을 기사: 다른 면에서 내려온 기사가 예비 기사보다 먼저 (S18). 원래 단신은 단신 쪽(탭)에
    var reservesEl = CURATED ? demoted.slice()   // 큐레이션 판: 남는 쪽엔 면에서 내려온 기사만, 예비 기사는 단신 탭으로 (S50)
      : demoted.concat(pool.filter(function (el) { return el.getAttribute("data-reserve") === "1"; }));
    if (spare > 0 && reservesEl.length) {
      var moreSec = document.createElement("section");
      moreSec.className = "sec sec-more"; moreSec.setAttribute("data-section", "more");
      moreSec.setAttribute("data-title", "더 읽을 기사");
      var mres = placeSection(stage, g, moreSec, false, spare,
        reservesEl.map(function (el) { return { el: el, node: el.cloneNode(true) }; }), null);
      var placedMore = reservesEl.filter(function (el) { return !mres.rest.some(function (r) { return r.el === el; }); });
      built.more = mres.pages;
      balance(mres.pages);
      spare -= mres.pages.length;
      pool = pool.filter(function (el) { return placedMore.indexOf(el) < 0; });
      if (order.indexOf("more") < 0) order.splice(order.indexOf("briefs") >= 0 ? order.indexOf("briefs") : (order.indexOf("opinion") >= 0 ? order.indexOf("opinion") : order.length), 0, "more");
    }
    briefAll = pool;
    if (pool.length && briefPages) {
      built.briefs = [briefTabsPage(stage, g, briefSec.getAttribute("data-title"), pool)];
      if (order.indexOf("briefs") < 0) order.splice(Math.max(0, order.indexOf("opinion")) || order.length, 0, "briefs");
    } else {
      built.briefs = [];
      dropped += pool.length;
      briefAll = [];
    }
    var total = 0;
    Object.keys(budgets).forEach(function (k) { total += budgets[k] || 0; });
    var out = [];
    order.forEach(function (id) { out = out.concat(built[id] || []); });
    // 쪽수 고정: 기사가 모자라 쪽이 남으면 끝 쪽으로 채운다 (같은 화면 크기면 호가 바뀌어도 쪽수가 같다)
    while (total && !CURATED && out.length < total) {   // 큐레이션 판은 줄인 만큼 쪽도 준다 (S50)
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
    briefCount = briefAll.length;   // 단신 탭 쪽·"전체 보기" 창에 실린 단신 (S47·S48)
    emptySummary = Array.prototype.filter.call(stage.querySelectorAll(".item:not(.oplist):not(.opcmp):not(.oppick):not(.an):not(.guide-intro):not(.guide-table)"), function (el) {
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
    var fr = document.querySelector('[data-act="front"]');
    if (fr) fr.disabled = current === 0;   // 이미 1면이면 누를 일이 없다
  }

  function build(keepIssue, keepPage) {
    stopTurn();
    drag = null;
    anim = false;
    book.innerHTML = "";
    leaves = [];
    endSheet();
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
    pages.forEach(function (p, i) { p.classList.toggle("pg-left", spread && mode !== "scroll" && i % 2 === 0); });
    if (mode === "scroll") { buildScroll(res.g, start); return; }
    anim = true;
    book.className = (spread ? "spread" : "single") + " anim";
    book.style.width = (spread ? res.g.w * 2 : res.g.w) + "px";
    book.style.height = res.g.h + "px";
    pw = res.g.w; ph = res.g.h;
    S = Math.ceil(2 * Math.hypot(pw, ph)) + 4;
    leaves = pages.map(function (p) { var o = leafOf(p); book.appendChild(o.leaf); return o; });
    var bp = document.createElement("div");
    bp.className = "turn-back";
    bp.style.width = pw + "px"; bp.style.height = ph + "px";
    ghost = document.createElement("div");
    ghost.className = "turn-ghost";
    bp.appendChild(ghost);
    ghostOf = -1;
    backLeaf = leafOf(bp);
    book.appendChild(backLeaf.leaf);
    mask = document.createElement("div");
    mask.className = "turn-mask";
    mask.style.width = pw + "px"; mask.style.height = ph + "px";
    cast = document.createElement("div");
    cast.className = "turn-cast";
    cast.style.width = cast.style.height = S + "px";
    mask.appendChild(cast);
    book.appendChild(mask);
    current = start - (start % (spread ? 2 : 1));
    rest();
  }

  // ---------- 넘김 (S30d: 종이 넘김) ----------
  // 10/23 전 라이브러리(StPageFlip)처럼 모서리가 접히며 넘어간다(2026-10-25 "원래대로 하되 부드럽고 버벅이지 않게").
  // 라이브러리는 프레임마다 쪽 모양을 잘라(clip-path)·그림자를 다시 그려 글 많은 쪽에서 끊겼다 →
  // 쪽마다 가리는 틀(.leaf, overflow hidden)을 접힌 선에 맞춰 돌려 앞면을 자르고, 뒷면(다음 펼침의 쪽 / 한 쪽 화면은 빈 종이)은
  // 접힌 선에 거울처럼 비춰 둔다. 매 프레임 transform·opacity 만 바꾸므로 쪽 글자를 다시 그리지 않는다(합성 단계만).
  // 앞뒤 펼침 쪽은 밑에 깔아 미리 그려 둔다 — 넘김 첫 프레임이 늦지 않게.
  var pw = 0, ph = 0, S = 0;   // 쪽 폭·높이, 가리는 틀 한 변 (쪽 대각선의 두 배 — 어느 각도로 돌아도 반평면을 덮게)
  var leaves = [], backLeaf = null, mask = null, cast = null;
  var ghost = null, ghostOf = -1;   // 한 쪽 화면 뒷면에 비치는 앞면 글자 (S34): 지금 담긴 쪽 번호
  var turn = null;             // 넘기는 중: {dir, A, B, under, ox, s, e, Hc, rest, done, P, raf, to}
  var DUR_SPREAD = 820, DUR_SINGLE = 600;

  function leafOf(page) {
    var leaf = document.createElement("div");
    leaf.className = "leaf";
    var light = document.createElement("div"); light.className = "flap-light";
    var shade = document.createElement("div"); shade.className = "flap-shade";
    leaf.appendChild(page); leaf.appendChild(light); leaf.appendChild(shade);
    leaf.style.width = leaf.style.height = S + "px";
    return { leaf: leaf, page: page, light: light, shade: shade };
  }
  function originOf(i) { return spread && i % 2 === 1 ? pw : 0; }
  // 넘기지 않을 때: 지금 펼침(또는 쪽)이 위, 앞뒤 펼침은 밑에 깔아 둔다(가려져 있고 누를 수도 없음).
  // 값이 같으면 다시 쓰지 않는다 — 쪽이 스무 개 넘어 넘김 끝마다 스타일을 통째로 다시 계산하지 않게
  function setStyle(el, k, v) { if (el.style[k] !== v) el.style[k] = v; }
  function rest() {
    var step = spread ? 2 : 1;
    leaves.forEach(function (o, i) {
      var on = i >= current && i < current + step, near = i >= current - step && i < current + 2 * step;
      setStyle(o.leaf, "transform", "translate(" + originOf(i) + "px, 0px)");
      setStyle(o.page, "transform", "");
      setStyle(o.leaf, "zIndex", on ? "1" : "0");
      setStyle(o.leaf, "visibility", near ? "visible" : "hidden");
      setStyle(o.leaf, "willChange", near ? "transform" : "auto");
      setStyle(o.page, "willChange", near ? "transform" : "auto");
      if (o.leaf.inert !== !on) o.leaf.inert = !on;
      setStyle(o.shade, "opacity", "0"); setStyle(o.light, "opacity", "0");
    });
    if (backLeaf) { backLeaf.leaf.style.visibility = "hidden"; backLeaf.shade.style.opacity = backLeaf.light.style.opacity = 0; }
    if (mask) { mask.style.visibility = "hidden"; cast.style.opacity = 0; }
    if (!spread && ghost) { clearTimeout(ghostTimer); ghostTimer = setTimeout(function () { if (!turn) fillGhost(current); }, 150); }
    showInfo();
  }
  // 한 쪽 화면 뒷면 (S34, 2026-10-30 "넘기는 뒷부분이 빈 화면이라 어색 — 아이패드처럼 살짝 보이게"): 펼침은 뒷면에 다음 쪽이
  // 오지만 한 쪽 화면은 뒤에 올 쪽이 없다 → 신문지처럼 그 쪽 앞면 글자가 뒤집혀 옅게 비친다. 다음 넘김(지금 쪽)은 쉬는 동안 미리 복제해 둔다
  function fillGhost(i) {
    if (!ghost || ghostOf === i || !pages[i]) return;
    var c = pages[i].cloneNode(true);
    c.removeAttribute("data-page");
    Array.prototype.forEach.call(c.querySelectorAll("[id],[data-issue]"), function (n) { n.removeAttribute("id"); n.removeAttribute("data-issue"); });
    c.style.transform = "";
    ghost.textContent = "";
    ghost.appendChild(c);
    ghostOf = i;
  }
  var ghostTimer = 0;
  function canTurn(dir) {
    var step = spread ? 2 : 1;
    return dir > 0 ? current + step < pages.length : current - step >= 0;
  }
  // A = 접히는 쪽, B = 그 뒷면, under = 드러나는 쪽. 좌표는 A 쪽 기준: s = 책등 x, e = 바깥 가장자리 x, Hc = 잡은 모서리 y.
  // rest·done = 모서리(P)의 처음·끝 자리 (한 쪽 화면에서 뒤로는 앞 쪽이 넘어가 있던 자리에서 되돌아온다)
  function beginTurn(dir, Hc) {
    var c = current, L = function (i) { return leaves[i] || null; }, T = { dir: dir, Hc: Hc, raf: 0 };
    if (spread) {
      if (dir > 0) { T.A = L(c + 1); T.B = L(c + 2); T.under = [L(c + 3)]; T.ox = pw; T.s = 0; T.e = pw; }
      else { T.A = L(c); T.B = L(c - 1); T.under = [L(c - 2)]; T.ox = 0; T.s = pw; T.e = 0; }
      T.rest = { x: T.e, y: Hc }; T.done = { x: 2 * T.s - T.e, y: Hc };
    } else {
      T.ox = 0; T.s = 0; T.e = pw; T.B = backLeaf;
      if (dir > 0) { T.A = L(c); T.under = [L(c + 1)]; T.rest = { x: pw, y: Hc }; T.done = { x: -pw, y: Hc }; }
      else { T.A = L(c - 1); T.under = [L(c)]; T.rest = { x: -pw, y: Hc }; T.done = { x: pw, y: Hc }; }
      fillGhost(dir > 0 ? c : c - 1);
    }
    T.under.forEach(function (u) { if (u) { u.leaf.style.visibility = "visible"; u.leaf.style.zIndex = 1; } });
    [T.A, T.B].forEach(function (o, k) {
      o.leaf.style.visibility = "visible"; o.leaf.style.zIndex = 3 + k;
      o.leaf.style.willChange = o.page.style.willChange = "transform";
    });
    mask.style.transform = "translate(" + T.ox + "px,0)"; mask.style.visibility = "visible";   // left 를 바꾸면 레이아웃
    T.P = { x: T.rest.x, y: T.rest.y };
    turn = T;
    draw(T.P);
  }
  // 모서리가 갈 수 있는 자리: 책등 쪽 두 모서리에서 종이 길이를 넘지 않게 (찢어지지 않게)
  function clampP(P, s, Hc) {
    var cx = s, cy = Hc, dx = P.x - cx, dy = P.y - cy, d = Math.hypot(dx, dy);
    if (d > pw) P = { x: cx + dx * pw / d, y: cy + dy * pw / d };
    var r2 = Math.hypot(pw, ph);
    cy = ph - Hc; dx = P.x - cx; dy = P.y - cy; d = Math.hypot(dx, dy);
    if (d > r2) P = { x: cx + dx * r2 / d, y: cy + dy * r2 / d };
    return P;
  }
  // 모서리를 P 로: 접힌 선 = 모서리 자리와 P 의 수직이등분선. 틀은 그 선을 x 축(=0)으로 돌려 책등 쪽만 남긴다
  function draw(P) {
    var T = turn;
    P = clampP(P, T.s, T.Hc);
    T.P = P;
    var dx = P.x - T.e, dy = P.y - T.Hc, d = Math.hypot(dx, dy), ux, uy;
    if (d < 0.5) { ux = T.s > T.e ? 1 : -1; uy = 0; d = 0.5; } else { ux = dx / d; uy = dy / d; }
    var mx = T.e + ux * d / 2, my = T.Hc + uy * d / 2, a = Math.atan2(uy, ux) * 180 / Math.PI;
    var clip = "translate(" + (T.ox + mx) + "px," + my + "px) rotate(" + a + "deg) translate(0," + (-S / 2) + "px)";
    var back = "translate(0," + (S / 2) + "px) rotate(" + (-a) + "deg) translate(" + (-mx) + "px," + (-my) + "px)";
    T.A.leaf.style.transform = clip;
    T.A.page.style.transform = back;   // 틀이 돈 만큼 되돌려 쪽은 제자리
    T.B.leaf.style.transform = clip;
    // 뒷면: 쪽 좌우를 뒤집어(뒷면) A 자리에 놓고, 접힌 선에 비춘다 — 두 번 뒤집으므로 글은 바로 읽힌다
    T.B.page.style.transform = "translate(0," + (S / 2) + "px) scaleX(-1) rotate(" + (-a) + "deg) translate(" + (-mx) + "px," + (-my) + "px) translate(" + pw + "px,0) scaleX(-1)";
    cast.style.transform = "translate(" + mx + "px," + my + "px) rotate(" + a + "deg) translate(" + (-S) + "px," + (-S / 2) + "px)";
    var f = Math.min(1, Math.abs(P.x - T.e) / (2 * pw)), k = Math.sin(Math.PI * f);
    T.B.shade.style.opacity = Math.min(1, k * 1.4);
    T.B.light.style.opacity = k;
    cast.style.opacity = Math.min(1, k * 1.6);
  }
  function progress() { return turn ? Math.abs(turn.P.x - turn.rest.x) / (2 * pw) : 0; }
  function ease(k, both) { return both ? (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2) : 1 - Math.pow(1 - k, 3); }
  // 놓은 뒤: done 이면 끝까지, 아니면 제자리로. lift = 단추로 넘길 때 모서리를 들어 올리는 높이
  function settle(done, lift) {
    var T = turn, from = { x: T.P.x, y: T.P.y }, to = done ? T.done : T.rest, start = 0;
    var dur = Math.max(160, (spread ? DUR_SPREAD : DUR_SINGLE) * Math.abs(to.x - from.x) / (2 * pw));
    T.to = done;
    var tick = function (now) {
      if (turn !== T) return;
      if (!start) start = now;
      var k = Math.min(1, (now - start) / dur), e = ease(k, !!lift);
      draw({ x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e + (lift ? lift * Math.sin(Math.PI * e) : 0) });
      if (k < 1) { T.raf = requestAnimationFrame(tick); return; }
      endTurn(done);
    };
    T.raf = requestAnimationFrame(tick);
  }
  function endTurn(done) {
    var d = turn.dir;
    turn = null;
    if (done) current += d * (spread ? 2 : 1);
    rest();
  }
  function stopTurn() {   // 넘기던 것을 끝으로 바로 (다시 나누기·다음 넘김 전)
    if (!turn) return;
    cancelAnimationFrame(turn.raf);
    endTurn(turn.raf ? turn.to : progress() > 0.5);
  }
  function animateTurn(dir) {
    if (drag && drag.dir) return;   // 끄는 중
    stopTurn();
    if (!canTurn(dir)) return;
    beginTurn(dir, ph);
    settle(true, -ph * 0.12);
  }

  // 끌기: 마우스·손가락 공통. 8px 넘게 가로로 움직여야 넘기기 시작 — 그 전엔 누르기(제목·원문·단추)로 둔다 (S28b: 모서리 제목 누르면 넘김이 겹치던 것)
  // 잡은 높이가 쪽 위쪽 절반이면 위 모서리, 아래쪽이면 아래 모서리가 접힌다
  var drag = null, eatClick = false;
  function dragStart(x, y) {
    if (!anim || mode !== "flip" || (turn && !turn.raf)) return false;
    drag = { x: x, y: y, dir: 0, top: book.getBoundingClientRect().top, hist: [[x, Date.now()]] };
    return true;
  }
  function dragMove(x, y) {
    if (!drag) return false;
    var dx = x - drag.x, dy = y - drag.y;
    if (!drag.dir) {
      if (Math.abs(dy) > 12 && Math.abs(dy) > Math.abs(dx)) { drag = null; return false; }   // 세로 손짓
      if (Math.abs(dx) < 8 || Math.abs(dx) < Math.abs(dy) * 1.2) return false;
      var dir = dx < 0 ? 1 : -1;
      if (!canTurn(dir)) { drag = null; return false; }
      stopTurn();   // 앞 넘김이 아직 움직이는 중이면 끝내고
      if (!canTurn(dir)) { drag = null; return false; }
      drag.dir = dir;
      beginTurn(dir, drag.y - drag.top < ph / 2 ? 0 : ph);
      drag.p0 = { x: turn.rest.x, y: turn.rest.y };
    }
    drag.hist.push([x, Date.now()]);
    if (drag.hist.length > 5) drag.hist.shift();
    var k = spread ? 1.25 : 2;   // 손가락이 화면을 다 가로지르기 전에 모서리가 끝까지 가게
    draw({ x: drag.p0.x + dx * k, y: drag.p0.y + dy * 0.5 });
    return true;
  }
  function dragEnd() {
    var d = drag;
    drag = null;
    if (!d || !d.dir || !turn) return;
    eatClick = true;   // 끌다 놓은 자리의 링크가 눌리지 않게
    setTimeout(function () { eatClick = false; }, 400);
    // 넘기는 쪽으로의 속도 (px/ms): 놓기 전 100ms 동안만 — 끌다 멈추고 놓으면 0
    var now = Date.now(), h = d.hist.filter(function (p) { return now - p[1] <= 100; }), v = 0, f = progress();
    if (h.length) v = (d.hist[d.hist.length - 1][0] - h[0][0]) / Math.max(16, now - h[0][1]) * -d.dir;
    settle(v > -0.3 && (f > 0.5 || (v > 0.3 && f > 0.03)));   // 빠르게 튕기면 짧아도 넘어가고, 거꾸로 튕기면 되돌아감
  }
  book.addEventListener("touchstart", function (e) {
    if (e.touches.length === 1) dragStart(e.touches[0].clientX, e.touches[0].clientY);
    else if (drag) { drag = null; if (turn && !turn.raf) settle(false); }   // 두 손가락 = 넘기지 않음
  }, { passive: true });
  book.addEventListener("touchmove", function (e) {
    if (e.touches.length !== 1) return;
    if (dragMove(e.touches[0].clientX, e.touches[0].clientY) && e.cancelable) e.preventDefault();
  }, { passive: false });
  book.addEventListener("touchend", function () { dragEnd(); });
  book.addEventListener("touchcancel", function () { drag = null; if (turn && !turn.raf) settle(false); });
  book.addEventListener("mousedown", function (e) {
    if (e.button !== 0 || /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
    if (dragStart(e.clientX, e.clientY)) e.preventDefault();   // 글 선택·링크 끌기 대신 넘김 (누르기는 click 으로 그대로)
  });
  window.addEventListener("mousemove", function (e) { if (drag) dragMove(e.clientX, e.clientY); });
  window.addEventListener("mouseup", function () { dragEnd(); });
  window.addEventListener("click", function (e) { if (eatClick) { eatClick = false; e.preventDefault(); e.stopPropagation(); } }, true);

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

  // 한 면 보기 넘김 (S32b): 스크롤은 바로 목표 쪽으로 옮기고, 그 위에 옮기기 전 화면을 복제한 덮개를 두어 왼쪽 가장자리를 축으로 돌린다.
  // 다음 = 옛 화면이 넘어가며 새 쪽이 드러남, 이전 = 옛 화면 위로 앞 쪽이 되넘어와 덮음. transform·opacity 만 움직인다(Web Animations)
  var sheet = null;   // 넘기는 중인 덮개 {el, anim}
  function snapshot() {   // 지금 스크롤 화면에 걸친 쪽들을 같은 자리에 복제
    var box = document.createElement("div"), sr = scroller.getBoundingClientRect();
    box.className = "sheet-face";
    pages.forEach(function (p) {
      var r = p.getBoundingClientRect();
      if (r.bottom <= sr.top || r.top >= sr.bottom) return;
      var c = p.cloneNode(true);
      c.removeAttribute("id");
      c.style.position = "absolute";
      c.style.left = (r.left - sr.left) + "px"; c.style.top = (r.top - sr.top) + "px";
      c.style.transformOrigin = "0 0"; c.style.transform = "scale(" + zoom + ")";
      box.appendChild(c);
    });
    return box;
  }
  function endSheet() {
    if (!sheet) return;
    var s = sheet;
    sheet = null;
    if (s.anim) s.anim.cancel();
    s.el.remove();
  }
  function turnScroll(delta) {
    endSheet();
    var to = Math.max(0, Math.min(current + delta, pages.length - 1));
    if (to === current || zoom > 1.01 || !scroller.animate) { scrollToPage(to); return; }
    var wrap = document.createElement("div"), old = snapshot();
    wrap.className = "sheet";
    wrap.setAttribute("aria-hidden", "true");
    var face = old;
    if (delta < 0) { scrollToPage(to); face = snapshot(); wrap.appendChild(old); }   // 이전: 옛 화면은 깔고 앞 쪽이 덮으며 들어온다
    var shade = document.createElement("div");
    shade.className = "sheet-shade";
    face.appendChild(shade);
    wrap.appendChild(face);
    book.appendChild(wrap);
    if (delta > 0) scrollToPage(to);
    var turned = "perspective(1800px) rotateY(-100deg)", flat = "perspective(1800px) rotateY(0deg)";
    var frames = delta > 0 ? [{ transform: flat }, { transform: turned }] : [{ transform: turned }, { transform: flat }];
    var opt = { duration: 520, easing: "cubic-bezier(.4, .1, .3, 1)", fill: "both" };
    sheet = { el: wrap, anim: face.animate(frames, opt) };
    shade.animate(delta > 0 ? [{ opacity: 0 }, { opacity: 0.45 }] : [{ opacity: 0.45 }, { opacity: 0 }], opt);
    var mine = sheet;
    mine.anim.onfinish = function () { if (sheet === mine) endSheet(); };
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
    if (mode === "scroll") { turnScroll(delta); return; }
    animateTurn(delta > 0 ? 1 : -1);   // 앞·뒤 모두 넘김 애니메이션 (S28a — 예전 라이브러리는 세로에서 뒤로 못 넘김)
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

  // 한 면 보기(확대 안 했을 때)의 손가락 넘기기 → go() 가 넘김 덮개(S32b)로. 펼침 보기의 넘김은 위 끌기(S28a)가 맡는다
  // 손가락 밀기: 오른쪽→왼쪽 = 다음 쪽, 왼쪽→오른쪽 = 이전 쪽 (2026-10-21 "세로에서 넘기기가 잘 안 먹힌다")
  // 가로 이동이 세로 이동보다 뚜렷할 때만 — 세로 스크롤·두 손가락 확대와 겹치지 않게
  var tx = null, ty = 0;
  function swipeOn() { return mode === "scroll" ? zoom <= 1.01 : !anim; }
  book.addEventListener("touchstart", function (e) {
    tx = swipeOn() && e.touches.length === 1 ? e.touches[0].clientX : null;
    if (tx !== null) ty = e.touches[0].clientY;
  }, { passive: true });
  book.addEventListener("touchmove", function (e) { if (e.touches.length > 1) tx = null; }, { passive: true });
  book.addEventListener("touchend", function (e) {
    if (tx === null || !swipeOn()) { tx = null; return; }
    var dx = e.changedTouches[0].clientX - tx, dy = e.changedTouches[0].clientY - ty;
    tx = null;
    if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy) * 1.5) go(dx < 0 ? 1 : -1);
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
    var list = !reader.hidden && body.querySelector(".bt-full") ? Array.prototype.slice.call(body.childNodes) : null;
    if (list) {   // 단신 모두 보기에서 열었으면 목록으로 돌아가기 (S47 리뷰)
      var bb = mk("button", "rv-back", "← 단신 목록");
      bb.type = "button";
      var listLabel = reader.getAttribute("data-list-label") || "단신 모두 보기";
      bb.addEventListener("click", function () { body.innerHTML = ""; reader.querySelector(".reader-panel").style.height = ""; list.forEach(function (n) { body.appendChild(n); }); reader.setAttribute("aria-label", listLabel); swReset(body); });
      node.insertBefore(bb, node.firstChild);
    }
    body.innerHTML = "";
    body.appendChild(node);
    readSeq++;
    reader.setAttribute("aria-label", "기사 자세히");
    showReader();
    addFull(node);
  }
  // 창 열기·닫기 (S29d 점검): 열면 뒤 지면·도구 막대를 inert 로(탭·스크린리더가 가려진 지면으로 새지 않게), 닫으면 누른 자리로 포커스를 돌린다
  var lastFocus = null;
  function showReader() {
    if (reader.hidden) lastFocus = document.activeElement;
    [book, document.getElementById("toolbar")].forEach(function (el) { if (el) el.inert = true; });
    reader.hidden = false;
    reader.querySelector(".reader-panel").style.height = "";   // 새 내용이면 창 높이 고정을 푼다
    reader.querySelector(".reader-panel").scrollTop = 0;
    reader.querySelector("[data-reader-close]").focus();
  }
  function closeReader() {
    if (!reader || reader.hidden) return;
    reader.hidden = true;
    reader.querySelector(".reader-panel").style.height = "";
    readSeq++;
    [book, document.getElementById("toolbar")].forEach(function (el) { if (el) el.inert = false; });
    if (lastFocus && lastFocus.isConnected && lastFocus.focus) lastFocus.focus();
    lastFocus = null;
  }

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
        if (!isJson && r.status >= 500 && left > 0 && (seq == null || seq === readSeq)) return load(left - 1);   // seq 없음 = 공유 요청(S54)
        return r.json();
      });
    };
    return load(1);
  }
  // 전문 받기 (S54 ④): 주소별로 이 탭 메모리에만 — 성공한 결과(FULL)와 받는 중인 요청(INFLIGHT). localStorage·지면 HTML 에 안 남김(D16).
  // 요청·20초 시간 초과·503 한 번 더는 여기서 스스로 — 창을 닫거나 돌아가도 요청은 끝까지 가고 결과가 남는다. 실패는 남기지 않아 다음에 다시 받음
  var FULL = {}, INFLIGHT = {}, TR = {};
  function fullText(url) {
    if (FULL[url]) return Promise.resolve(FULL[url]);
    if (INFLIGHT[url]) return INFLIGHT[url];
    var ctrl = window.AbortController ? new AbortController() : null;
    var p = new Promise(function (res) {
      var timer = setTimeout(function () { if (ctrl) ctrl.abort(); res({ ok: false, timeout: true }); }, 20000);
      relay("/?url=" + encodeURIComponent(url), null, null, ctrl ? ctrl.signal : undefined).then(function (j) { clearTimeout(timer); res(j || { ok: false }); },
        function () { clearTimeout(timer); res({ ok: false, net: true }); });
    }).then(function (j) {
      delete INFLIGHT[url];
      if (j && j.ok && j.paragraphs && j.paragraphs.length) FULL[url] = j;
      return j;
    });
    INFLIGHT[url] = p;
    return p;
  }
  function failWhy(j) {
    return j && j.timeout ? "원문 사이트가 응답하지 않습니다" : j && j.net ? "연결하지 못했습니다"
      : "원문을 가져오지 못했습니다" + (j && j.reason ? " (" + j.reason + ")" : "");
  }
  // 자세히 창 두 장 넘기기 (S55 시안 A): "AI 정리 · 전문" 탭 + 가로로 두 장(scroll-snap). 옆으로 밀거나 탭을 누르면 바뀐다.
  // 전문을 받을 수 있으면 둘째 장에 본문, 못 받는 기사는 "같은 사건 전문"(대체 기사 목록), 둘 다 없으면 한 장 그대로
  var swSeq = 0;
  function swPanes(wrap) { return Array.prototype.slice.call(wrap.querySelectorAll(":scope > .sw-track > .sw-pane")); }
  function swSize(wrap) {   // 두 장 칸 높이 = 지금 장 높이 (긴 전문 때문에 AI 정리 아래가 비지 않게)
    var k = +(wrap.getAttribute("data-k") || 0), p = swPanes(wrap)[k], tr = wrap.querySelector(":scope > .sw-track");
    if (p && tr) tr.style.height = p.offsetHeight + "px";
  }
  function swSelect(wrap, k, scroll, align) {   // scroll: 가로로 그 장까지 ("smooth"·true·false), align: 세로를 탭 줄 바로 아래로
    var tabs = wrap.querySelectorAll(":scope > .sw-tabs > .sw-tab"), panes = swPanes(wrap), tr = wrap.querySelector(":scope > .sw-track");
    wrap.setAttribute("data-k", k);
    Array.prototype.forEach.call(tabs, function (t, i) { t.setAttribute("aria-selected", i === k ? "true" : "false"); t.tabIndex = i === k ? 0 : -1; });
    panes.forEach(function (p, i) {
      p.setAttribute("aria-hidden", i === k ? "false" : "true");   // 안 보이는 장은 화면 읽기·Tab 에서 뺀다 (inert 는 밀기를 막을 수 있어 쓰지 않음)
      Array.prototype.forEach.call(p.querySelectorAll("a, button, summary, input, select, textarea, [tabindex]"), function (el) {   // summary 도 (재리뷰 M3)
        if (i === k) { if (el.hasAttribute("data-swti")) { el.removeAttribute("tabindex"); el.removeAttribute("data-swti"); } }
        else if (!el.hasAttribute("data-swti")) { el.setAttribute("data-swti", ""); el.tabIndex = -1; }
      });
    });
    var box = k && wrap.closest(".reader-panel");
    if (box && !box.style.height) box.style.height = box.offsetHeight + "px";   // 요약 → 전문으로 넘겨도 창 크기는 요약 때 그대로 (안은 창 안에서 스크롤)
    if (tr && scroll !== false) tr.scrollTo({ left: k * tr.clientWidth, behavior: scroll === "smooth" ? "smooth" : "auto" });
    swSize(wrap);
    var panel = align && reader && reader.querySelector(".reader-panel");
    if (panel) {   // 장을 바꾸면 탭 바로 아래부터 (창 안에서의 위치로 — 리뷰 N9)
      var top = wrap.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop;
      if (panel.scrollTop > top) panel.scrollTop = top;
    }
  }
  function swipeWrap(node, label2) {
    var id = "sw" + (++swSeq);
    var wrap = mk("div", "sw"), tabs = mk("div", "sw-tabs"), tr = mk("div", "sw-track");
    tabs.setAttribute("role", "tablist");
    var p1 = mk("div", "sw-pane"), p2 = mk("div", "sw-pane");
    ["AI 정리", label2].forEach(function (label, i) {
      var t = mk("button", "sw-tab", label);
      t.type = "button";
      t.id = id + "-t" + i;
      t.setAttribute("role", "tab");
      t.setAttribute("aria-controls", id + "-p" + i);
      t.addEventListener("click", function () { swSelect(wrap, i, "smooth", true); });
      tabs.appendChild(t);
    });
    tabs.addEventListener("keydown", function (e) {   // 왼쪽·오른쪽 방향키로 탭 옮기기
      if (["ArrowLeft", "ArrowRight", "Home", "End"].indexOf(e.key) < 0) return;
      e.preventDefault();
      e.stopPropagation();
      var k = e.key === "ArrowRight" || e.key === "End" ? 1 : 0;
      swSelect(wrap, k, "smooth", true);
      tabs.children[k].focus();
    });
    [p1, p2].forEach(function (p, i) { p.id = id + "-p" + i; p.setAttribute("role", "tabpanel"); p.setAttribute("aria-labelledby", id + "-t" + i); tr.appendChild(p); });
    node.parentNode.replaceChild(wrap, node);
    p1.appendChild(node);
    wrap.appendChild(tabs);
    wrap.appendChild(tr);
    var timer = null;
    tr.addEventListener("scroll", function () {   // 손으로 밀었을 때: 멈춘 자리의 장으로 탭을 맞춘다
      clearTimeout(timer);
      timer = setTimeout(function () {
        var k = tr.clientWidth ? Math.round(tr.scrollLeft / tr.clientWidth) : 0;
        if (k !== +(wrap.getAttribute("data-k") || 0)) swSelect(wrap, k, false, true);   // 손으로 밀어도 세로를 맞춘다 (리뷰 M2)
      }, 90);
    }, { passive: true });
    swSelect(wrap, 0, false);
    if (window.ResizeObserver) { var ro = new ResizeObserver(function () { swSize(wrap); }); ro.observe(p1); ro.observe(p2); }   // 전문·번역·사진이 늦게 채워져도 높이를 따라감
    return { wrap: wrap, pane: p2 };
  }
  function swReset(root) {   // "← 돌아가기"로 다시 붙이면 첫 장·첫 탭으로 (다시 붙인 칸은 가로 위치가 0 이 되고 scroll 이 안 난다)
    Array.prototype.forEach.call(root.querySelectorAll(".sw"), function (w) { swSelect(w, 0); });
  }
  window.addEventListener("resize", function () {
    if (!reader || reader.hidden) return;
    Array.prototype.forEach.call(reader.querySelectorAll(".sw"), function (w) { swSelect(w, +(w.getAttribute("data-k") || 0)); });   // 가로 위치만 (세로는 그대로 — 리뷰 M3)
  });
  function cleanTitle(t, site) {   // og:title 끝의 " - 한국경제"·" | Reuters" 같은 매체 이름 꼬리 떼기
    t = String(t || "").trim();
    if (!site) return t;
    var m = t.match(/^(.*\S)\s+[-|–—]\s+([^-|–—]{1,30})$/);
    var tail = m ? m[2].trim().toLowerCase() : "", name = String(site).trim().toLowerCase();
    return m && tail && (tail === name || tail.replace(/\s/g, "") === name.replace(/\s/g, "")) ? m[1] : t;   // 꼬리가 매체 이름과 같을 때만 (리뷰 N4)
  }
  // 자세히 창 전문 (S54 시안 C → S55 시안 A 두 장): 뉴스 기사의 메타 줄 첫 "원문" 단추가 읽을 수 있으면 둘째 장에 본문, 못 읽으면 같은 사건 전문 기사 목록
  function addFull(node) {
    if (!RD || !node.matches("article.item")) return;
    var sec = node.getAttribute("data-section");
    if (sec === "china" || sec === "opinion" || sec === "analysis") return;
    var btn = node.querySelector(":scope > .meta .orig-btn");
    if (!btn) return;
    var alt = node.querySelector(":scope > .ft-alt");
    var url = btn.getAttribute("data-read");
    if (alt) alt.remove();
    if (!url) {
      if (!alt) return;
      var w0 = swipeWrap(node, "같은 사건 전문");
      var box0 = mk("section", "ft ft-alt-pane");
      alt.hidden = false;
      alt.insertBefore(mk("p", "ft-why", btn.getAttribute("data-noread") === "addr" ? "원문 주소를 찾지 못했습니다." : "이 매체는 외부에서 본문을 읽지 못하게 막아 두었습니다."), alt.firstChild);
      box0.appendChild(alt);
      w0.pane.appendChild(box0);
      swSelect(w0.wrap, 0, false);   // 넣은 단추도 안 보이는 장이면 Tab 에서 뺀다 (리뷰 B1)
      return;
    }
    var w = swipeWrap(node, "전문");
    var src = btn.getAttribute("data-src") || "";
    var box = mk("section", "ft");
    var h = mk("h4", "ft-title", (node.querySelector(".hl a") || {}).textContent || "");
    box.appendChild(h);
    var meta = mk("p", "ft-meta");
    var href = btn.getAttribute("data-href") || "", lang = btn.getAttribute("data-lang") || "ko";
    var srcEl = mk("span", "ft-src", src);
    meta.appendChild(srcEl);
    meta.appendChild(linkBtn(href, "원래 기사 ↗"));
    box.appendChild(meta);
    if (btn.getAttribute("data-paywall") === "1") box.appendChild(mk("p", "ft-pay", "유료 매체 — 앞부분만 보일 수 있음"));
    var status = mk("p", "rv-status", "전문을 불러오는 중…");
    status.setAttribute("role", "status");
    box.appendChild(status);
    var main = mk("div", "ft-body");
    box.appendChild(main);
    w.pane.appendChild(box);
    swSelect(w.wrap, 0, false);   // 받는 동안의 "원래 기사" 링크도 Tab 에서 빼기 (리뷰 B1)
    fullText(url).then(function (j) {
      if (!j || !j.ok || !j.paragraphs || !j.paragraphs.length) {
        status.textContent = failWhy(j) + ".";
        status.className = "rv-status rv-fail";
        main.appendChild(linkBtn(href, "원래 기사 열기 ↗", true));
        if (alt) { alt.hidden = false; main.appendChild(alt); }   // 받기 실패면 같은 사건 전문 기사도 (리뷰 M6)
        swSelect(w.wrap, +(w.wrap.getAttribute("data-k") || 0), false);
        return;
      }
      if (j.title) { h.textContent = cleanTitle(j.title, j.site || src); h.setAttribute("lang", lang); }
      var when = j.published ? new Date(j.published) : null;
      status.textContent = when && !isNaN(when) ? when.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" }) : "";
      status.hidden = !status.textContent;   // 시각이 없으면 빈 줄 없이
      var imgs = (j.images || []).slice(), ps = [];
      if (imgs.length) main.appendChild(figure(imgs.shift()));
      j.paragraphs.forEach(function (p, i) {
        var n = mk("p", "rv-p", p);   // textContent 로만 (원문 HTML 은 쓰지 않음)
        ps.push(n);
        main.appendChild(n);
        if (imgs.length && i % 4 === 3) main.appendChild(figure(imgs.shift()));
      });
      var foot = mk("p", "rv-foot", "원문을 그 자리에서 받아 사진과 글만 다시 보여 준 화면입니다(저장하지 않음). 저작권은 " + (j.site || src || "해당 매체") + "에 있습니다. ");
      foot.appendChild(linkBtn(j.url || href, "원래 기사 열기 ↗"));
      main.appendChild(foot);
      if (lang !== "ko") translateButton(box, main, ps, lang, url);
      var k = +(w.wrap.getAttribute("data-k") || 0);
      swSelect(w.wrap, k, false);   // 새로 넣은 단추도 안 보이는 장이면 Tab 에서 빼고, 높이 다시
      Array.prototype.forEach.call(main.querySelectorAll("img"), function (im) { im.addEventListener("load", function () { swSize(w.wrap); }); });
    });
  }
  // 전문 칸 번역은 단추를 눌렀을 때만 (무료 할당량 — 제목을 누를 때마다 자동 번역하지 않는다). 결과는 주소별로 TR 에
  function translateButton(box, before, nodes, lang, url) {
    var bar = mk("div", "rv-lang");
    var go = mk("button", "rv-tab", "한국어로 번역");
    go.type = "button";
    bar.appendChild(go);
    box.insertBefore(bar, before);
    var texts = nodes.map(function (n) { return n.textContent; });
    var key = url + "|p";
    var show = function (ko) {
      nodes.forEach(function (n, i) { n.setAttribute("data-orig", texts[i]); n.setAttribute("data-ko", ko[i] || texts[i]); n.textContent = ko[i] || texts[i]; });
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
    };
    go.addEventListener("click", function () {
      if (TR[key]) { show(TR[key]); return; }
      go.disabled = true;
      go.textContent = "한국어로 옮기는 중…";
      relay("/translate", { body: JSON.stringify({ lang: lang, texts: texts }) }, null).then(function (j) {
        if (!j || !j.ok || !j.texts || j.texts.length !== texts.length) { go.disabled = false; go.textContent = "번역하지 못했습니다 — 다시"; return; }
        TR[key] = j.texts;
        show(j.texts);
      }, function () { go.disabled = false; go.textContent = "번역하지 못했습니다 — 다시"; });
    });
  }
  // 번역: 문단 요소들(원문 글)을 한국어로 바꿔 보이고, 한국어/원문 전환 단추를 단다
  function translateInto(view, nodes, lang, seq, key) {
    if (!RD || !lang || lang === "ko" || !nodes.length) return;
    var bar = mk("div", "rv-lang");
    var note = mk("span", "rv-lang-note", "한국어로 옮기는 중…");
    bar.appendChild(note);
    view.insertBefore(bar, view.querySelector(".rv-body"));
    var texts = nodes.map(function (n) { return n.textContent; });
    var got = key && TR[key] && TR[key].length === texts.length ? Promise.resolve({ ok: true, texts: TR[key] })   // 같은 주소는 이 탭에서 한 번만 번역 (S54)
      : relay("/translate", { body: JSON.stringify({ lang: lang, texts: texts }) }, seq);
    got.then(function (j) {
      if (j && j.ok && j.texts && j.texts.length === texts.length && key) TR[key] = j.texts;
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
    var art = el.closest("article.item, article.fz-art");   // 1면 메인 기사(S26)도
    var isBtn = el.tagName !== "A" && !el.hasAttribute("data-title");   // 메타 줄 "원문" 단추면 그 기사의 (원)제목·리드를 쓴다 — 대체 기사 단추(S54)는 제 제목
    var titleText = el.getAttribute("data-title") || (isBtn && art ? ((art.querySelector(".orig") || art.querySelector(".hl a") || el).textContent) : el.textContent);
    var leadEl = isBtn && art ? art.querySelector(".lead") : null;
    var view = mk("article", "readview");
    if (back) {
      var bb = mk("button", "rv-back", "← 돌아가기");
      bb.type = "button";
      bb.addEventListener("click", function () { readSeq++; body.innerHTML = ""; back.forEach(function (n) { body.appendChild(n); }); swReset(body); });
      view.appendChild(bb);
    }
    var top = mk("div", "rv-top");
    top.appendChild(mk("span", "rv-src", srcName));
    top.appendChild(linkBtn(href, "링크 ↗"));
    view.appendChild(top);
    var h = mk("h2", "rv-title", titleText.trim());
    view.appendChild(h);
    var status = mk("p", "rv-status", url && RD ? "원문을 불러오는 중…" : "");
    status.setAttribute("role", "status");   // 불러오는 중·실패 안내를 스크린리더가 읽게 (S29d 점검)
    view.appendChild(status);
    var main = mk("div", "rv-body");
    view.appendChild(main);
    body.innerHTML = "";
    body.appendChild(view);
    reader.setAttribute("aria-label", "원문 보기");
    showReader();
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
      var alt = art && art.querySelector(":scope > .ft-alt");   // 같은 사건 전문 기사 (S54 ④)
      if (alt && !url) { var ac = alt.cloneNode(true); ac.hidden = false; var why = ac.querySelector(".ft-why"); if (why) why.remove(); main.appendChild(ac); }
      translateInto(view, nodes, lang, seq, (url || href) + "|feed|" + nodes.map(function (n) { return n.textContent; }).join("").length);
    };
    if (!url || !RD) {
      fallback(RD && url === "" ? (el.getAttribute("data-noread") === "addr" ? "원문 주소를 찾지 못했습니다. 피드에 실린 내용만 보여 드립니다."
                                   : "이 매체는 외부에서 본문을 읽지 못하게 막아 두었습니다(유료 구독·봇 차단). 피드에 실린 내용만 보여 드립니다.")
                                 : "본문을 불러올 수 없어 피드에 실린 내용만 보여 드립니다.");
      return;
    }
    fullText(url).then(function (j) {   // 자세히 창 전문과 같은 요청·결과를 같이 쓴다 (S54)
      if (seq !== readSeq) return;
      if (!j || !j.ok || !j.paragraphs || !j.paragraphs.length) {
        fallback(failWhy(j) + ". 피드에 실린 내용만 보여 드립니다.");
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
      translateInto(view, [h].concat(ps), lang, seq, url + "|tp");
    });
  }

  // ---------- 경제 해설 창 (S31c·d, 14차 요청) ----------
  // 경제 분야 기사 메타 줄의 "경제 해설" → 단추 옆 template(발행 때 AI 가 쓴 이론으로 보면·실제로는·상세 분석·지켜볼 지표)을 창에.
  // 자세히 창에서 열었으면 "돌아가기". 맨 아래 작은 "이런 해설은 이제 필요 없어요" → 그 개념을 아는 개념으로(feedback.js 가 저장·서버로)
  function openEcon(btn) {
    var tpl = btn.parentNode && btn.parentNode.querySelector("template.econ-src");
    if (!reader || !tpl) return;
    var body = reader.querySelector(".reader-body");
    var back = reader.hidden ? null : Array.prototype.slice.call(body.childNodes);
    var view = tpl.content.firstElementChild.cloneNode(true);
    if (back) {
      var bb = mk("button", "rv-back", "← 돌아가기");
      bb.type = "button";
      bb.addEventListener("click", function () { body.innerHTML = ""; back.forEach(function (n) { body.appendChild(n); }); reader.setAttribute("aria-label", "기사 자세히"); });
      view.insertBefore(bb, view.firstChild);
    }
    body.innerHTML = "";
    body.appendChild(view);
    readSeq++;
    reader.setAttribute("aria-label", "경제 해설");
    econSkip(view);
    showReader();
  }
  function econConcepts(view) {
    return Array.prototype.map.call(view.querySelectorAll(".ev-concepts .concept"), function (c) { return c.textContent.trim(); });
  }
  function econSkip(view) {
    var z = view.querySelector(".ev-skip"), fb = window.NEWS_FB, cs = econConcepts(view);
    if (!z) return;
    z.innerHTML = "";
    if (!fb || !fb.knows || !cs.length) return;
    if (!cs.every(fb.knows)) {
      var b = mk("button", "ev-skip-btn", "이런 해설은 이제 필요 없어요");
      b.type = "button";
      z.appendChild(b);
      return;
    }
    var done = mk("span", "ev-done", "다음 호부터 " + cs.map(function (c) { return "‘" + c + "’"; }).join(", ") +
      " 설명은 빼고, 새로 설명할 게 없는 기사는 해설을 붙이지 않습니다. ");
    var u = mk("button", "ev-undo", "되돌리기");
    u.type = "button";
    done.appendChild(u);
    z.appendChild(done);
  }

  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    var mod = e.ctrlKey || e.metaKey || e.shiftKey || e.button !== 0;
    var ec = t.closest("[data-econ]");                         // "경제 해설" → 해설 창 (S31c)
    if (ec) { e.preventDefault(); openEcon(ec); return; }
    var ev = t.closest(".econ-view");
    if (ev && window.NEWS_FB && t.closest(".ev-skip-btn")) { window.NEWS_FB.addKnown(econConcepts(ev)); econSkip(ev); ev.querySelector(".ev-undo").focus(); return; }
    if (ev && window.NEWS_FB && t.closest(".ev-undo")) { window.NEWS_FB.removeKnown(econConcepts(ev)); econSkip(ev); ev.querySelector(".ev-skip-btn").focus(); return; }
    var bt = t.closest("[data-bt]");                            // 단신 분야 탭 (S47)
    if (bt) { selectBriefTab(bt, false); return; }
    var ba = t.closest("[data-bt-all]");                        // 탭별 전체 보기 → 창 (S48)
    if (ba) { if (!ba.disabled) openBriefAll(ba.getAttribute("data-bt-all")); return; }
    var d = t.closest("a[data-detail]");                      // 기사 제목 → AI 정리(자세히 창)
    if (d && !mod) { e.preventDefault(); var ai = d.closest("[data-issue]"); if (ai) openReader(ai.getAttribute("data-issue")); return; }
    var op = t.closest("a[data-open]");                        // 큐레이션 판 "함께 볼 기사" 목록 제목 → 그 기사 창 (S50)
    if (op && !mod) { e.preventDefault(); openReader(op.getAttribute("data-open")); return; }
    var o = t.closest("[data-art]");                           // "원문"·작은 제목 → 원문 창
    if (o && !mod) { e.preventDefault(); openArticle(o); return; }
    var m = t.closest("[data-more]");
    if (m) { var art = m.closest("[data-issue]"); if (art) openReader(art.getAttribute("data-issue")); return; }
    if (t.closest("[data-reader-close]")) closeReader();
  });
  // 창 바깥(어두운 부분)을 누르면 닫힘 (S28c, 2026-10-23 "지면 부분 누르면 잘 안 먹힌다"): document 로 올라온 click 으로 받던 것은
  // iOS Safari 가 누를 수 없는 div 의 click 을 document 까지 보내지 않아 놓쳤다 → 창에 직접. 바깥에서 누르고 바깥에서 뗀 것만
  // (창 안 글을 끌다 바깥에서 놓으면 click 대상이 바깥이 되어 닫히던 것도 막음)
  if (reader) {
    var downOut = false;
    ["pointerdown", "mousedown", "touchstart"].forEach(function (ev) {
      reader.addEventListener(ev, function (e) { downOut = e.target === reader; }, { passive: true });
    });
    reader.addEventListener("click", function (e) { if (e.target === reader && downOut) closeReader(); downOut = false; });
  }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && reader && !reader.hidden) closeReader(); }, true);

  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register((window.EDITION && window.EDITION.base || "") + "sw.js").catch(function () { /* 오프라인 캐시는 선택 기능 */ });
  }

  function goTo(i) {
    if (mode === "scroll") { scrollToPage(i); return; }
    stopTurn();
    i = Math.max(0, Math.min(i, pages.length - 1));
    current = i - (i % (spread ? 2 : 1));
    rest();
  }

  window.NEWS = { rebuild: function () { build(visibleIssue()); }, go: go, goTo: goTo, openReader: openReader, openArticle: openArticle, setView: setView, setZoom: function (z) { applyZoom(z, null); }, fullscreen: toggleFullscreen, state: function () { return { mode: mode, zoom: zoom, current: current, pages: pages.length, spread: spread, flip: anim, turning: !!turn, overflow: overflowPages.slice(), clipped: clipped, demoted: demotedCount, briefs: briefCount, briefIds: briefAll.map(function (el) { return el.getAttribute("data-issue"); }), dropped: dropped, emptySummary: emptySummary }; } };
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
