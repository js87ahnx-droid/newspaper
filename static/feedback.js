/* 피드백·주간 설문 — 기기 안에서만 학습한다 (지시서 6-2, 6-3, 결정 D3: 기기 내 학습 + 내보내기).
 *
 * - "더 보기 / 덜 보기" 를 누르면 그 기사 분야의 관심 가중치를 ±0.25 바꿔 localStorage 에 둔다.
 * - 다음에 열 때(쪽을 나누기 전에) 관심도를 서버와 같은 식으로 다시 계산해 지면 안 배치를 바꾼다.
 *   · 섹션 안 순서를 다시 정렬 (1면 톱은 그대로)
 *   · 많이 "덜 보기" 한 분야(가중치 0.1 이하)의 기사는 단신으로 내린다
 *   · 많이 "더 보기" 한 분야(기본보다 0.5 이상)의 단신은 관심면으로 올린다 — 관심 상한(서버와 같은 50%) 안에서만
 *   · 1면 톱·다양성·연속 보장 기사는 내리지 않는다 (다양성 규칙이 항상 우선, 6-3)
 * - 주 1회 첫 장 위에 설문 카드(3문항). 응답은 같은 경로로 가중치에 반영.
 * - 설정 창에서 학습된 가중치를 보고, interests.yaml 에 옮길 수 있게 파일로 내보낸다.
 */
