"""파일 쓰기·읽기 (S29d, 2026-10-23 점검): 쓰다 끊겨도 반쯤 쓴 파일이 남지 않게, 깨진 캐시·기록 하나에 발행이 멈추지 않게.

10/23 로컬 실행이 끊기며 data/raw 의 edition·issues JSON 과 소스 파일 넷이 NUL 바이트로 채워졌다. Actions 에서 같은 일이 나면
깨진 data/raw 가 캐시로 저장(if: always())되어 다음 실행부터 json.loads 에서 계속 실패한다.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def write_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """임시 파일에 다 쓴 뒤 바꿔 끼운다 (Path.write_text 와 같은 텍스트 모드)."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding=encoding) as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json(path: Path, default):
    """없거나 깨졌으면 default (깨졌으면 경고). 캐시·기록용 — 지면 데이터처럼 꼭 있어야 하는 파일엔 쓰지 않는다."""
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        print(f"경고: 깨진 파일 {path.name} 건너뜀 ({str(e)[:60]})", file=sys.stderr)
        return default
