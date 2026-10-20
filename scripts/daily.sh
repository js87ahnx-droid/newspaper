#!/usr/bin/env bash
# 아침 발행: 마지막 수집 → 정제 → 이슈 묶기 → 점수·편집 → 입장 차이·논평·사설(+LLM) → 지면 → 암호화 → 검사.
# 사용: NEWS_PASSWORD=… bash scripts/daily.sh
#   EDITION_DATE=YYYY-MM-DD   호 날짜 (기본: 가장 최근에 끝난 시간창)
#   SKIP_IF_PUBLISHED=1       이미 발행된 호면 아무것도 안 하고 끝냄 (예비 실행용)
#   RENDER_ONLY=1             지면 HTML 만 다시 (수집·편집·LLM 없이 data/raw/<호>.edition.json 으로)
#   CLAUDE_CODE_OAUTH_TOKEN   있으면 LLM 훅 사용 (구독), 없으면 무토큰
# 암호화(NEWS_PASSWORD)가 없거나 실패하면 중간에 멈춘다 — 평문 지면이 커밋·공개되지 않게.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python}"
STATICRYPT="npx --yes staticrypt@3.5.4"

DATE="${EDITION_DATE:-$($PY -c 'from datetime import datetime, timezone
from pipeline.prepare import current_edition
from pipeline.settings import load_config
print(current_edition(datetime.now(timezone.utc), load_config()))')}"
echo "호 날짜: $DATE"

if [ "${SKIP_IF_PUBLISHED:-0}" = "1" ] && [ -f "docs/archive/$DATE/index.html" ]; then
  echo "이미 발행된 호입니다 — 건너뜀"
  exit 0
fi
if [ -z "${NEWS_PASSWORD:-}" ]; then
  echo "::error::NEWS_PASSWORD 가 없습니다. 암호화 없이 공개할 수 없어 중단합니다."
  exit 1
fi

# LLM 토큰 정리·확인은 맨 앞에서 (머리기사 묶기·이슈 분석 둘 다 LLM 을 쓴다)
LLM_FLAG=""
# 붙여 넣을 때 섞인 공백·줄바꿈을 지운다 (터미널 줄 접힘 복사). 값은 찍지 않고 길이·접두어만 남긴다
if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
  _tok_raw="$CLAUDE_CODE_OAUTH_TOKEN"
  export CLAUDE_CODE_OAUTH_TOKEN="$(printf '%s' "$_tok_raw" | tr -d '[:space:]')"
  _pre="다름"; case "$CLAUDE_CODE_OAUTH_TOKEN" in sk-ant-oat01-*) _pre="sk-ant-oat01" ;; esac
  echo "LLM 토큰: 길이 ${#CLAUDE_CODE_OAUTH_TOKEN}, 접두어 ${_pre}, 공백 제거 $(( ${#_tok_raw} - ${#CLAUDE_CODE_OAUTH_TOKEN} ))자"
  unset _tok_raw _pre
fi
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] || ! command -v claude >/dev/null 2>&1; then
  LLM_FLAG="--no-llm"
  echo "LLM 훅: 토큰 또는 claude CLI 없음 — 무토큰으로 발행"
fi

$PY -m pipeline validate
if [ "${RENDER_ONLY:-0}" = "1" ]; then
  # 지면만 다시 그리기 (S26e): 수집·편집·AI 호출 없이, 이 호를 만들 때 남긴 data/raw/<호>.edition.json 으로 HTML 만 새로
  if [ ! -f "data/raw/$DATE.edition.json" ]; then
    echo "::error::data/raw/$DATE.edition.json 이 없습니다 (누적분 캐시에 없음) — render_only 없이 다시 발행하세요"
    exit 1
  fi
  echo "지면만 다시 그리기: $DATE"
  $PY -m pipeline publish --date "$DATE" --site docs
else
$PY -m pipeline collect || echo "::warning::마지막 수집에서 피드가 모두 실패했습니다 (누적분으로 발행)"
$PY -m pipeline prepare --date "$DATE"
$PY -m pipeline embed --date "$DATE"
$PY -m pipeline cluster --date "$DATE"
$PY -m pipeline headlines --date "$DATE" $LLM_FLAG || echo "::warning::매체 머리기사를 받지 못했습니다 (머리기사 가중 없이 편집)"
$PY -m pipeline edit --date "$DATE" --write-history $LLM_FLAG   # 분야 분류도 LLM (S21b)

$PY -m pipeline enrich --date "$DATE" $LLM_FLAG
$PY -m pipeline publish --date "$DATE" --site docs
fi

# 암호화: 오늘 호·이 호의 보관본·지난 호 목록
while IFS= read -r f || [ -n "$f" ]; do   # 마지막 줄에 줄바꿈이 없어도 읽는다
  [ -z "$f" ] && continue
  STATICRYPT_PASSWORD="$NEWS_PASSWORD" $STATICRYPT "$f" -d "$(dirname "$f")" --short --remember 30 -c .staticrypt.json \
    --template-title "일자 뉴스" \
    --template-instructions "개인 열람용 지면입니다." \
    --template-button "열기" \
    --template-placeholder "비밀번호" \
    --template-remember "이 기기에서 30일 동안 기억" \
    --template-error "비밀번호가 다릅니다" \
    --template-color-primary "#1d1b18" \
    --template-color-secondary "#f6f1e7" >/dev/null
done < docs/.to-encrypt
rm -f docs/.to-encrypt

# 검사: 모든 지면 HTML 이 암호화됐고 기사 제목이 평문으로 남지 않았는지
$PY tools/verify_site.py docs "data/raw/$DATE.edition.json"
echo "발행 준비 완료: $DATE"
