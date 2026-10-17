// 기사 페이지에서 제목·사진·본문 문단만 뽑는다 (HTMLRewriter — 문서 트리를 만들지 않고 흘려 읽어 CPU 를 적게 쓴다)
//
// 후보를 여럿 모아 가장 나은 것을 쓴다 (pipeline/bodies.py 와 같은 생각)
//   1. 매체 본문 칸 (알려진 선택자) — 문단·줄바꿈을 살린 글
//   2. 구조화 데이터 articleBody (ld+json)
//   3. Arc 출판 시스템 데이터 (조선일보 등 — 본문이 자바스크립트 데이터로만 있다)
//   4. <article> 안의 <p> 문단, 그다음 페이지 전체 <p> 문단 (긴 것만)

// 본문 칸 — 매체별로 실측해서 더한다 (앞쪽이 우선)
export const BODY_SELECTORS = [
  "[itemprop=articleBody]", "[itemprop=articlebody]",
  "#articleBody", "#article_body", "#articletxt", "#article-view-content-div", "#news_body_area", "#newsEndContents",
  ".article_body", ".article-body", ".article_txt", ".article-text", ".article__content", ".article_view",
  ".news_view", ".text_area", ".story-body", ".story_area", ".art_body", ".news_cnt_detail_wrap",
  ".article-body__content", ".article__body", ".wysiwyg", ".body-text", ".content__article-body",
  "[data-component=text-block]", "[data-testid=article-body]", "[class*=article-body__content]",
  "section[name=articleBody]", ".StoryBodyCompanionColumn", ".paywall", ".article_right",
];

// 이 안의 글은 본문이 아니다
const SKIP = "script, style, noscript, nav, footer, aside, form, button, iframe, svg, select, figcaption, [aria-hidden=true], [class*=related], [class*=recommend], [class*=share], [class*=byline], [id*=related], [class*=advert], [class*=ad-], [class*=copyright], [class*=reporter]";
const BLOCK = "p, div, br, li, h1, h2, h3, h4, h5, h6, section, blockquote, tr, figure, ul, ol, table, dd, dt";
const VOID = new Set(["br", "img", "hr", "meta", "link", "input", "source", "wbr", "col", "embed", "area", "base", "param", "track"]);

const MIN_CHARS = 120;     // 이보다 짧으면 본문이 아니라 안내문·요약 (짧은 사진 기사는 150자 안팎 — 동아 실측)
const MIN_LOOSE = 300;     // 매체가 본문이라고 표시하지 않은 문단 모음은 더 길어야 본문으로 본다
const MAX_CHARS = 30000;
const MAX_IMAGES = 6;

const NAMED = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", middot: "·", hellip: "…", lsquo: "‘", rsquo: "’", ldquo: "“", rdquo: "”", ndash: "–", mdash: "—", bull: "•", copy: "©", reg: "®", trade: "™", times: "×", lrm: "", rlm: "", zwj: "", zwnj: "" };

export function decodeEntities(s) {
  return s.replace(/&(#x[0-9a-f]+|#[0-9]+|[a-z]+);/gi, (m, e) => {
    if (e[0] === "#") {
      const n = e[1] === "x" || e[1] === "X" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      try { return String.fromCodePoint(n); } catch (x) { return m; }
    }
    const v = NAMED[e.toLowerCase()];
    return v === undefined ? m : v;
  });
}

const stripTags = (s) => decodeEntities(String(s || "").replace(/<br\s*\/?>/gi, "\n").replace(/<\/p>/gi, "\n").replace(/<[^>]+>/g, ""));

