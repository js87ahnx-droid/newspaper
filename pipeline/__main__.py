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


def _cache(args, cfg):
    from .embcache import EmbeddingCache

    name = cfg.clustering.model.split("/")[-1]
    return EmbeddingCache(_raw_dir(args) / f"emb-{name}.npz")


def cmd_embed(args: argparse.Namespace) -> int:
    """지금 채워지는 호의 기사 중 아직 임베딩이 없는 것만 계산해 캐시에 넣는다 (수집 직후 실행)."""
    import time

    from .collect import load_store
    from .prepare import prepare, target_edition

    cfg = load_config(Path(args.root))
    sources = load_sources(Path(args.root))
    store = load_store(_raw_dir(args) / "store.jsonl")
    edition = date.fromisoformat(args.date) if args.date else target_edition(datetime.now(timezone.utc), cfg)
    articles, _ = prepare(store, edition, cfg, sources)
    cache = _cache(args, cfg)
    t0 = time.perf_counter()
    n = cache.fill(articles, cfg.clustering.model)
    # 캐시 키는 정제 뒤 기사(리드 상한 적용) 기준이므로 정리도 정제 결과로 한다: 이번 호와 직전 호만 남김
    prev, _ = prepare(store, edition - timedelta(days=1), cfg, sources)
    pruned = cache.prune(articles + prev)
    cache.save()
    print(f"임베딩: {edition} 호 기사 {len(articles)}건 중 새로 계산 {n}건 ({time.perf_counter() - t0:.0f}초), 캐시 정리 {pruned}건")
    return 0


