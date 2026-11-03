/* 설정 창의 "편집 리뷰"·"편집 기준" 탭 (S38b·S38d, 20차 요청).
 *
 * - 편집 리뷰: 이 호 뉴스 면 기사(window.EDITION.review — 발행이 넣음)를 면별로. 기사마다 [적절][위로][아래로][빼기],
 *   방향을 고르면 메모 칸. 다시 누르면 취소. localStorage "news.reviews" = {호: {기사 id: {verdict, memo}}} (최근 7개 호)
 *   · 바꾸면 1.5초 모아 중계 서버(Worker)의 /reviews 로 그 호 리뷰 전체를 점수·분야와 함께 보낸다 (worker/src/reviews.js)
 *   · 이 기기에 그 호 리뷰가 없으면 처음 열 때 서버 것을 받아 쓴다 (다른 기기에서 한 것)
 *   · 발행이 매일 받아 메모를 뺀 채 data/reviews 에, 주마다 편집 가중치를 조금씩 조정한다 (pipeline/review.py)
 * - 편집 기준: 지금 쓰는 값(자동 조정을 덮은 것)으로 점수 식·고르는 순서·자동 조정 내역, "자동 조정 되돌리기"
 * 지면 기사의 점수 펼침("주목·중요")은 그대로 둔다 (사용자 2026-11-03).
 */
