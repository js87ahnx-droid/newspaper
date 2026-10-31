#!/usr/bin/env bash
# 누적분(data/raw) 캐시를 못 불러온 실행이 빈 결과를 새 누적분으로 저장하지 않게 (S35a).
# 2026-10-31 10:44 수집이 "Egress is over the account limit" 로 불러오기에 실패하고도 빈 상태로 이어 가
# 끝에 저장했고, 다음 실행들이 모두 그 빈 쪽을 이어받아 그날 호 edition.json 과 아침 수집분이 사라졌다.
#
# 사용: bash scripts/raw_cache_guard.sh <불러온 키 (못 불러왔으면 빈 문자열)> [strict]
#   불러왔으면 save=true. 못 불러왔는데 저장된 누적분이 있으면(= 불러오기 실패) save=false,
#   strict=1 이면 실패로 끝낸다(수집은 저장 못 할 수집을 할 까닭이 없다). 누적분이 하나도 없으면 처음부터 쌓는다(save=true).
#   gh 로 확인을 못 하면 불러오기 실패로 본다 (덮어쓰는 쪽이 더 비싸다).
set -euo pipefail
MATCHED="${1:-}"
STRICT="${2:-0}"
out() { echo "save=$1" >> "${GITHUB_OUTPUT:-/dev/null}"; }

if [ -n "$MATCHED" ]; then
  echo "누적분 불러옴: $MATCHED"; out true; exit 0
fi
n=$(gh cache list --key raw- --limit 1 --json key -q 'length' 2>/dev/null || echo "?")
if [ "$n" = "0" ]; then
  echo "저장된 누적분이 없음 — 처음부터 쌓는다"; out true; exit 0
fi
echo "::error::누적분 캐시를 불러오지 못함 (저장된 누적분은 있음: $n) — 이번 실행은 누적분을 저장하지 않는다"
out false
if [ "$STRICT" = "1" ]; then exit 1; fi
exit 0
