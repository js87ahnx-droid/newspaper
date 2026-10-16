"""공개 직전 검사: Pages 폴더에 평문 지면이나 비밀값이 남지 않았는지.

1. 모든 HTML(정적 파일 제외)이 StaticCrypt 로 암호화돼 있다
2. 그날 지면의 기사 제목·리드가 어느 파일에도 평문으로 없다
3. 비밀값처럼 보이는 문자열(토큰·키)이 없다
실패하면 종료 코드 1 — daily.sh 가 멈추고 커밋·공개하지 않는다.
사용: python tools/verify_site.py docs data/raw/<호>.edition.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MARKER = "staticrypt"
SECRET_LIKE = re.compile(r"(sk-ant-[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}|CLAUDE_CODE_OAUTH_TOKEN\s*=\s*\S+)")


def main(site: Path, edition_path: Path | None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    problems = []
    htmls = [p for p in site.rglob("*.html") if "static" not in p.relative_to(site).parts]
    for p in htmls:
        text = p.read_text(encoding="utf-8", errors="replace")
        if MARKER not in text.lower():
            problems.append(f"암호화 안 됨: {p}")
    samples: list[str] = []
    if edition_path and edition_path.exists():
        ed = json.loads(edition_path.read_text(encoding="utf-8"))
        for ps in ed["sections"].values():
            for it in ps:
                samples.append(it["title"])
                if len(it.get("lead", "")) >= 30:
                    samples.append(it["lead"][:30])
        for row in (ed.get("opinion") or {}).get("editorials", []):
            samples.append(row["title"])
    samples = [s for s in samples if len(s) >= 8]
    for p in site.rglob("*"):
        if not p.is_file() or p.suffix in (".png", ".jpg", ".ico"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        leaked = [s for s in samples if s in text]
        if leaked:
            problems.append(f"기사 글이 평문으로 있음: {p} — 예: {leaked[0][:30]}")
        if SECRET_LIKE.search(text):
            problems.append(f"비밀값처럼 보이는 문자열: {p}")
    if problems:
        print("공개 전 검사 실패:")
        for x in problems:
            print("  -", x)
        return 1
    print(f"공개 전 검사 통과: HTML {len(htmls)}개 모두 암호화, 기사 글 평문 0 (확인 문장 {len(samples)}개)")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None))