// 문단 정리: 공백 접기, 빈 줄·짧은 꼬리말·저작권 문구 빼기, 같은 문단 되풀이 빼기
const JUNK = /^(©|ⓒ|copyright|저작권자|무단\s*전재|<저작권|\[?사진\s*=|기자\s*[\w.-]+@|[\w.-]+@[\w.-]+\.\w+$|구독|좋아요|공유하기|기사\s*제보|advertisement$|sign up|subscribe|read more|related:|watch:)/i;
// 한 줄 전체가 이것뿐이면 버튼·메뉴 글자
const LABELS = new Set(["광고", "닫기", "close", "공유", "공유하기", "기사 공유", "더보기", "글자크기", "인쇄", "프린트", "advertisement", "skip advertisement", "share", "listen", "save", "copy link", "video", "동영상", "play"]);
export function paragraphs(text) {
  const seen = new Set();
  const out = [];
  for (let line of String(text || "").split(/\n+/)) {
    line = line.replace(/[ \t ​]+/g, " ").trim();
    if (!line || JUNK.test(line) || LABELS.has(line.toLowerCase()) || /^요약 내용은|AI 서비스를 통해 제공/.test(line) || seen.has(line)) continue;
    seen.add(line);
    out.push(line);
  }
  return out;
}

// 한 문단이 너무 길면(구조화 데이터에 줄바꿈이 없는 매체 — SBS 등) 문장 끝에서 300자 안팎으로 나눈다
export function splitLong(ps, limit = 700) {
  const out = [];
  for (const p of ps) {
    if (p.length <= limit) { out.push(p); continue; }
    let cur = "";
    for (const s of p.split(/(?<=[.!?。]["”’)\]]?)\s+/)) {
      if (cur && cur.length + s.length > 320) { out.push(cur); cur = ""; }
      cur = cur ? cur + " " + s : s;
    }
    if (cur) out.push(cur);
  }
  return out;
}

const size = (ps) => ps.reduce((n, p) => n + p.length, 0);

function absUrl(src, base) {
  if (!src) return null;
  src = decodeEntities(src.trim().split(/\s+/)[0]);
  if (src.startsWith("data:")) return null;
  try {
    const u = new URL(src, base);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch (e) { return null; }
}

const BAD_IMG = /(logo|icon|sprite|blank|pixel|spacer|1x1|avatar|profile|btn_|button|banner|emoji|\.svg|\.gif)/i;

function fromLdJson(blocks) {
  for (const b of blocks) {
    let data;
    try { data = JSON.parse(b); } catch (e) { continue; }
    const list = Array.isArray(data) ? data : [data, ...((data && data["@graph"]) || [])];
    for (const d of list) {
      if (d && typeof d.articleBody === "string" && d.articleBody.trim()) return paragraphs(stripTags(d.articleBody.replace(/\\n/g, "\n")));
    }
  }
  return [];
}

function fromFusion(src) {
  const m = /Fusion\.globalContent\s*=\s*(\{[\s\S]*?\});\s*Fusion\./.exec(src || "");
  if (!m) return { paras: [], images: [] };
  let data;
  try { data = JSON.parse(m[1]); } catch (e) { return { paras: [], images: [] }; }
  const paras = [], images = [];
  for (const el of data.content_elements || []) {
    if (el.type === "text" && el.content) paras.push(...paragraphs(stripTags(el.content)));
    else if (el.type === "image" && el.url) {
      // 원본은 5000px 안팎 — 매체가 만들어 둔 줄인 사진이 있으면 그것을 쓴다
      const r = el.resizedUrls || {};
      const small = r.article_leadart || r["16x9_lg"] || r["4x3_lg"] || Object.values(r).find((u) => /width=(6|7|8|9|1[0-2])\d\d\b/.test(u));
      images.push({ src: small || el.url, caption: stripTags(el.caption || "").trim() });
    }
  }
  return { paras, images };
}

export async function extract(response, url, debug) {
  const st = {
    skip: 0, body: 0, art: 0, p: false,
    bodyText: "", artP: "", allP: "", curP: "",
    meta: {}, title: "", ld: [], ldOn: false, ldBuf: "", fusion: "", fusionOn: false,
    images: [], pend: [], done: false,
  };
  const flushP = () => {
    const t = st.curP.trim();
    if (t) { if (st.art > 0) st.artP += t + "\n"; st.allP += t + "\n"; }
    st.curP = ""; st.p = false;
  };
  const sep = () => { if (st.body > 0) st.bodyText += "\n"; };
  // HTMLRewriter 는 한 요소에 닫는 꼬리표 처리기를 하나만 둔다(나중에 단 것이 앞의 것을 덮는다).
  // 그래서 각 처리기는 할 일을 st.pend 에 모으고, 맨 끝의 "*" 처리기가 한 번에 달아 거꾸로(안쪽 일부터) 부른다
  const onEnd = (el, fn) => { if (!VOID.has(el.tagName) && !el.selfClosing) { st.pend.push(fn); return true; } return false; };
  const depth = (key) => ({
    element(el) { if (onEnd(el, () => { st[key]--; if (st[key] === 0) enough(); })) st[key]++; },
  });
  // 본문 칸(또는 <article>)이 닫혔고 글이 충분하면 그 뒤(꼬리말·광고·스크립트)는 읽지 않는다 — CPU 한도(무료 10ms)
  const enough = () => {
    if (st.body === 0 && st.bodyText.length >= 600) st.done = true;
    if (st.art === 0 && st.artP.length >= 800) st.done = true;
  };

  const rw = new HTMLRewriter()
    .on("meta", {
      element(el) {
        const k = (el.getAttribute("property") || el.getAttribute("name") || "").toLowerCase();
        if (k && !(k in st.meta)) st.meta[k] = el.getAttribute("content") || "";
      },
    })
    .on("title", { text(t) { st.title += t.text; } })
    .on("script[type='application/ld+json']", {
      element(el) { st.ldOn = true; st.ldBuf = ""; onEnd(el, () => { st.ld.push(st.ldBuf); st.ldOn = false; }); },
      text(t) { if (st.ldOn) st.ldBuf += t.text; },
    })
    .on("script#fusion-metadata", {
      element(el) { st.fusionOn = true; onEnd(el, () => { st.fusionOn = false; }); },
      text(t) { if (st.fusionOn) st.fusion += t.text; },
    })
    .on(SKIP, depth("skip"))
    .on(BODY_SELECTORS.join(", "), depth("body"))
    .on("article, main", depth("art"))
    .on(BLOCK, {
      element(el) {
        if (st.p) flushP();
        sep();
        if (el.tagName === "p" && st.skip === 0) st.p = true;
        onEnd(el, () => { if (st.p) flushP(); sep(); });
      },
    })
    .on("img", {
      element(el) {
        if (st.skip > 0 || st.body === 0 || st.images.length >= 12) return;   // 본문 칸 안의 사진만 (관련 기사 썸네일 제외)
        const src = absUrl(el.getAttribute("data-src") || el.getAttribute("data-lazy-src") || el.getAttribute("data-original") || el.getAttribute("src"), url);
        const w = parseInt(el.getAttribute("width") || "0", 10);
        if (!src || BAD_IMG.test(src) || (w && w < 120)) return;
        st.images.push({ src, caption: decodeEntities(el.getAttribute("alt") || "").trim(), inBody: st.body > 0 });
      },
    })
    .on("*", {
      element(el) {
        if (!st.pend.length) return;
        const fns = st.pend;
        st.pend = [];
        el.onEndTag(() => { for (let i = fns.length - 1; i >= 0; i--) fns[i](); });
      },
    })
    .onDocument({
      text(t) {
        if (st.skip > 0) return;
        if (st.body > 0) st.bodyText += t.text;
        if (st.p) st.curP += t.text;
      },
    });

  // 바뀐 HTML 은 쓰지 않으므로 모아 두지 않고 흘려 버린다. 본문을 다 읽었으면 거기서 멈춘다
  const rd = rw.transform(response).body.getReader();
  for (;;) {
    const { done } = await rd.read();
    if (done) break;
    if (st.done) { await rd.cancel().catch(() => {}); break; }
  }
  if (st.p) flushP();

  const decode = (s) => paragraphs(decodeEntities(s));
  const fusion = fromFusion(st.fusion);
  const cands = [
    { via: "본문 칸", paras: decode(st.bodyText) },
    { via: "구조화 데이터", paras: fromLdJson(st.ld) },
    { via: "출판 데이터", paras: fusion.paras },
    { via: "기사 문단", paras: decode(st.artP).filter((p) => p.length >= 40) },
    { via: "문단", paras: decode(st.allP).filter((p) => p.length >= 60) },
  ].filter((c) => size(c.paras) >= (c.via === "기사 문단" || c.via === "문단" ? MIN_LOOSE : MIN_CHARS));
  if (debug) return { ok: false, reason: "debug", debug: { skip: st.skip, body: st.body, art: st.art, bodyText: st.bodyText.length, artP: st.artP.length, allP: st.allP.length, ld: st.ld.length, fusion: st.fusion.length, cands: cands.map((c) => c.via + ":" + size(c.paras)) } };
  if (!cands.length) return { ok: false, reason: "본문을 찾지 못함" };
  // 앞 세 후보(매체가 본문이라고 표시한 곳)를 우선, 그중 가장 긴 것. 없으면 문단 모음
  const marked = cands.filter((c) => c.via !== "기사 문단" && c.via !== "문단");
  const best = (marked.length ? marked : cands).reduce((a, b) => (size(b.paras) > size(a.paras) ? b : a));

  // 사진 설명과 똑같은 문단은 사진 아래에 이미 보이므로 뺀다
  const alts = new Set([...st.images, ...fusion.images].map((i) => i.caption).filter(Boolean));
  let total = 0;
  const paras = [];
  for (const p of splitLong(best.paras.filter((x) => !alts.has(x)))) { if (total > MAX_CHARS) break; paras.push(p); total += p.length; }

  const seen = new Set();
  const images = [];
  const og = absUrl(st.meta["og:image"] || st.meta["twitter:image"], url);
  for (const im of [...fusion.images, ...(og ? [{ src: og, caption: "" }] : []), ...st.images.filter((i) => i.inBody)]) {
    const key = im.src.split("?")[0];
    if (seen.has(key) || images.length >= MAX_IMAGES) continue;
    seen.add(key);
    images.push({ src: im.src, caption: im.caption || "" });
  }

  const title = decodeEntities(st.meta["og:title"] || st.meta["twitter:title"] || st.title || "").trim();
  return {
    ok: true,
    url,
    title,
    site: decodeEntities(st.meta["og:site_name"] || "").trim(),
    published: st.meta["article:published_time"] || st.meta["og:article:published_time"] || "",
    images,
    paragraphs: paras,
    via: best.via,
    chars: total,
  };
}
