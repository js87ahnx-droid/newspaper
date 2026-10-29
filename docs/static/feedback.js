/* 피드백·관심 학습 — 기기에서 바로 지면에 반영하고, 서버 편집에는 주마다 합친다 (지시서 6-2, 6-3 / S30).
 *
 * - 관심 학습값 = 분야마다 절대 가중치(0~3)와 챙겨 볼 키워드. localStorage "news.prefs2" 에 {v, weights, keywords, updated}
 *   · "더 보기 / 덜 보기" 는 그 분야 값을 ±0.25 (같은 단추를 다시 누르면 취소, S24b)
 *   · 설정 창(⚙)에서 분야마다 가로 슬라이더, 키워드 넣기·빼기, "기본값으로"(interests.yaml 원래 값)
 *   · 예전 기기 값(news.prefs 의 delta)은 처음 열 때 절대값으로 옮긴다
 * - 서버 반영(S30a·b): 바꾸면 1.5초 모아 중계 서버(Worker)의 /prefs 로 보낸다. 열 때 서버 값이 더 새것이면(다른 기기) 그것을 쓴다.
 *   발행이 주(ISO)마다 한 번 받아 interests.yaml 위에 덮어 편집한다 — 내보내기 없음
 * - 지면 다시 배치: 관심도를 서버와 같은 식으로 다시 계산해
 *   · 섹션 안 순서를 다시 정렬 (1면 톱은 그대로)
 *   · 가중치 0.1 이하 분야의 기사는 단신으로 내린다
 *   · 서버 값보다 0.5 이상 높인 분야의 단신은 관심면으로 올린다 — 관심 상한(서버와 같은 50%) 안에서만
 *   · 1면 톱·다양성·연속 보장 기사는 내리지 않는다 (다양성 규칙이 항상 우선, 6-3)
 *   처음 지면(#flow)을 복사해 두고, 값이 바뀌면 거기서 새로 배치한다
 * - 주간 설문은 저절로 뜨지 않는다 (S30c, 사용자 요청) — 설정 창의 "설문" 단추로만
 * - 아는 경제 개념(known, S31d): 경제 해설 창의 "이런 해설은 이제 필요 없어요" → 같은 값에 함께 저장·서버로.
 *   발행이 매일 받아 그 개념의 기초 설명을 빼고, 새로 설명할 게 없는 기사는 해설을 붙이지 않는다. 설정 창에서 뺄 수 있다
 */
