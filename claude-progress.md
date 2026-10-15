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

### S2 관심사 인터뷰 — 완료
- 답: 관심 = 경제·증시, 반도체·AI, 정치·안보, 국제 (같은 우선순위) / 키워드 = 삼성전자, SK하이닉스, 엔비디아, TSMC, HBM, 반도체 수출 / 덜 볼 분야 = 연예·스포츠, 사건·사고, 생활·문화 / 하루 40건 / 입장 비교 = 외교·안보, 경제 정책, 국내 정치, 테크·규제 / 해외 기사: 영어는 제목 원문 + 한국어 요약, 그 외 언어는 제목 번역
- 6번 답에 맞춰 스키마 변경: `foreign_title` → `foreign_display{english, other}`. LLM 상한 단위를 "이슈 수" → "하루 호출 수(10회)"로 바꿔 여러 건을 묶어 처리
- 분야 id 목록(10개)·비교 유형 id(4개)를 코드에 고정하고 모르는 값은 거부, 관심·덜 볼 분야 중복 거부
- `pipeline/interest.py`: 모든 분야에 가중치를 매긴 표 + 키워드 가산(대소문자 무시, 한 번만)
- Evaluator 결과
  - [x] 6문항 답 모두 `interests.yaml` 에 반영 (위 목록과 파일 대조)
  - [x] 관심도 가중치 표 단위 테스트 4건 통과 (선택 1.0 / 덜 볼 0.2 / 나머지 0.5, 0인 분야 없음, 키워드 가산)
  - 전체 pytest 28건 통과, `validate` 통과
- 참고: 후보 해외 매체(NHK World, Japan Times, SCMP, Global Times, Al Jazeera 등)는 대부분 영어판이라 "그 외 언어 번역" 규칙은 일본어·중국어판 피드를 추가할 때만 쓰인다 → S3에서 사용자에게 확인

### S3 소스 실측·API 조사 — 사용자 확인 대기
- 조사표: `docs-internal/source-audit.md`
- 공식 피드 동작 16곳(피드 54개) → `sources.yaml` enabled. Google 뉴스 대체만 가능 9곳(중앙, 매경, KBS 국문, CNN, AP, Reuters, Nikkei Asia, NHK World, Global Times) → enabled: false
- 발견: WSJ·NHK·CNN 의 예전 피드 주소는 200을 돌려주지만 갱신이 멈춰 있음 → 최신 기사 시각으로 판정해야 함 (check_sources 의 48시간 기준)
- 발견: 한겨레 RSS에 발행 시각 없음 → 기사 페이지 메타로 보완 (S4)
- 발견: 피드 16개가 11시간 시간창을 다 덮지 못함 → 시간창 안 여러 번 수집·누적으로 설계 변경 (계획서 S4·S10 반영)
- 공식 API: 무료로 본문 가능한 곳은 Guardian 하나, NYT는 초록·첫 문단
- Evaluator 결과
  - [x] 매체별 판정·근거 표 작성
  - [x] 동작 피드만 enabled — `tools/check_sources.py` 켜진 피드 54개 실패 0
  - [x] D6·D7 사용자 답 (2026-10-15): Google 뉴스 대체 9곳 모두 사용 / 성향 라벨에 '관영' 추가(Global Times) / 본문 API는 나중에(S11에서 재결정, 그때까지 원문 링크 + 읽기 모드)
  - 반영 후 재점검: 켜진 매체 25곳·피드 63개 실패 0, validate·pytest 28건 통과
  - 관찰: Google 뉴스 `when:1d` 결과에도 오래된 기사가 섞임(NHK World 폭 9131h) → S4 시간창 필터가 반드시 걸러야 함
- S3 완료

### S4 수집·정제 — 완료
- `python -m pipeline collect`: 켜진 피드 전부 병렬 수집(동시 8, 재시도 2회·4xx는 즉시 포기) → `data/raw/store.jsonl` 에 누적(정규화 URL 기준 1건, 3일 지난 것 정리), 실행마다 `collect-log.jsonl` 에 실패 내역 기록. 시각 없는 매체(한겨레)는 기사 페이지 `<head>` 메타만 읽어 보완
- `python -m pipeline prepare [--date]`: 호 날짜의 시간창 [전날 19:00, 당일 06:00) KST 로 거르고, 같은 매체 같은 제목 병합, sources.yaml 을 다시 적용(라벨·가중치·언어 제한·매체 끄기), 리드 300자 상한 → `data/raw/<호>.json`, `data/run-report.json`
- Evaluator 결과
  - [x] 피드 고의 실패(DNS 오류·HTML 응답) 시 나머지로 결과가 나오고, 실패 매체·사유가 로그와 run-report.json 에 남음 (테스트)
  - [x] 시간창 경계 18:59:59 / 19:00:00 / 05:59:59 / 06:00:00 KST — RFC822 +0900, GMT, -0400, ISO Z, 시간대 없음 입력까지 10가지 모두 정확 (테스트)
  - [x] 추적 파라미터·www·m.·끝 슬래시·http 차이가 같은 기사로 합쳐짐 (테스트 + 실데이터 id 중복 0)
  - [x] 실제 수집: 10/16호(19:00~21:30 부분) 400건, 10/15호 471건 — 독립 스크립트로 다시 판정해 시간창 밖 0건
  - [x] 두 번 수집해도 같은 기사는 한 번만 (테스트 + 실데이터: 2회차 새 기사 11건만 추가)
  - [x] 한겨레 시각 보완: 1회차 107건 성공·8건 실패(연결 시간 초과) → 2회차 재시도로 8건 모두 확인. 끝내 실패하면 버리고 `dropped_no_date` 로 기록 (테스트)
  - pytest 70건 통과
- 평가에서 찾아 고친 결함 3건
  1. 조선일보 RSS에 일본어판 기사가 섞여 들어옴(41건) → 매체별 `langs` 제한 추가, 발행 때 sources.yaml 을 다시 적용
  2. 리드 상한이 말줄임표 때문에 301자 → 상한 안에서 자르도록 수정, 발행 때 한 번 더 적용
  3. 한겨레 페이지 시각 확인에 재시도가 없었음 → 재시도 붙이고 실패분은 다음 수집 때 다시 확인
- 남은 확인: 시간창 전체(19:00~06:00)를 여러 번 수집한 하루치는 S10 자동 수집이 돌아간 뒤 검증 (지금은 부분 시간창 2개로 검증)
- 관찰: Google 뉴스 대체 매체는 2.5시간 동안 2~9건으로 적음 → 여러 번 수집하면 늘어나는지 S10 이후 확인

### 사진 요구 반영 (사용자 요청 2026-10-15: "사진도 적절히, 다 넣을 필요는 없음")
- 계획서에 사진 원칙 추가: RSS가 주는 대표 이미지만, 저장소·배포물에 복사하지 않고 원 주소로 표시, 1면 톱·1면 1건·섹션 머리기사에만, 사진 때문에 순위를 바꾸지 않음
- 수집 단계에 `image` 추출 추가(media:content·media:thumbnail·이미지 enclosure·리드 속 img, 가장 큰 것), 테스트 7건
- 실측(10/16호 428건): 사진 있는 기사 248건(58%). 제공: 조선·연합·SBS·한겨레·동아·Guardian·BBC·Fox·NYT·WSJ·SCMP·Japan Times / 미제공: 경향·한경·NHK·Al Jazeera·Google 뉴스 대체 9곳
- 참고: BBC 이미지는 240px 폭이라 큰 자리에는 흐릿할 수 있음 → S8에서 확인