(function () {
  "use strict";
  var E = window.EDITION || {};
  var RD = E.reader && E.reader.url && E.reader.key ? E.reader : null;
  var KEY = "news.reviews", KEEP = 7, WAIT = 1500, MAX_MEMO = 200;
  var VERDICTS = [["ok", "적절"], ["up", "위로"], ["down", "아래로"], ["drop", "빼기"]];
  var SEC_TITLE = { front: "1면", interest: "관심면" };
  var timer = 0, state = "idle", pulled = false;

  var store = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* 저장 불가 환경 */ } }
  };
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function num(v) { return (+v || 0).toFixed(2).replace(/^0/, ""); }

  function all() { var a = store.get(KEY, {}); return a && typeof a === "object" ? a : {}; }
  function mine() { return all()[E.edition] || {}; }
  function keep(items) {
    var a = all();
    a[E.edition] = items;
    Object.keys(a).sort().reverse().slice(KEEP).forEach(function (k) { delete a[k]; });
    store.set(KEY, a);
  }
  function byId() { var m = {}; (E.review || []).forEach(function (r) { m[r.id] = r; }); return m; }

  function body() {
    var m = byId(), items = {}, got = mine();
    Object.keys(got).forEach(function (id) {
      var r = m[id], g = got[id];
      if (!r || !g || !g.verdict) return;
      items[id] = { verdict: g.verdict, topic: r.tp, section: r.s, rank: r.r, scores: r.sc };
      if (g.memo) items[id].memo = String(g.memo).slice(0, MAX_MEMO);
    });
    return JSON.stringify({ v: 1, edition: E.edition, items: items, updated: new Date().toISOString() });
  }
  function push() {
    if (!RD) return;
    fetch(RD.url + "/reviews", { method: "POST", headers: { "X-Reader-Key": RD.key, "Content-Type": "application/json" }, body: body(),
      cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" })
      .then(function (r) { if (!r.ok) throw new Error("http " + r.status); state = "sent"; status(); })
      .catch(function () { state = "failed"; status(); });
  }
  function schedule() {
    if (!RD) { status(); return; }
    state = "pending"; status();
    clearTimeout(timer);
    timer = setTimeout(push, WAIT);
  }
  // 이 기기에 이 호 리뷰가 없으면 서버 것(다른 기기)을 받아 쓴다
  function pull(done) {
    if (pulled || !RD || Object.keys(mine()).length) { pulled = true; return; }
    pulled = true;
    fetch(RD.url + "/reviews?from=" + encodeURIComponent(E.edition), { headers: { "X-Reader-Key": RD.key }, cache: "no-store",
      credentials: "omit", referrerPolicy: "no-referrer" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        var rec = j && j.ok && (j.reviews || []).filter(function (x) { return x && x.edition === E.edition; })[0];
        if (!rec || !rec.items || Object.keys(mine()).length) return;
        var items = {};
        Object.keys(rec.items).forEach(function (id) { items[id] = { verdict: rec.items[id].verdict, memo: rec.items[id].memo || "" }; });
        keep(items);
        state = "sent";
        if (done) done();
      })
      .catch(function () { /* 서버를 못 보면 이 기기 값으로 */ });
  }

  function statusText() {
    var n = Object.keys(mine()).length;
    var head = "이 호 평가 " + n + "건. ";
    return head + (!RD ? "서버 주소가 없어 이 기기에만 저장됩니다."
      : state === "pending" ? "서버로 보내는 중…"
      : state === "failed" ? "서버로 보내지 못했습니다 — 다시 고르면 다시 보냅니다."
      : state === "sent" ? "서버에 저장했습니다. 매주 모아 편집 가중치를 조금씩 조정합니다."
      : "모인 리뷰로 매주 편집 가중치를 조금씩 조정합니다.");
  }
  function status() {
    var el = document.querySelector('#settings [data-pane="review"] .rvstat');
    if (el) el.textContent = statusText();
  }

  function rowHTML(r, g) {
    var v = g && g.verdict, sc = r.sc || {};
    var btns = VERDICTS.map(function (x) {
      return '<button type="button" data-rv="' + x[0] + '"' + (v === x[0] ? ' class="on" aria-pressed="true"' : ' aria-pressed="false"') + ">" + x[1] + "</button>";
    }).join("");
    var memo = v && v !== "ok"
      ? '<input type="text" class="rvmemo" maxlength="' + MAX_MEMO + '" placeholder="이유 (선택)" aria-label="메모" value="' + esc((g && g.memo) || "") + '">' : "";
    return '<div class="rv" data-id="' + esc(r.id) + '">' +
      '<div class="rvt"><span class="rk">' + r.r + "</span>" + esc(r.t) + "</div>" +
      '<div class="rvs">주목 ' + num(sc.attention) + " · 중요 " + num(sc.importance) + " · 머리 " + num(sc.headline) +
      (sc.continuity ? " · 연속 " + num(sc.continuity) : "") + " · 관심 " + num(sc.interest) + " · <b>종합 " + num(sc.final) + "</b></div>" +
      (r.why ? '<div class="rvw">' + esc(r.why) + "</div>" : "") +
      '<div class="rvb">' + btns + "</div>" + memo + "</div>";
  }
  function reviewHTML() {
    var rows = E.review || [], got = mine(), order = [], groups = {};
    if (!rows.length) return '<p class="hint">이 호에는 평가할 기사 목록이 없습니다.</p>';
    rows.forEach(function (r) { if (!groups[r.s]) { groups[r.s] = []; order.push(r.s); } groups[r.s].push(r); });
    var titles = E.sectionTitles || {};
    return '<p class="rvstat">' + statusText() + "</p>" + order.map(function (s, i) {
      var done = groups[s].filter(function (r) { return got[r.id]; }).length;
      return '<details class="rvsec"' + (i === 0 ? " open" : "") + "><summary>" + esc(SEC_TITLE[s] || titles[s] || s) +
        " <small>" + groups[s].length + "건" + (done ? " · 평가 " + done : "") + "</small></summary>" +
        groups[s].map(function (r) { return rowHTML(r, got[r.id]); }).join("") + "</details>";
    }).join("");
  }

  function bindReview(pane) {
    if (pane.getAttribute("data-bound")) return;
    pane.setAttribute("data-bound", "1");
    pane.addEventListener("click", function (ev) {
      var b = ev.target.closest && ev.target.closest("[data-rv]");
      if (!b) return;
      var row = b.closest(".rv"), id = row.getAttribute("data-id"), v = b.getAttribute("data-rv");
      var got = mine(), g = got[id] || {};
      if (g.verdict === v) delete got[id];   // 다시 누르면 취소
      else got[id] = { verdict: v, memo: v === "ok" ? "" : (g.memo || "") };
      keep(got);
      var r = byId()[id];
      if (r) {
        var tmp = document.createElement("div");
        tmp.innerHTML = rowHTML(r, got[id]);
        row.parentNode.replaceChild(tmp.firstChild, row);
      }
      schedule();
    });
    pane.addEventListener("change", function (ev) {
      if (!ev.target.classList || !ev.target.classList.contains("rvmemo")) return;
      var id = ev.target.closest(".rv").getAttribute("data-id"), got = mine();
      if (!got[id]) return;
      got[id].memo = ev.target.value.trim().slice(0, MAX_MEMO);
      keep(got);
      schedule();
    });
  }

  // ---- 편집 기준 (S38d) ----
  var W_LABEL = { attention: "주목도", importance: "중요도", headline: "머리기사", interest: "관심도", continuity: "연속성" };
  function pct(v) { return Math.round((+v || 0) * 100) + "%"; }
  function val(cur, base) {
    var c = (+cur).toFixed(2);
    return Math.abs(cur - base) >= 0.001 ? "<b>" + c + "</b> <small>(기본 " + (+base).toFixed(2) + ")</small>" : c;
  }
  function changeText(c) { return esc(c.label) + " " + (+c.from).toFixed(2) + " → " + (+c.to).toFixed(2); }
  function weekDay(ed) { var m = /^\d{4}-(\d{2})-(\d{2})$/.exec(ed || ""); return m ? (+m[1]) + "/" + (+m[2]) + " 호" : ""; }
  function rulesHTML() {
    var g = E.editing;
    if (!g) return '<p class="hint">이 호에는 편집 기준 정보가 없습니다.</p>';
    var w = g.w, bw = g.bw, topics = E.topics || {}, r = g.rules, L = g.learned;
    var formula = ["attention", "importance", "headline", "interest", "continuity"].map(function (k) {
      return W_LABEL[k] + " " + val(w[k], bw[k]);
    }).join(" + ");
    var ti = Object.keys(g.ti).sort(function (a, b) { return g.ti[b] - g.ti[a]; }).map(function (t) {
      return '<span class="rlt">' + esc(topics[t] || t) + " " + val(g.ti[t], g.bti[t]) + "</span>";
    }).join("");
    var intl = (r.topicMax || {}).international;
    var auto;
    if (L && L.week) {
      auto = "<p>마지막 조정 <b>" + esc(L.week) + "</b> (" + weekDay(L.edition) + ", 리뷰 " + (L.reviews || 0) + "건)</p>" +
        ((L.changes || []).length ? "<ul>" + L.changes.map(function (c) { return "<li>" + changeText(c) + "</li>"; }).join("") + "</ul>"
          : "<p>바뀐 값 없음</p>");
    } else {
      auto = "<p>" + (L && L.reset_at ? "되돌린 뒤 아직 자동 조정 없음." : "아직 자동 조정 없음.") +
        " 4주 안에 방향 있는 리뷰(위로·아래로·빼기)가 10건 모이면 그 주에 처음 조정합니다.</p>";
    }
    var hist = L && (L.history || []).length > 1 ? '<details class="rlhist"><summary>지난 조정</summary><ul>' +
      L.history.slice(0, -1).reverse().map(function (h) {
        return "<li>" + esc(h.week) + " · 리뷰 " + h.reviews + "건 · " + ((h.changes || []).map(changeText).join(", ") || "바뀐 값 없음") + "</li>";
      }).join("") + "</ul></details>" : "";
    return '<div class="rules">' +
      "<h3>종합 점수</h3><p>" + formula + " <small>(가중치 합으로 나눔)</small></p>" +
      "<table><tr><th>주목도</th><td>다룬 매체 영향력 합 + 다룬 나라 수 + 매체 메인 피드 노출</td></tr>" +
      "<tr><th>중요도</th><td>분야 기본값 + 핵심어(전쟁·금리·관세 등, 하나에 " + (+g.kwBonus).toFixed(2) + ", 3개까지) + 다룬 나라 수</td></tr>" +
      "<tr><th>머리기사</th><td>종이신문 1면·홈페이지 맨 위에 올린 매체 (1위 1.0, 2위 0.5, 3위 0.35)</td></tr>" +
      "<tr><th>관심도</th><td>관심도 탭의 분야 값 + 챙겨 볼 키워드</td></tr>" +
      "<tr><th>연속성</th><td>전날부터 이어진 날수</td></tr></table>" +
      '<h3>분야 중요도</h3><p class="rlts">' + ti + "</p>" +
      "<h3>고르는 순서</h3><ol>" +
      "<li>1면 톱: 관심도 빼고, 머리기사 비중 " + val(w.front_headline, bw.front_headline) + "로 셈</li>" +
      "<li>다양성: 지면의 " + pct(r.diversity) + "는 관심도와 상관없이 주목도 상위</li>" +
      "<li>연속: " + r.contDays + "일 이상 이어진 이슈를 지면의 " + pct(r.contMax) + "까지</li>" +
      "<li>나머지는 종합 점수 순. 관심도 덕분에 들어온 기사는 " + pct(r.interestCap) + "까지" +
      (intl ? ", 국제는 " + pct(intl) + "까지" : "") + "</li></ol>" +
      "<h3>자동 조정</h3>" + auto + hist +
      '<p class="hint">편집 리뷰를 주마다 모아 주목도·중요도·머리기사·연속성 가중치(기본값의 0.7~1.3배)와 분야 중요도(0.6~1.4배)를 조금씩 바꿉니다. 관심도 가중치는 바꾸지 않습니다.</p>' +
      (RD ? '<div class="actions"><button type="button" data-rl="reset">자동 조정 되돌리기</button></div><p class="rlstat" aria-live="polite"></p>' : "") +
      "</div>";
  }
  function bindRules(pane) {
    if (pane.getAttribute("data-bound")) return;
    pane.setAttribute("data-bound", "1");
    pane.addEventListener("click", function (ev) {
      var b = ev.target.closest && ev.target.closest('[data-rl="reset"]');
      if (!b || !RD) return;
      if (!window.confirm("자동 조정값을 지우고 config.yaml 값으로 돌릴까요? 다음 발행부터 적용되고, 지금까지의 리뷰는 더 쓰지 않습니다.")) return;
      var st = pane.querySelector(".rlstat");
      b.disabled = true;
      fetch(RD.url + "/reviews/reset", { method: "POST", headers: { "X-Reader-Key": RD.key }, cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer" })
        .then(function (r) { if (!r.ok) throw new Error("http " + r.status); st.textContent = "되돌리기를 요청했습니다 — 다음 발행 때 기본값으로 돌아갑니다."; })
        .catch(function () { b.disabled = false; st.textContent = "서버로 보내지 못했습니다. 잠시 뒤 다시 눌러 주세요."; });
    });
  }

  function render(pane, kind) {
    if (kind === "review") {
      pane.innerHTML = reviewHTML();
      bindReview(pane);
      pull(function () { if (pane.isConnected) { pane.innerHTML = reviewHTML(); } });
    } else if (kind === "rules") {
      pane.innerHTML = rulesHTML();
      bindRules(pane);
    }
  }

  window.NEWS_EDIT = { render: render, reviews: mine, body: body };
})();