(function () {
  "use strict";
  var E = window.EDITION || {};
  var flow = document.getElementById("flow");
  var STEP = 0.25, SURVEY_STEP = 0.5, MAX_W = 3;

  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 저장 불가 환경 */ } }
  };

  function prefs() {
    var p = store.get("news.prefs", null) || {};
    p.delta = p.delta || {};
    p.keywords = p.keywords || [];
    return p;
  }

  function weightOf(p, topic) {
    var base = (E.topicWeights || {})[topic] || 0;
    return Math.max(0, Math.min(MAX_W, base + (p.delta[topic] || 0)));
  }

  function keywordHit(p, text) {
    var low = text.toLowerCase();
    return (E.keywords || []).concat(p.keywords).some(function (k) { return k && low.indexOf(String(k).toLowerCase()) >= 0; });
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
  function apply() {
    var p = prefs();
    var moved = { demoted: 0, promoted: 0 };
    var arts = Array.prototype.slice.call(flow.querySelectorAll("section.sec > article.item[data-a]"));
    arts.forEach(function (a) { a.setAttribute("data-final2", rescore(a, p).toFixed(4)); });

    var briefs = sectionEl("briefs");
    // 내리기: 많이 "덜 보기" 한 분야의 보장 안 된 기사
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
    // 올리기: 많이 "더 보기" 한 분야의 단신 — 관심 상한 안에서
    var room = Math.max(0, (E.interestCap || 0) - (E.interestCounted || 0));
    var cap = (E.sectionCaps || {}).interest || 6;
    if (briefs && room > 0) {
      var cands = Array.prototype.slice.call(briefs.querySelectorAll("article.item"))
        .filter(function (a) {
          var t = a.getAttribute("data-topic");
          return a.getAttribute("data-guaranteed") !== "1" && a.getAttribute("data-moved") !== "down" &&
                 weightOf(p, t) >= ((E.topicWeights || {})[t] || 0) + 0.5;
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
    p.delta[d.topic] = Math.round(((p.delta[d.topic] || 0) + change) * 1000) / 1000;
    if (!p.delta[d.topic]) delete p.delta[d.topic];
    store.set("news.prefs", p);
    var log = store.get("news.fbLog", []) || [];
    log.push({ t: new Date().toISOString(), edition: E.edition, issue: d.issue, topic: d.topic, kind: undo ? "undo" : d.kind });
    store.set("news.fbLog", log.slice(-500));
    if (undo) delete keep[E.edition][d.issue]; else keep[E.edition][d.issue] = d.kind;
    store.set("news.pressed", keep);
    // 같은 기사의 단추 표시: 누른 것만 (취소면 모두 지움)
    document.querySelectorAll('[data-issue="' + d.issue + '"] [data-fb]').forEach(function (b) {
      b.classList.toggle("pressed", !undo && b.getAttribute("data-fb") === d.kind);
    });
    toast(undo ? label + " 분야 " + (d.kind === "more" ? "더" : "덜") + " 보기를 취소했습니다"
      : label + " 분야를 " + (d.kind === "more" ? "더" : "덜") + " 보도록 기억했습니다 · 다음에 열 때 반영");
  });

  // ---------- 주간 설문 ----------
  function isoWeek(d) {
    var t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    var day = t.getUTCDay() || 7;
    t.setUTCDate(t.getUTCDate() + 4 - day);
    var y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1));
    return t.getUTCFullYear() + "-W" + String(Math.ceil(((t - y0) / 86400000 + 1) / 7)).padStart(2, "0");
  }
  function surveyDue(now) { return store.get("news.survey", null) !== isoWeek(now || new Date()); }

  function chips(name) {
    return Object.keys(E.topics || {}).map(function (t) {
      return '<label class="chip"><input type="checkbox" name="' + name + '" value="' + t + '"><span>' + E.topics[t] + "</span></label>";
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
      '<fieldset><legend>1. 이번 주 덜 보고 싶던 분야는?</legend>' + chips("less") + "</fieldset>" +
      '<fieldset><legend>2. 더 보고 싶은 분야는?</legend>' + chips("more") + "</fieldset>" +
      '<fieldset><legend>3. 새로 보고 싶은 키워드는? (쉼표로 구분)</legend><input type="text" name="kw" placeholder="예: 원전, 배터리"></fieldset>' +
      '<div class="actions"><button type="button" data-s="later">다음 주에</button><button type="submit" data-s="save">저장</button></div>' +
      '<p class="hint">답은 이 기기에만 저장되고, 관심 밖이라도 중요한 뉴스는 계속 실립니다.</p></form>';
    document.body.appendChild(box);
    var form = box.querySelector("form");
    function close() { store.set("news.survey", isoWeek(new Date())); box.remove(); }
    box.querySelector('[data-s="later"]').addEventListener("click", close);
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var p = prefs();
      form.querySelectorAll('input[name="less"]:checked').forEach(function (i) { p.delta[i.value] = (p.delta[i.value] || 0) - SURVEY_STEP; });
      form.querySelectorAll('input[name="more"]:checked').forEach(function (i) { p.delta[i.value] = (p.delta[i.value] || 0) + SURVEY_STEP; });
      form.kw.value.split(/[,，]/).map(function (s) { return s.trim(); }).filter(Boolean).forEach(function (k) {
        if (p.keywords.indexOf(k) < 0) p.keywords.push(k);
      });
      store.set("news.prefs", p);
      close();
      apply();
      if (window.NEWS) window.NEWS.rebuild();
      toast("설문을 반영했습니다");
    });
  }

  // ---------- 설정 창: 학습된 가중치·내보내기·초기화 ----------
  function learnedExport() {
    var p = prefs(), topics = {}, less = [];
    Object.keys(E.topicWeights || {}).forEach(function (t) {
      var w = Math.round(weightOf(p, t) * 100) / 100;
      if (w >= 1) topics[t] = w; else if (w <= 0.25) less.push(t);
    });
    return {
      note: "interests.yaml 에 옮길 값 (기기에서 학습). topics·less·keywords 를 복사해 붙이면 서버 편집에도 반영됩니다.",
      exported: new Date().toISOString(), edition: E.edition,
      topics: topics, less: less, keywords: (E.keywords || []).concat(p.keywords.filter(function (k) { return (E.keywords || []).indexOf(k) < 0; })),
      learned_delta: p.delta, feedback_count: (store.get("news.fbLog", []) || []).length
    };
  }

  function showSettings() {
    var old = document.getElementById("settings");
    if (old) { old.remove(); return; }
    var p = prefs();
    var rows = Object.keys(E.topics || {}).map(function (t) {
      var base = (E.topicWeights || {})[t] || 0, w = weightOf(p, t);
      return "<tr><td>" + E.topics[t] + "</td><td>" + base.toFixed(2) + "</td><td>" + (w >= base ? "+" : "") + (w - base).toFixed(2) +
             "</td><td><b>" + w.toFixed(2) + "</b></td></tr>";
    }).join("");
    var box = document.createElement("div");
    box.id = "settings";
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "관심 설정");
    box.innerHTML = '<div class="card"><h2>관심 학습</h2><table><thead><tr><th>분야</th><th>기본</th><th>학습</th><th>지금</th></tr></thead><tbody>' +
      rows + "</tbody></table><p>추가 키워드: " + (p.keywords.join(", ") || "없음") + "</p>" +
      '<div class="actions"><button type="button" data-x="export">가중치 내보내기</button><button type="button" data-x="survey">설문 다시</button>' +
      '<button type="button" data-x="reset">학습 초기화</button><button type="button" data-x="close">닫기</button></div>' +
      '<p class="hint">학습 결과는 이 기기에만 있습니다. 서버 편집에 반영하려면 내보낸 파일의 값을 interests.yaml 에 옮기세요.</p></div>';
    document.body.appendChild(box);
    box.addEventListener("click", function (ev) {
      var x = ev.target.getAttribute && ev.target.getAttribute("data-x");
      if (x === "close") box.remove();
      if (x === "survey") { box.remove(); showSurvey(); }
      if (x === "reset" && confirm("이 기기의 관심 학습을 지울까요?")) {
        try { ["news.prefs", "news.fbLog", "news.pressed"].forEach(function (k) { localStorage.removeItem(k); }); } catch (e) { /* 무시 */ }
        box.remove(); toast("학습을 초기화했습니다 · 다음에 열 때 반영");
      }
      if (x === "export") {
        var blob = new Blob([JSON.stringify(learnedExport(), null, 2)], { type: "application/json" });
        var a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "interests-learned-" + (E.edition || "today") + ".json";
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
      }
    });
  }

  document.addEventListener("click", function (e) {
    if (e.target.closest && e.target.closest('[data-act="settings"]')) showSettings();
  });

  // 쪽을 나누기 전에 실행 (app.js 보다 먼저 불러온다)
  apply();
  markPressed();
  window.NEWS_FB = { apply: apply, prefs: prefs, isoWeek: isoWeek, surveyDue: surveyDue, showSurvey: showSurvey, exportData: learnedExport };
  if (surveyDue()) setTimeout(showSurvey, 600);
})();
