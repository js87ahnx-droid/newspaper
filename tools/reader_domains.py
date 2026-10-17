"""원문 재배열 중계(worker/)의 매체 도메인 허용목록을 sources.yaml 의 site 에서 만든다 (S17).

사용: python tools/reader_domains.py          worker/src/domains.json 을 다시 쓴다
      python tools/reader_domains.py --check  다르면 1 로 끝남 (테스트·배포 전 확인)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.settings import load_sources  # noqa: E402

OUT = ROOT / "worker" / "src" / "domains.json"


def domains(root: Path = ROOT) -> list[str]:
    return sorted({d.strip().lower() for s in load_sources(root).sources if s.enabled for d in s.site})


def main(argv: list[str]) -> int:
    text = json.dumps(domains(), indent=1) + "\n"
    if "--check" in argv:
        same = OUT.exists() and OUT.read_text(encoding="utf-8") == text
        print("허용목록 일치" if same else f"허용목록이 sources.yaml 과 다릅니다 — python tools/reader_domains.py 로 다시 만드세요")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"{OUT.relative_to(ROOT)}: {len(domains())}곳")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
