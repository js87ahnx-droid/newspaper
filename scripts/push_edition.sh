#!/usr/bin/env bash
# 발행 결과 커밋·푸시 (S39). 11/5: 대기하던 #222 가 #221 이 올린 호를 다시 만들고 push 에서 충돌했다.
# 올리기 전에 원격 최신을 받아, 같은 호가 이미 있으면 덮어쓰지 않고 정상 종료한다. force(일부러 다시 만들기)는 그대로 올리되
# 그 사이 다른 실행이 같은 파일을 고쳤으면(충돌) 덮어쓰지 않고 실패로 끝낸다.
#
# 사용: bash scripts/push_edition.sh <호 날짜> [force: 1]
# 결과(GITHUB_OUTPUT result=): pushed | nochange | skipped(같은 호가 이미 있음) | failed
set -uo pipefail
DATE="$1"
FORCE="${2:-0}"
BRANCH="${PUSH_BRANCH:-main}"
WAIT="${PUSH_WAIT:-5}"
ORIGIN="refs/remotes/origin/$BRANCH"

out() { echo "result=$1" >> "${GITHUB_OUTPUT:-/dev/null}"; }
summary() { echo "$1" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"; }
fail() {   # 원인, 설명
  echo "::error title=발행 push 실패 ($1)::발행 결과를 push 하지 못함 — $2"
  summary "**push 실패 ($1) — $DATE 호가 저장소에 없음**: $2"
  out failed
  exit 1
}
classify() {   # git 오류 문구 → 원인
  case "$1" in
    *403*|*[Pp]ermission*|*denied*|*"not allowed"*|*protected*|*"Authentication failed"*) echo "권한" ;;
    *rejected*|*non-fast-forward*|*"fetch first"*|*"stale info"*) echo "충돌" ;;
    *) echo "기타" ;;
  esac
}

git config user.name "newspaper-bot"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
# 주간 관심 학습값(S30b), 편집 자동 조정·리뷰(S38c, 메모 없음), 경제 해설 보관(S33a — 지난 호 지면은 14일 뒤 지워도 해설은 남긴다)
for p in docs data/history .staticrypt.json data/interests-learned.json data/editing-learned.json data/reviews data/econ; do
  if [ -e "$p" ]; then git add "$p"; fi
done
if git diff --cached --quiet; then echo "바뀐 것 없음"; out nochange; exit 0; fi
detail=$(git commit -q -m "발행: $DATE" 2>&1) || fail "기타" "커밋 실패: $(echo "$detail" | tail -n 1)"

reason="기타"; detail=""
for i in 1 2 3; do
  if [ "$i" -gt 1 ]; then sleep $(( (i - 1) * WAIT )); fi
  if ! detail=$(git fetch -q origin "+refs/heads/$BRANCH:$ORIGIN" 2>&1); then
    reason=$(classify "$detail"); detail="원격을 받지 못함: $(echo "$detail" | tail -n 1)"
    if [ "$reason" = "권한" ]; then break; fi
    continue
  fi
  if [ "$FORCE" != "1" ] && git cat-file -e "$ORIGIN:docs/archive/$DATE/index.html" 2>/dev/null; then
    echo "::notice title=발행 건너뜀::$DATE 호가 이미 저장소에 있음 (다른 실행이 먼저 올림) — 덮어쓰지 않고 끝냄"
    summary "**$DATE 호는 다른 실행이 먼저 올림 — 건너뜀**"
    out skipped
    exit 0
  fi
  if ! git rebase -q --autostash "$ORIGIN" >/dev/null 2>&1; then
    files=$(git diff --name-only --diff-filter=U | head -n 3 | tr '\n' ' ')
    git rebase --abort >/dev/null 2>&1
    reason="충돌"; detail="다른 커밋과 같은 파일을 고침: ${files:-파일 모름}"
    continue
  fi
  if detail=$(git push -q origin "HEAD:refs/heads/$BRANCH" 2>&1); then out pushed; exit 0; fi
  reason=$(classify "$detail"); detail=$(echo "$detail" | tail -n 1)
  if [ "$reason" = "권한" ]; then break; fi   # 다시 해도 안 된다
done
fail "$reason" "$detail"