(function () {
  "use strict";
  var E = window.EDITION || {};
  var flow = document.getElementById("flow");
  var STEP = 0.25, SURVEY_STEP = 0.5, MAX_W = 3, PUSH_WAIT = 1500;
  var RD = E.reader && E.reader.url && E.reader.key ? E.reader : null;
  var TOPIC_IDS = Object.keys(E.topics || E.topicWeights || {});

  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 저장 불가 환경 */ } }
  };
  function clampW(v) { return Math.max(0, Math.min(MAX_W, Math.round(v * 100) / 100)); }
  function serverW(t) { return (E.topicWeights || {})[t] || 0; }

  // 저장된 값 (없으면 예전 delta 를 옮겨서)
  function prefs() {
    var p = store.get("news.prefs2", null);
    if (!p || typeof p !== "object" || p.v !== 1) {
      p = { v: 1, weights: {}, keywords: null, updated: null };
      var old = store.get("news.prefs", null);
      if (old && typeof old === "object") {
        Object.keys(old.delta || {}).forEach(function (t) { p.weights[t] = clampW(serverW(t) + old.delta[t]); });
        if ((old.keywords || []).length) p.keywords = (E.keywords || []).concat(old.keywords.filter(function (k) { return (E.keywords || []).indexOf(k) < 0; }));
        if (Object.keys(p.weights).length || p.keywords) p.updated = new Date().toISOString();
      }
    }
    p.weights = p.weights || {};
    p.known = Array.isArray(p.known) ? p.known : [];
    return p;
  }
  function weightOf(p, topic) { return clampW(topic in p.weights ? p.weights[topic] : serverW(topic)); }
  function keywordList(p) { return p.keywords || E.keywords || []; }
  function fullWeights(p) { var w = {}; TOPIC_IDS.forEach(function (t) { w[t] = weightOf(p, t); }); return w; }

  function keywordHit(p, text) {
    var low = text.toLowerCase();
    return keywordList(p).some(function (k) { return k && low.indexOf(String(k).toLowerCase()) >= 0; });
  }

  function rescore(art, p) {
    var w = E.weights || { attention: 0.35, importance: 0.3, continuity: 0.1, interest: 0.25, headline: 0 };
    var topic = art.getAttribute("data-topic");
    var title = (art.querySelector(".hl") || art).textContent;
    var inte = Math.min((weightOf(p, topic) + (keywordHit(p, title) ? (E.keywordBoost || 0) : 0)) / (E.maxInterest || 1), 1);
    var a = +art.getAttribute("data-a") || 0, i = +art.getAttribute("data-i") || 0, c = +art.getAttribute("data-c") || 0;
    var h = +art.getAttribute("data-h") || 0, wh = w.headline || 0;   // 매체 머리기사 (score.py 와 같은 식)
    var sum = w.attention + w.importance + w.continuity + w.interest + wh;
    return (w.attention * a + w.importance * i + w.continuity * c + w.interest * inte + wh * h) / sum;
  }

  function sectionEl(id) {
    var s = flow.querySelector('section[data-section="' + id + '"]');
    if (s || id !== "interest") return s;
    // 관심면이 없던 날이면 단신 앞에 새로 만든다
    s = document.createElement("section");
    s.className = "sec sec-interest";
    s.setAttribute("data-section", "interest");
    s.setAttribute("data-title", (E.sectionTitles || {}).interest || "관심");
    var briefs = flow.querySelector('section[data-section="briefs"]');
    flow.insertBefore(s, briefs || null);
    return s;
  }

  function asBrief(art, toBrief) {
    art.classList.toggle("brief", toBrief);
    var lead = art.querySelector(".lead"), photo = art.querySelector(".photo"), why = art.querySelector(".why");
    [lead, photo, why].forEach(function (el) { if (el) el.hidden = toBrief; });
  }

  // ---------- 다시 배치 ----------
  var pristine = flow ? flow.cloneNode(true) : null;   // 서버가 편집한 그대로
  function apply() {
    var p = prefs();
    var moved = { demoted: 0, promoted: 0 };
    var arts = Array.prototype.slice.call(flow.querySelectorAll("section.sec > article.item[data-a]"));
    arts.forEach(function (a) { a.setAttribute("data-final2", rescore(a, p).toFixed(4)); });

    var briefs = sectionEl("briefs");
    // 내리기: 가중치를 거의 0 으로 둔 분야의 보장 안 된 기사
    ["politics", "economy", "international", "society", "interest"].forEach(function (id) {
      var sec = sectionEl(id);
      if (!sec || !briefs) return;
      Array.prototype.slice.call(sec.querySelectorAll("article.item")).forEach(function (a) {
        if (a.getAttribute("data-guaranteed") === "1") return;
        if (weightOf(p, a.getAttribute("data-topic")) <= 0.1) {
          briefs.appendChild(a); asBrief(a, true); a.setAttribute("data-moved", "down"); moved.demoted++;
        }
      });
    });
    // 올리기: 서버 값보다 많이 올린 분야의 단신 — 관심 상한 안에서
    var room = Math.max(0, (E.interestCap || 0) - (E.interestCounted || 0));
    var cap = (E.sectionCaps || {}).interest || 6;
    if (briefs && room > 0) {
      var cands = Array.prototype.slice.call(briefs.querySelectorAll("article.item"))
        .filter(function (a) {
          var t = a.getAttribute("data-topic");
          return a.getAttribute("data-guaranteed") !== "1" && a.getAttribute("data-moved") !== "down" &&
                 weightOf(p, t) >= serverW(t) + 0.5;
        })
        .sort(function (x, y) { return +y.getAttribute("data-final2") - +x.getAttribute("data-final2"); });
      var interest = null;
      cands.forEach(function (a) {
        if (moved.promoted >= room) return;
        interest = interest || sectionEl("interest");
        var inSec = Array.prototype.slice.call(interest.querySelectorAll("article.item"));
        if (inSec.length >= cap) {
          // 관심면이 차 있으면 다시 계산한 점수가 더 낮은 보장 안 된 기사와 자리를 바꾼다
          var weakest = inSec.filter(function (x) { return x.getAttribute("data-guaranteed") !== "1" && x.getAttribute("data-moved") !== "up"; })
            .sort(function (x, y) { return +x.getAttribute("data-final2") - +y.getAttribute("data-final2"); })[0];
          if (!weakest || +weakest.getAttribute("data-final2") >= +a.getAttribute("data-final2")) return;
          briefs.appendChild(weakest); asBrief(weakest, true); weakest.setAttribute("data-moved", "down"); moved.demoted++;
        }
        interest.appendChild(a); asBrief(a, false); a.setAttribute("data-moved", "up"); moved.promoted++;
      });
    }
    // 섹션 안 순서: 다시 계산한 점수 순 (1면 톱은 맨 앞 고정)
    Array.prototype.forEach.call(flow.querySelectorAll("section.sec"), function (sec) {
      var items = Array.prototype.slice.call(sec.querySelectorAll(":scope > article.item[data-a]"));
      if (!items.length) return;
      var top = items.filter(function (a) { return a.getAttribute("data-top") === "1"; });
      var rest = items.filter(function (a) { return a.getAttribute("data-top") !== "1"; })
        .sort(function (x, y) { return +y.getAttribute("data-final2") - +x.getAttribute("data-final2"); });
      top.concat(rest).forEach(function (a) { sec.appendChild(a); });
    });
    var empty = flow.querySelector('section[data-section="interest"]');
    if (empty && !empty.querySelector("article")) empty.remove();
    window.NEWS_FB_LAST = moved;
    return moved;
  }
  // 값이 바뀐 뒤: 서버가 편집한 지면에서 새로 배치하고 쪽을 다시 나눈다
  function reapply() {
    if (!pristine) return;
    var fresh = pristine.cloneNode(true);
    while (flow.firstChild) flow.removeChild(flow.firstChild);
    while (fresh.firstChild) flow.appendChild(fresh.firstChild);
    apply();
    markPressed();
    if (window.NEWS) window.NEWS.rebuild();
  }

  // ---------- 저장·서버로 보내기 (S30c) ----------
  var pushTimer = 0, syncState = store.get("news.prefsPending", false) ? "pending" : "idle";
  function save(p, quiet) {
    p.updated = new Date().toISOString();
    store.set("news.prefs2", p);
    if (!quiet) schedulePush();
  }
  function schedulePush() {
    if (!RD) return;
    store.set("news.prefsPending", true);
    syncState = "pending"; showSync();
    clearTimeout(pushTimer);
    pushTimer = setTimeout(push, PUSH_WAIT);
  }
  function push() {
    var p = prefs();
    if (!RD || !p.updated) return;
    var body = JSON.stringify({ v: 1, weights: fullWeights(p), keywords: keywordList(p).slice(0, 30), known: p.known.slice(-100), updated: p.updated });
    fetch(RD.url + "/prefs", { method: "POST", headers: { "X-Reader-Key": RD.key, "Content-Type": "application/json" }, body: body,
      cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" })
      .then(function (r) { if (!r.ok) throw new Error("http " + r.status); store.set("news.prefsPending", false); syncState = "sent"; showSync(); })
      .catch(function () { syncState = "failed"; showSync(); });   // 다음에 열 때 다시 보낸다
  }
  // 열 때: 서버 값이 더 새것이면(다른 기기에서 바꿈) 받아 쓰고, 이 기기 값이 더 새것이거나 못 보낸 게 있으면 보낸다
  function pull() {
    if (!RD) return;
    fetch(RD.url + "/prefs", { headers: { "X-Reader-Key": RD.key }, cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        var s = j && j.ok && j.prefs, p = prefs();
        if (s && s.v === 1 && s.updated && (!p.updated || s.updated > p.updated)) {
          store.set("news.prefs2", { v: 1, weights: s.weights || {}, keywords: s.keywords || null, known: s.known || [], updated: s.updated });
          store.set("news.prefsPending", false);
          syncState = "sent";
          reapply();
          refreshSettings();
        } else if (p.updated && (!s || !s.updated || p.updated > s.updated || store.get("news.prefsPending", false))) {
          push();
        }
      })
      .catch(function () { /* 서버를 못 보면 이 기기 값으로 */ });
  }

  // ---------- 아는 경제 개념 (S31d) ----------
  function knows(c) { return prefs().known.indexOf(c) >= 0; }
  function addKnown(list) {
    var p = prefs();
    list.forEach(function (c) { c = String(c).trim().slice(0, 40); if (c && p.known.indexOf(c) < 0) p.known.push(c); });
    p.known = p.known.slice(-100);
    save(p); refreshSettings();
  }
  function removeKnown(list) {
    var p = prefs();
    p.known = p.known.filter(function (c) { return list.indexOf(c) < 0; });
    save(p); refreshSettings();
  }

  // ---------- 누른 표시 ----------
  function pressedMap() {
    var m = store.get("news.pressed", {}) || {};
    return m[E.edition] || {};
  }
  function markPressed() {
    var m = pressedMap();
    Object.keys(m).forEach(function (issue) {
      flow.querySelectorAll('[data-issue="' + issue + '"] [data-fb="' + m[issue] + '"]').forEach(function (b) { b.classList.add("pressed"); });
    });
  }

  function toast(msg) {
    var t = document.getElementById("toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; t.setAttribute("role", "status"); document.body.appendChild(t); }
    t.textContent = msg;
    t.className = "show";
    clearTimeout(toast.timer);
    toast.timer = setTimeout(function () { t.className = ""; }, 2200);
  }

  document.addEventListener("news:feedback", function (e) {
    var d = e.detail, p = prefs();
    var label = (E.topics || {})[d.topic] || d.topic;
    var all = store.get("news.pressed", {}) || {};
    var keep = {};
    Object.keys(all).sort().slice(-2).forEach(function (k) { keep[k] = all[k]; });  // 최근 두 호만 보관
    keep[E.edition] = keep[E.edition] || {};
    var before = keep[E.edition][d.issue];
    var undo = before === d.kind;   // 같은 단추를 다시 누르면 취소 (S24b)
    // 앞서 누른 것은 되돌리고(반대 단추로 바꿀 때도), 취소가 아니면 새로 누른 것을 더한다
    var change = (before === "more" ? -STEP : before === "less" ? STEP : 0) + (undo ? 0 : (d.kind === "more" ? STEP : -STEP));
    p.weights[d.topic] = clampW(weightOf(p, d.topic) + change);
    save(p);
    var log = store.get("news.fbLog", []) || [];
    log.push({ t: new Date().toISOString(), edition: E.edition, issue: d.issue, topic: d.topic, kind: undo ? "undo" : d.kind });
    store.set("news.fbLog", log.slice(-500));
    if (undo) delete keep[E.edition][d.issue]; else keep[E.edition][d.issue] = d.kind;
    store.set("news.pressed", keep);
    // 같은 기사의 단추 표시: 누른 것만 (취소면 모두 지움)
    document.querySelectorAll('[data-issue="' + d.issue + '"] [data-fb]').forEach(function (b) {
      b.classList.toggle("pressed", !undo && b.getAttribute("data-fb") === d.kind);
    });
    refreshSettings();
    toast(undo ? label + " 분야 " + (d.kind === "more" ? "더" : "덜") + " 보기를 취소했습니다"
      : label + " 분야를 " + (d.kind === "more" ? "더" : "덜") + " 보도록 기억했습니다 · 다음에 열 때 반영");
  });

  // ---------- 주간 설문 (설정 창에서만) ----------
  function isoWeek(d) {
    var t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    var day = t.getUTCDay() || 7;
    t.setUTCDate(t.getUTCDate() + 4 - day);
    var y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
    return t.getUTCFullYear() + "-W" + String(Math.ceil(((t - y0) / 86400000 + 1) / 7)).padStart(2, "0");
  }
  // "2026-W44" → 그 주 월요일
  function weekMonday(w) {
    var m = /^(\d{4})-W(\d{2})$/.exec(w || "");
    if (!m) return null;
    var jan4 = new Date(Date.UTC(+m[1], 0, 4)), day = jan4.getUTCDay() || 7;
    return new Date(Date.UTC(+m[1], 0, 4 - day + 1 + (+m[2] - 1) * 7));
  }
  function mdDay(d) { return (d.getUTCMonth() + 1) + "/" + d.getUTCDate() + "(" + "일월화수목금토"[d.getUTCDay()] + ")"; }

  function topicChips(name) {
    return TOPIC_IDS.map(function (t) {
      return '<label class="chip"><input type="checkbox" name="' + name + '" value="' + t + '"><span>' + (E.topics || {})[t] + "</span></label>";
    }).join("");
  }

  function showSurvey() {
    if (document.getElementById("survey")) return;
    var box = document.createElement("div");
    box.id = "survey";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "이번 주 설문");
    box.innerHTML =
      '<form class="card"><h2>이번 주 지면, 어땠나요?</h2>' +
      '<fieldset><legend>1. 이번 주 덜 보고 싶던 분야는?</legend>' + topicChips("less") + "</fieldset>" +
      '<fieldset><legend>2. 더 보고 싶은 분야는?</legend>' + topicChips("more") + "</fieldset>" +
      '<fieldset><legend>3. 새로 보고 싶은 키워드는? (쉼표로 구분)</legend><input type="text" name="kw" placeholder="예: 원전, 배터리"></fieldset>' +
      '<div class="actions"><button type="button" data-s="later">닫기</button><button type="submit" data-s="save">저장</button></div>' +
      '<p class="hint">관심 밖이라도 중요한 뉴스는 계속 실립니다.</p></form>';
    document.body.appendChild(box);
    var form = box.querySelector("form");
    function close() { store.set("news.survey", isoWeek(new Date())); box.remove(); }
    box.querySelector('[data-s="later"]').addEventListener("click", close);
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var p = prefs();
      form.querySelectorAll('input[name="less"]:checked').forEach(function (i) { p.weights[i.value] = clampW(weightOf(p, i.value) - SURVEY_STEP); });
      form.querySelectorAll('input[name="more"]:checked').forEach(function (i) { p.weights[i.value] = clampW(weightOf(p, i.value) + SURVEY_STEP); });
      var kws = keywordList(p).slice();
      form.kw.value.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean).forEach(function (k) {
        if (kws.indexOf(k) < 0) kws.push(k);
      });
      p.keywords = kws;
      save(p);
      close();
      reapply();
      toast("설문을 반영했습니다");
    });
  }

  // ---------- 설정 창: 분야 슬라이더·키워드·기본값으로 (S30c) ----------
  function word(v) { return v < 0.13 ? "안 봄" : v < 0.6 ? "덜" : v < 1.3 ? "보통" : v < 2.1 ? "더" : "많이"; }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function syncText() {
    var last = weekMonday(E.learnedWeek), now = new Date(), next = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
    next.setUTCDate(next.getUTCDate() + ((8 - (next.getUTCDay() || 7)) % 7 || 7));
    var head = (last ? "마지막 서버 반영 <b>" + mdDay(last) + " 주</b> · " : "") + "다음 반영 <b>" + mdDay(next) + " 호</b>. ";
    var tail = !RD ? "서버 주소가 없어 이 기기에만 저장됩니다."
      : syncState === "pending" ? "바꾼 값을 서버로 보내는 중…"
      : syncState === "failed" ? "서버로 보내지 못했습니다 — 다음에 열 때 다시 보냅니다."
      : syncState === "sent" ? "바꾼 값을 서버에 저장했습니다."
      : "바꾼 값은 이 기기 지면에 바로, 서버 편집에는 다음 반영 때 들어갑니다.";
    return head + tail;
  }
  function showSync() {
    var el = document.querySelector("#settings .sync");
    if (el) el.innerHTML = syncText();
  }
  function rowsHTML(p) {
    return TOPIC_IDS.map(function (t) {
      var v = weightOf(p, t);
      return '<div class="wrow"><label for="w-' + t + '">' + esc((E.topics || {})[t] || t) + '</label>' +
        '<input type="range" id="w-' + t + '" data-topic="' + t + '" min="0" max="' + MAX_W + '" step="0.05" value="' + v + '">' +
        '<output for="w-' + t + '"><b>' + word(v) + "</b> " + v.toFixed(2) + "</output></div>";
    }).join("");
  }
  function chipsHTML(p) {
    return keywordList(p).map(function (k, i) {
      return '<span class="kwchip">' + esc(k) + '<button type="button" data-kw="' + i + '" aria-label="' + esc(k) + ' 빼기">×</button></span>';
    }).join("") || '<span class="hint">없음</span>';
  }
  function knownHTML(p) {
    return p.known.map(function (k, i) {
      return '<span class="kwchip">' + esc(k) + '<button type="button" data-known="' + i + '" aria-label="' + esc(k) + ' 다시 해설 받기">×</button></span>';
    }).join("") || '<span class="hint">없음 — 경제 해설 창의 "이런 해설은 이제 필요 없어요"로 더합니다</span>';
  }
  function refreshSettings() {
    var box = document.getElementById("settings");
    if (!box) return;
    var p = prefs();
    box.querySelector(".wrows").innerHTML = rowsHTML(p);
    box.querySelector(".kwchips").innerHTML = chipsHTML(p);
    box.querySelector(".knownchips").innerHTML = knownHTML(p);
    showSync();
  }

  var layoutTimer = 0;
  function laterReapply() { clearTimeout(layoutTimer); layoutTimer = setTimeout(reapply, 400); }

  function showSettings() {
    var old = document.getElementById("settings");
    if (old) { old.remove(); return; }
    var p = prefs();
    var box = document.createElement("div");
    box.id = "settings";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "관심 학습");
    box.innerHTML = '<div class="card"><div class="shead"><h2>관심 학습</h2><span class="hint">많이 볼수록 오른쪽</span></div>' +
      '<div class="wscale" aria-hidden="true"><i></i><span><em style="left:0">안 봄</em><em style="left:' + (100 / MAX_W).toFixed(1) +
      '%">보통</em><em style="left:100%">많이</em></span><i></i></div>' +
      '<div class="wrows">' + rowsHTML(p) + "</div>" +
      '<h3 class="kwh">챙겨 볼 키워드</h3><div class="kwchips">' + chipsHTML(p) + "</div>" +
      '<form class="kwadd"><input type="text" name="kw" placeholder="예: 원전, 배터리" aria-label="키워드 추가"><button type="submit">추가</button></form>' +
      '<h3 class="kwh">아는 경제 개념 <small class="hint">해설에서 기초 설명을 뺍니다</small></h3><div class="kwchips knownchips">' + knownHTML(p) + "</div>" +
      '<p class="sync">' + syncText() + "</p>" +
      '<div class="actions"><button type="button" data-x="reset">기본값으로</button><button type="button" data-x="survey">설문</button>' +
      '<button type="button" data-x="close">닫기</button></div></div>';
    document.body.appendChild(box);
    box.addEventListener("input", function (ev) {
      var t = ev.target.getAttribute && ev.target.getAttribute("data-topic");
      if (!t) return;
      var v = clampW(+ev.target.value);
      ev.target.parentNode.querySelector("output").innerHTML = "<b>" + word(v) + "</b> " + v.toFixed(2);
    });
    box.addEventListener("change", function (ev) {
      var t = ev.target.getAttribute && ev.target.getAttribute("data-topic");
      if (!t) return;
      var q = prefs();
      q.weights[t] = clampW(+ev.target.value);
      save(q);
      laterReapply();
    });
    box.querySelector(".kwadd").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var q = prefs(), kws = keywordList(q).slice(), inp = ev.target.kw;
      inp.value.split(/[,，]/).map(function (s) { return s.trim().slice(0, 30); }).filter(Boolean).forEach(function (k) {
        if (kws.indexOf(k) < 0 && kws.length < 30) kws.push(k);
      });
      inp.value = "";
      q.keywords = kws;
      save(q);
      refreshSettings();
      laterReapply();
    });
    box.addEventListener("click", function (ev) {
      var t = ev.target, x = t.getAttribute && t.getAttribute("data-x"), kw = t.getAttribute && t.getAttribute("data-kw");
      var kn = t.getAttribute && t.getAttribute("data-known");
      if (kn !== null && kn !== undefined) { var kp = prefs(); removeKnown([kp.known[+kn]]); return; }
      if (kw !== null && kw !== undefined) {
        var q = prefs(), kws = keywordList(q).slice();
        kws.splice(+kw, 1);
        q.keywords = kws;
        save(q); refreshSettings(); laterReapply();
      }
      if (x === "close") box.remove();
      if (x === "survey") { box.remove(); showSurvey(); }
      if (x === "reset") {
        var r = prefs(), dw = E.defaultTopicWeights || E.topicWeights || {};
        r.weights = {};
        TOPIC_IDS.forEach(function (k) { r.weights[k] = clampW(dw[k] || 0); });
        r.keywords = (E.defaultKeywords || E.keywords || []).slice();
        save(r); refreshSettings(); laterReapply();
        toast("interests.yaml 기본값으로 돌렸습니다");
      }
    });
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest('[data-act="settings"]')) showSettings();
  });

  // 쪽을 나누기 전에 실행 (app.js 보다 먼저 불러온다)
  var p0 = prefs();
  if (p0.updated && !store.get("news.prefs2", null)) save(p0);   // 예전 delta 를 옮긴 것: 저장하고 서버로도
  apply();
  markPressed();
  window.NEWS_FB = { apply: apply, reapply: reapply, prefs: prefs, weightOf: weightOf, isoWeek: isoWeek, showSurvey: showSurvey, showSettings: showSettings,
                     knows: knows, addKnown: addKnown, removeKnown: removeKnown };
  pull();
})();
