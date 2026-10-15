"""명령줄 진입점: python -m pipeline <명령>"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .settings import ROOT, SettingsError, load_config, load_interests, load_sources


def cmd_validate(args: argparse.Namespace) -> int:
    root = Path(args.root)
    errors = []
    for loader in (load_config, load_sources, load_interests):
        try:
            loader(root)
        except SettingsError as e:
            errors.append(str(e))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("설정 파일 3개 검증 통과")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Windows 콘솔 기본 인코딩(cp949)에서 한글 오류 메시지가 깨지지 않게 UTF-8로 고정
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m pipeline", description="○월 ○일자 뉴스 발행 파이프라인")
    parser.add_argument("--root", default=str(ROOT), help="설정 파일이 있는 폴더 (기본: 저장소 루트)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="config.yaml · sources.yaml · interests.yaml 검증").set_defaults(func=cmd_validate)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