def cmd_cluster(args: argparse.Namespace) -> int:
    import time

    from .cluster import build_issues, issues_to_json, similarity_matrix
    from .collect import Article

    cfg = load_config(Path(args.root))
    raw = _raw_dir(args)
    path = raw / f"{args.date}.json"
    articles = [Article.from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))]
    t0 = time.perf_counter()
    cache = _cache(args, cfg)
    computed = cache.fill(articles, cfg.clustering.model)  # 미리 못 한 것만
    vecs = cache.get(articles)
    t1 = time.perf_counter()
    threshold = args.threshold or cfg.clustering.similarity_threshold
    sim = similarity_matrix(articles, vecs, cfg.clustering)
    issues = build_issues(articles, sim, threshold, cfg.clustering.linkage)
    t2 = time.perf_counter()
    (raw / f"{args.date}.issues.json").write_text(
        json.dumps(issues_to_json(issues), ensure_ascii=False, indent=1), encoding="utf-8"
    )
    multi = [i for i in issues if len(i.article_ids) > 1]
    cross = [i for i in multi if len(i.langs) > 1]
    print(
        f"{args.date} 호: 기사 {len(articles)}건 → 이슈 {len(issues)}개 (2건 이상 {len(multi)}개, 다국어 {len(cross)}개) "
        f"| 임베딩 {t1 - t0:.1f}초(새로 계산 {computed}건), 군집 {t2 - t1:.1f}초, 임계값 {threshold}"
    )
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    from .cluster import Issue
    from .collect import Article
    from .edit import arrange, choose, edition_to_json
    from .interest import build_interest_table
    from .score import load_previous, score_issues, write_history

    root = Path(args.root)
    cfg, interests = load_config(root), load_interests(root)
    raw = _raw_dir(args)
    edition = date.fromisoformat(args.date)
    articles = {d["id"]: Article.from_dict(d) for d in json.loads((raw / f"{args.date}.json").read_text(encoding="utf-8"))}
    issues = [Issue(**d) for d in json.loads((raw / f"{args.date}.issues.json").read_text(encoding="utf-8"))]
    history_dir = Path(args.data) / "history"
    prev_date, previous = load_previous(history_dir, edition)
    scored = score_issues(issues, articles, cfg, build_interest_table(interests), previous)
    placed, cstats = choose(scored, cfg, interests)
    ed = arrange(placed, cfg, interests, articles)
    out = edition_to_json(ed, args.date, articles, cstats)
    out["stats"]["history_previous"] = prev_date.isoformat() if prev_date else None
    (raw / f"{args.date}.edition.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.write_history:
        placed_ids = {p.scored.issue.id for ps in ed.sections.values() for p in ps}
        write_history(history_dir, edition, scored, placed_ids)
    st = out["stats"]
    print(
        f"{args.date} 호 편집: 실림 {sum(v for k, v in st['by_section'].items() if k != 'compare')}건 {st['by_section']} | 다양성 {st['diversity_slots']}, "
        f"관심 {st['interest_counted']}/{st['interest_cap']}(제외 {st['interest_skipped']}), 연속 보장 {st['continuity_guaranteed']}, "
        f"사진 {st['photos']}, 전날 기록 {st['history_previous']}"
    )
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    """입장 차이(무토큰)를 붙이고, LLM 훅이 켜져 있으면 요약·번역을 붙인다."""
    from .collect import Article
    from .stance import day_prior, stance

    root = Path(args.root)
    cfg, interests = load_config(root), load_interests(root)
    raw = _raw_dir(args)
    edition = json.loads((raw / f"{args.date}.edition.json").read_text(encoding="utf-8"))
    day_articles = [Article.from_dict(d) for d in json.loads((raw / f"{args.date}.json").read_text(encoding="utf-8"))]
    by_id = {a.id: a for a in day_articles}
    prior = day_prior(day_articles)
    items = [it for ps in edition["sections"].values() for it in ps] + edition["compare"]
    for it in items:
        it["stance"] = stance([by_id[a["id"]] for a in it["articles"]], prior)
    llm_note = "꺼짐"
    if cfg.llm.enabled and not args.no_llm:
        from datetime import date as _date

        from .llm import Budget, enrich  # 켜져 있을 때만 불러온다

        budget = Budget(raw / "llm-usage.json", _date.today(), cfg.llm.max_calls_per_day)
        edition = enrich(edition, cfg.llm, interests.foreign_display, raw / f"{args.date}.llm.json", budget)
        llm_note = f"{edition['stats']['llm']['status']} (오늘 {edition['stats']['llm']['calls_today']}회)"
    (raw / f"{args.date}.edition.json").write_text(json.dumps(edition, ensure_ascii=False, indent=1), encoding="utf-8")
    noted = sum(1 for it in items if it["stance"]["note"])
    worded = sum(1 for it in items if it["stance"]["lean_words"] or it["stance"]["country_words"])
    print(f"{args.date} 호 입장 차이: 기사 {len(items)}건 중 쏠림 표시 {noted}, 특징 단어 {worded} | LLM: {llm_note}")
    return 0


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
    p = sub.add_parser("embed", help="지금 채워지는 호의 새 기사만 임베딩해 캐시에 저장 (수집 직후)")
    p.add_argument("--date", help="호 날짜 YYYY-MM-DD (기본: 시간창이 열린 호)")
    p.set_defaults(func=cmd_embed)
    p = sub.add_parser("cluster", help="정제된 기사를 다국어 임베딩으로 이슈별로 묶음")
    p.add_argument("--date", required=True, help="호 날짜 YYYY-MM-DD")
    p.add_argument("--threshold", type=float, help="유사도 임계값 (기본: config.yaml)")
    p.set_defaults(func=cmd_cluster)
    p = sub.add_parser("edit", help="점수 계산과 지면 편집 (data/raw/<호>.edition.json)")
    p.add_argument("--date", required=True, help="호 날짜 YYYY-MM-DD")
    p.add_argument("--write-history", action="store_true", help="연속성 기록(data/history)에 이 호를 저장")
    p.set_defaults(func=cmd_edit)
    p = sub.add_parser("enrich", help="입장 차이(무토큰) + LLM 요약·번역(켜져 있을 때)")
    p.add_argument("--date", required=True, help="호 날짜 YYYY-MM-DD")
    p.add_argument("--no-llm", action="store_true", help="이번 실행만 LLM 훅을 건너뜀")
    p.set_defaults(func=cmd_enrich)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
