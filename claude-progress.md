# 진행 기록 — ○월 ○일자 뉴스

## 2026-10-15

### Planner 완료
- 지시서 v0.2 검토, `project-plan.md` 작성 (스프린트 12개, 스프린트별 acceptance criteria)
- 현황: 작업 폴더 비어 있음 / gh 계정 `js87ahnx-droid` 로그인됨 / Python 3.14.3, Node 24
- 지시서와 현실이 어긋나는 4가지를 계획서 0장에 정리 (무료 요금제 비공개 Pages 불가, cron 지연, 일부 매체 RSS 부재, 다양성·관심 상한 슬롯 정의)

### 사용자 결정 (2026-10-15)
- D2·D8 접근 제한: 공개 Pages + 지면 암호화(StatiCrypt)
- D3 피드백: 기기 내 학습 + 내보내기
- D4 LLM 훅: 켬 (월 상한 미정 — "$ 기준" 질문에 답변함)
- D5 발행: 06:10 KST
- D9 전자판: 없음

- D1: GitHub `js87ahnx-droid` 사용
- D4 보완: API 과금 대신 Claude 구독(Claude Code CLI + `CLAUDE_CODE_OAUTH_TOKEN`), 사용량 상한 하루 10건
- 로컬 개발은 Python 3.11 (3.14는 일부 패키지 휠이 없을 수 있어 Actions와 같은 3.11로 맞춤)
- D6·D7은 S3(소스 실측·API 조사) 이후 확인

### S1 저장소 골격 — 완료
- `newspaper/` 를 별도 git 저장소로 생성 (상위 문서 백업 저장소와 분리), Python 3.11 venv
- `config.yaml` · `sources.yaml`(후보 24곳, 피드 비어 있음·전부 꺼짐) · `interests.yaml`(자리표시값), `pipeline/settings.py`(pydantic 엄격 검증), `python -m pipeline validate`
- Evaluator 결과
  - [x] `python -m pipeline --help` 동작
  - [x] 세 YAML 검증 통과, 잘못된 값 18종(음수 가중치, 비율 합 초과, 시각 형식, 시간대, 섹션 중복·순서, 오타 키, 피드 없는 enabled, 성향 라벨 오류 등) 모두 파일명·항목·이유와 함께 거부 — pytest 21건 통과
  - [x] `git check-ignore` 로 `.env`, `.env.local`, `secrets.json`, `data/bodies/x.txt` 차단 확인
  - 평가 중 발견 1건 수정: Windows 콘솔(cp949)에서 한글 오류 메시지가 깨짐 → stdout/stderr UTF-8 고정 후 재확인

### 다음
- S2 관심사 인터뷰 6문항 → `interests.yaml`
