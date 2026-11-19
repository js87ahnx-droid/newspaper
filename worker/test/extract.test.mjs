// 추출기 견본 시험 (S54d) — 실제 Workers 런타임(wrangler 로컬)에 작은 시험용 Worker 를 띄워 HTML 을 넣는다.
// 견본은 매체 페이지 구조만 본뜨고 글은 모두 지어낸 것이다 (공개 저장소에 기사 글을 두지 않음)
import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { unstable_dev } from "wrangler";

let w;
before(async () => {
  w = await unstable_dev("test/extract-harness.js", { experimental: { disableExperimentalWarning: true }, logLevel: "none" });
});
after(async () => { if (w) await w.stop(); });

const run = async (html) => (await w.fetch("/", { method: "POST", body: html })).json();
const line = (n) => `지어낸 문장 ${n}번입니다. 시험용으로 만든 글이며 실제 기사가 아닙니다. 문단 길이를 맞추려고 조금 더 씁니다.`;

test("연합뉴스 꼴: .story-news 안 문단, 기자 칸은 뺌", async () => {
  const html = `<html><head><meta property="og:title" content="지어낸 제목"></head><body>
    <article id="articleWrap"><div class="story-news article">
      <div id="newsWriterCarousel01" class="writer-zone01"><strong class="tit-name">홍길동 기자</strong><button>구독</button></div>
      ${[1, 2, 3, 4, 5].map((n) => `<p>${line(n)}</p>`).join("")}
    </div></article></body></html>`;
  const r = await run(html);
  assert.equal(r.ok, true);
  assert.equal(r.via, "본문 칸");
  assert.equal(r.paragraphs.length, 5);
  assert.ok(!r.paragraphs.some((p) => p.includes("홍길동")));
});

test("매경 증권(stock.mk) 꼴: section#news_body > .news_detail_wrap 의 <br> 줄", async () => {
  const html = `<html><body><section id="news_body" class="sec_body"><div class="news_detail_wrap">
    <span><strong>요약 한 줄</strong></span><br><br>${[1, 2, 3, 4].map((n) => `${line(n)}<br><br>`).join("")}
    <div><figure><img src="https://wimg.example/x.jpg"><figcaption>사진 설명</figcaption></figure></div>${line(5)}<br>
  </div></section></body></html>`;
  const r = await run(html);
  assert.equal(r.ok, true);
  assert.equal(r.via, "본문 칸");
  assert.ok(r.paragraphs.length >= 5);
});

test("동아일보 꼴: .news_view 본문 (지금도 됨 — 퇴행 확인)", async () => {
  const html = `<html><body><section class="news_view">${[1, 2, 3].map((n) => `${line(n)}<br><br>`).join("")}</section></body></html>`;
  const r = await run(html);
  assert.equal(r.ok, true);
  assert.equal(r.via, "본문 칸");
});

test("짧은 정상 기사(2문단 400자 안팎)는 그대로 통과", async () => {
  const p = (n) => `${line(n)} ${line(n + 10)} ${line(n + 20)}`.slice(0, 200);
  const html = `<html><body><div class="article_body"><p>${p(1)}</p><p>${p(2)}</p></div></body></html>`;
  const r = await run(html);
  assert.equal(r.ok, true);
  assert.equal(r.paragraphs.length, 2);
});

const page = (og, body) => `<html><head><meta property="og:title" content="지어낸 제목"><meta property="og:image" content="${og}"></head><body>
  <div class="article_body">${body}${[1, 2, 3].map((n) => `<p>${line(n)}</p>`).join("")}</div></body></html>`;

test("본문 사진이 있으면 대표 그림(og)은 안 씀", async () => {
  const r = await run(page("https://static.example.com/img/a.jpg", `<img src="https://img.example.com/photo/1.jpg" width="600">`));
  assert.deepEqual(r.images.map((i) => i.src), ["https://img.example.com/photo/1.jpg"]);
});

test("본문 사진이 없고 og 가 로고면 사진 0", async () => {
  const r = await run(page("https://static.hankyung.example/img/logo/logo-news-sns.png?v=1", ""));
  assert.equal(r.images.length, 0);
});

test("본문 사진이 없으면 보통 og 는 씀, 폴더 이름만 겹치는 진짜 사진도 살림", async () => {
  const r = await run(page("https://img.example.com/default/2026/11/19/photo.jpg?type=share", ""));
  assert.deepEqual(r.images.map((i) => i.src), ["https://img.example.com/default/2026/11/19/photo.jpg?type=share"]);
});
