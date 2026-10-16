#!/usr/bin/env bash
# 시간창 안에서 여러 번 돌리는 수집: 피드를 읽어 누적하고, 새 기사만 미리 임베딩한다 (발행 때 시간을 줄이려고).
# 사용: bash scripts/collect.sh   (Actions collect.yml 이 부른다. 로컬에서도 같은 방식)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python}"

$PY -m pipeline validate
# 피드가 전부 실패해도(종료 코드 1) 누적분은 남아 있으므로 임베딩은 계속한다
$PY -m pipeline collect || echo "::warning::이번 수집은 피드가 모두 실패했습니다 (누적분으로 계속)"
$PY -m pipeline embed
