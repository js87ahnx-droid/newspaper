"""명령줄 진입점: python -m pipeline <명령>"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
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


def _raw_dir(args) -> Path:
    return Path(args.data) / "raw"


def cmd_collect(args: argparse.Namespace) -> int:
    from .collect import collect

    sources = load_sources(Path(args.root))
    raw = _raw_dir(args)
    raw.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(collect(sources, raw / "store.jsonl"))
    with (raw / "collect-log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(report, ensure_ascii=False) + "\n")
    failed = report["feeds_failed"]
    print(
        f"수집: 피드 {report['feeds_ok']}/{report['feeds_total']} 성공, 새 기사 {report['added']}건, "
        f"누적 {report['store_after']}건 (페이지 시각 확인 {report['page_dates_resolved']}건, 실패 {report['page_dates_missing']}건)"
    )
    for r in failed:
        print(f"  실패 {r['source']}/{r['section']}: {r['error']}")
    # 일부 피드 실패는 정상 진행. 전부 실패했을 때만 오류로 끝낸다
    return 1 if report["feeds_ok"] == 0 else 0


def cmd_prepare(args: argparse.Namespace) -> int:
    from .collect import load_store
    from .prepare import current_edition, edition_window, prepare, to_jsonable

    cfg = load_config(Path(args.root))
    sources = load_sources(Path(args.root))
    raw = _raw_dir(args)
    edition = date.fromisoformat(args.date) if args.date else current_edition(datetime.now(timezone.utc), cfg)
    articles, report = prepare(load_store(raw / "store.jsonl"), edition, cfg, sources)

    # 이 호에 기여한 수집 실행들(시간창 앞뒤 여유 포함)의 피드 실패를 함께 보고한다
    start, end = edition_window(edition, cfg)
    lo, hi = start - timedelta(hours=2), end + timedelta(hours=2)
    runs = []
    log_path = raw / "collect-log.jsonl"
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            run = json.loads(line)
            if lo <= datetime.fromisoformat(run["collected_at"]) <= hi:
                runs.append(run)
    report["collect_runs"] = [
        {k: r[k] for k in ("collected_at", "feeds_ok", "feeds_total", "added", "feeds_failed")} for r in runs
    ]
    (raw / f"{edition.isoformat()}.json").write_text(
        json.dumps(to_jsonable(articles), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    Path(args.data, "run-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"{edition} 호: 기사 {report['articles']}건 "
        f"(시간창 밖 {report['dropped_out_of_window']}, 시각 없음 {report['dropped_no_date']}, "
        f"꺼진 매체 {report['dropped_source_disabled']}, 언어 제외 {report['dropped_wrong_lang']}, "
        f"같은 제목 병합 {report['merged_same_title']}), 수집 실행 {len(runs)}회"
    )
    return 0 if articles else 1


def main(argv: list[str] | None = None) -> int:
    # Windows 콘솔 기본 인코딩(cp949)에서 한글 오류 메시지가 깨지지 않게 UTF-8로 고정
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m pipeline", description="○월 ○일자 뉴스 발행 파이프라인")
    parser.add_argument("--root", default=str(ROOT), help="설정 파일이 있는 폴더 (기본: 저장소 루트)")
    parser.add_argument("--data", default=str(ROOT / "data"), help="데이터 폴더 (기본: data/)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="config.yaml · sources.yaml · interests.yaml 검증").set_defaults(func=cmd_validate)
    sub.add_parser("collect", help="켜진 피드를 읽어 누적 저장소에 합침 (시간창 안에서 여러 번 실행)").set_defaults(
        func=cmd_collect
    )
    p = sub.add_parser("prepare", help="호 날짜의 시간창 기사만 골라 중복 제거")
    p.add_argument("--date", help="호 날짜 YYYY-MM-DD (기본: 가장 최근에 끝난 시간창)")
    p.set_defaults(func=cmd_prepare)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
