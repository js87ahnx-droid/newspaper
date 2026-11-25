/* 발행 완료 예정 시각 (S61) — 오늘 호 덮개(app.js)와 지난 호 목록(archive.html.j2)이 같이 쓴다.
 *
 * docs/status.json 의 recent([{date, started, finished}] 정기 실행만, scripts/run_status.py)로
 * 걸리는 시간·시작 시각의 중앙값을 내고, 지금 상태에 맞는 단계와 완료 예정 시각을 돌려준다.
 * 모든 시각은 브라우저 시간대와 무관하게 KST(Asia/Seoul).
 */
(function () {
  "use strict";
  var OPEN = 6 * 60;          // 아침 6시부터 새 호 자리를 보인다 (사용자 지정)
  var DUR = 35;               // 기록이 없을 때 걸리는 시간(분)
  var START = 6 * 60 + 35;    // 기록이 없을 때 시작 시각(KST 하루 중 분)
  var LATE_START = 60;        // 시작 예상 뒤 이만큼 지나도 시작 안 하면 "늦어지고 있음"
  var STALE = 125;            // 시작 뒤 이만큼 지난 running 은 멈춘 것 같음 (S52 와 같음)
  var fmt = null;
  try {
    fmt = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  } catch (e) { fmt = null; }

  function parts(t) {   // {date:"YYYY-MM-DD", min: 하루 중 분}
    if (fmt && fmt.formatToParts) {
      var o = {};
      fmt.formatToParts(new Date(t)).forEach(function (p) { o[p.type] = p.value; });
      return { date: o.year + "-" + o.month + "-" + o.day, min: (+o.hour % 24) * 60 + (+o.minute) };
    }
    var k = new Date(+new Date(t) + 9 * 3600e3);   // Intl 이 없으면 UTC+9 로 직접
    return { date: k.toISOString().slice(0, 10), min: k.getUTCHours() * 60 + k.getUTCMinutes() };
  }
  function ms(iso) { var t = new Date(iso).getTime(); return isNaN(t) ? null : t; }
  function median(a) {
    if (!a.length) return null;
    var s = a.slice().sort(function (x, y) { return x - y; }), h = s.length >> 1;
    return s.length % 2 ? s[h] : (s[h - 1] + s[h]) / 2;
  }
  function rows(st) { return st && Array.isArray(st.recent) ? st.recent : []; }
  function duration(st) {   // 분
    var d = [];
    rows(st).forEach(function (r) {
      var a = ms(r && r.started), b = ms(r && r.finished);
      if (a != null && b != null && b > a && b - a < 6 * 3600e3) d.push((b - a) / 60e3);
    });
    var m = median(d);
    return m == null ? DUR : m;
  }
  function startGuess(st) {   // KST 하루 중 분
    var d = [];
    rows(st).forEach(function (r) { var a = ms(r && r.started); if (a != null) d.push(parts(a).min); });
    var m = median(d);
    return m == null ? START : m;
  }
  // D 날짜 00:00 KST 의 시각(ms)
  function dayStart(date) { return Date.parse(date + "T00:00:00+09:00"); }
  function hm(t) { var m = parts(t).min; return ("0" + Math.floor(m / 60)).slice(-2) + ":" + ("0" + m % 60).slice(-2); }
  function ceil5(t) { return Math.ceil(t / 300e3) * 300e3; }
  function label(date) { var p = date.split("-"); return (+p[1]) + "월 " + (+p[2]) + "일자"; }

  /* 지금 나와야 할 호(KST 오늘)의 진행 상황.
   * phase: wait(시작 전) · delayed(시작 예상+60분 지나도 시작 안 함) · run · late(예정 지남) · stuck(멈춘 것 같음) · error · done
   *        · null(아직 6시 전이고 시작도 안 함 — 보일 것 없음)
   * eta: 완료 예정(ms, 5분 올림) — wait·run 만, 나머지는 null */
  function info(st, now) {
    now = now == null ? Date.now() : +now;
    var today = parts(now), D = today.date;
    var mine = st && st.date === D;
    var out = { date: D, name: label(D), phase: null, eta: null, etaText: "", step: 0, steps: (st && +st.steps) || 7,
                label: "", started: "", updated: "", message: "" };
    if (mine && st.state === "done") { out.phase = "done"; return out; }
    if (mine && (st.state === "running" || st.state === "error")) {
      out.step = Math.max(1, Math.min(out.steps, +st.step || 1));
      out.label = String(st.label || "");
      out.started = st.started ? hm(st.started) : "";
      out.updated = st.updated ? hm(st.updated) : "";
      if (st.state === "error") { out.phase = "error"; out.message = String(st.message || ""); return out; }
      var s = ms(st.started);
      if (s == null || now - s > STALE * 60e3) { out.phase = "stuck"; return out; }
      var e = s + duration(st) * 60e3;
      if (now > e) { out.phase = "late"; return out; }
      out.phase = "run"; out.eta = ceil5(e); out.etaText = hm(out.eta);
      return out;
    }
    if (today.min < OPEN) return out;                 // 6시 전, 아직 시작 안 함
    var guess = dayStart(D) + startGuess(st) * 60e3;
    if (now > guess + LATE_START * 60e3) { out.phase = "delayed"; return out; }
    var e2 = Math.max(now, guess) + duration(st) * 60e3;
    out.phase = "wait"; out.eta = ceil5(e2); out.etaText = hm(out.eta);
    return out;
  }

  window.NEWS_ETA = { info: info, parts: parts, hm: hm, label: label, duration: duration, startGuess: startGuess, median: median,
                      OPEN: OPEN };
})();
