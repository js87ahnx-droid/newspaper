"""검수용 이슈 표본 30개 추출: 큰 이슈 10 + 다국어 이슈 10 + 나머지 2건 이상 이슈 중 무작위 10.

사용: python tools/sample_issues.py data/raw/2026-10-16 [--seed 7] > review.md
출력 표의 각 기사 줄에 사람이 O(같은 사건) / X(잘못 묶임)를 적는다.
"""
from __future__ import annotations

import argparse
import json
import random
import sys


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser()
    p.add_argument("prefix", help="data/raw/<호 날짜> (확장자 없이)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("-n", type=int, default=10, help="층별 표본 수")
    args = p.parse_args()

    arts = {a["id"]: a for a in json.load(open(args.prefix + ".json", encoding="utf-8"))}
    issues = json.load(open(args.prefix + ".issues.json", encoding="utf-8"))
    multi = [i for i in issues if len(i["article_ids"]) > 1]
    rnd = random.Random(args.seed)

    picked: list[tuple[str, dict]] = []
    seen: set[str] = set()

    def take(label, pool, k):
        for i in pool:
            if len([1 for l, _ in picked if l == label]) >= k:
                break
            if i["id"] not in seen:
                seen.add(i["id"])
                picked.append((label, i))

    take("큰 이슈", sorted(multi, key=lambda i: -len(i["article_ids"])), args.n)
    cross = [i for i in multi if len(i["langs"]) > 1]
    rnd.shuffle(cross)
    take("다국어", cross, args.n)
    rest = multi[:]
    rnd.shuffle(rest)
    # 앞 층이 모자라면(다국어 이슈가 적은 날) 무작위 층에서 채워 총 3n 개를 맞춘다
    take("무작위", rest, args.n + (2 * args.n - len(picked)))

    total = sum(len(i["article_ids"]) for _, i in picked)
    print(f"# 이슈 묶기 검수 표본 — {args.prefix}\n")
    print(f"- 이슈 {len(picked)}개, 기사 {total}건. 기사마다 대표 제목과 같은 사건이면 O, 아니면 X\n")
    for n, (label, i) in enumerate(picked, 1):
        print(f"## {n}. [{label}] {i['title']}  (기사 {len(i['article_ids'])}, 응집도 {i['cohesion']})\n")
        for aid in i["article_ids"]:
            a = arts[aid]
            print(f"- [ ] {a['source']} ({a['lang']}): {a['title']}")
        print()


if __name__ == "__main__":
    main()
