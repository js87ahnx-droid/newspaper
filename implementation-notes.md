# 구현 기록 (implementation notes)

계획(project-plan.md)과 다르게 구현했거나 안 하기로 한 것을 이유와 함께 적는다.

## 13차 요청 (S30)

### Deviations
- S30a: 결정 D16("중계 서버는 아무것도 저장하지 않는다")을 좁혔다 — 원문은 여전히 저장하지 않고, 저장소는 관심 학습값 KV 한 칸(PREFS)뿐.
  사용자가 "서버 편집까지 반영"을 골라 기기 밖 저장이 필요해서. test_worker_has_no_storage 를 그에 맞게 바꿈
- S30a: test_worker_has_no_storage 는 S25b 부터 실패하고 있었다(아침 발행 상태를 남기는 console.log 한 줄). 그 한 줄만 허용하도록 고쳐 이번에 통과
- S30a: 계획의 "KV 없음 501" 은 실제 런타임이 아니라 prefs.js 를 가짜 KV 로 직접 불러 시험(런타임 시험은 401·405·no-store 만) — 한 런타임에서 KV 있음·없음을 둘 다 띄우기 번거로워서
- S30c: "기본값으로"에 interests.yaml 원래 키워드도 필요해 Interests 에 base_keywords 를 더함(계획엔 분야 가중치만)
- S30c: 서버 값을 받아 쓰거나 슬라이더를 바꾼 뒤 지면 재배치는 처음 지면(#flow)을 복사해 두고 거기서 다시 배치 — apply() 를 두 번 부르면 앞서 옮긴 기사가 그대로 남아서
- S30c: 예전 "가중치 내보내기"와 그 테스트(test_export_learned_weights)는 지움(요청: 내보내기 없이). "학습 초기화"는 "기본값으로"로 바뀜
