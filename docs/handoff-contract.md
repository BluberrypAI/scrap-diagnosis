# 문진 → 경로추천 AI 인계 계약 (diagnosis-handoff-v1)

문진에서 사용자가 **확정**을 누르면 아래 객체(`handoff`)를 만든다. 경로추천 AI는 이 객체만 보고 다음 행동을 정한다. 확정 응답(`POST /cases/{id}/confirm`), 건 상세(`GET /cases/{id}`), 저장된 판정 버전(Verdict)에 같은 객체를 싣는다.

## 원칙
- 확정할 수 있는 것은 **규칙 엔진이 결론을 낸 경우**다.
  - 분류번호가 정해진 경우(`result_type = WASTE_CODE`)
  - 분류번호 없이 결론이 난 경우(`result_type = NO_CODE`): 폐기물 아님, 적용 제외 등
- 결론이 나지 않은 경우는 확정할 수 없고 `NEEDS_INFO`로 남는다. 질문 상한 도달, 증빙 거부, 적용 규칙 없음이 여기에 해당한다.
- 확정한 건의 상태는 두 종류 모두 `CODE_CONFIRMED`다(경로 미확정). 경로추천 AI는 `result_type`과 `route_guidance.action`으로 분기한다.
- 모든 판정은 기존 엔진 규칙을 옮긴 것이라 `review: UNVERIFIED`다. 경로추천 AI는 사용자 안내에 이 사실을 표시한다.

## 형식
```json
{
  "contract": "diagnosis-handoff-v1",
  "case_id": "…",
  "verdict_version": 1,
  "result_type": "WASTE_CODE | NO_CODE",
  "waste_code": "51-03-01 | null",
  "waste_name": "폐합성수지류(…) | null",
  "category": "GENERAL | DESIGNATED | OUT_OF_SCOPE | NEEDS_INTERPRETATION | null",
  "outcome": "NOT_WASTE | CIRCULAR_RESOURCE | EXCLUDED | HOUSEHOLD | INTERPRETATION_NEEDED | NO_GENERAL_CODE | CODE_NEEDS_TEST | NO_MIXTURE_RULE | null",
  "route_guidance": {
    "action": "RECOMMEND_ROUTE | NO_ROUTE_NEEDED | REFER_OTHER_LAW | REFER_MUNICIPALITY | REFER_AUTHORITY | NEEDS_TEST | MANUAL_CLASSIFICATION",
    "summary": "경로추천 AI가 사용자에게 안내할 한 줄 요지(한국어)",
    "notes": ["처리 시 참고할 점"]
  },
  "facts": {"material": {"value": "pp", "status": "CLAIMED", "source_type": "UTTERANCE"}},
  "evidence": [{"fact": "ph", "document_id": "…"}],
  "basis": [{"id": "B1", "type": "LAW", "ref": "…", "excerpt": "…"}],
  "review": "UNVERIFIED",
  "timestamps": {
    "diagnosis_started_at": "2026-11-08T09:12:03+09:00",
    "confirmed_at": "2026-11-08T09:20:41+09:00",
    "as_of": "2026-11-08"
  },
  "kb": {"kb_version": "…", "table_id": "pp", "table_version": "2026.11.0+re-2f1355a"}
}
```

규칙
- `facts`에는 값이 알려진 유효 사실만 넣는다. 각 사실에는 출처를 함께 넣는다(UTTERANCE / DOCUMENT / PROFILE / SCREENING / DERIVED).
- 시각은 모두 ISO 8601이며 시간대를 붙인다. 저장은 UTC로 하고, 인계 객체에는 Asia/Seoul로 낸다.
- `as_of`(법 기준일)는 **대화를 시작한 날짜(Asia/Seoul)**다. reopen해도 바꾸지 않는다.

## result_type / outcome → route_guidance.action
| result_type | outcome | action | 경로추천 AI가 할 일 |
|---|---|---|---|
| WASTE_CODE | null | RECOMMEND_ROUTE | 분류번호·구분(지정/일반)으로 처리 경로·업체 추천 |
| NO_CODE | NOT_WASTE | NO_ROUTE_NEEDED | 폐기물 처리 경로가 필요 없음을 안내한다. 나중에 내보내게 되면 다시 문진하도록 안내한다 |
| NO_CODE | CIRCULAR_RESOURCE | NO_ROUTE_NEEDED | 순환자원 인정 범위 안에서 거래하도록 안내하고, 인정서 유효성 확인을 권고한다 |
| NO_CODE | EXCLUDED | REFER_OTHER_LAW | 적용되는 다른 법(사실 `law_exclusion` 값)과 담당 기관을 안내한다 |
| NO_CODE | HOUSEHOLD | REFER_MUNICIPALITY | 관할 지자체 생활폐기물 배출 방법을 안내한다 |
| NO_CODE | INTERPRETATION_NEEDED | REFER_AUTHORITY | 관할 기관 질의를 안내한다. 근거 질의회신(`basis`)을 첨부한다 |
| NO_CODE | CODE_NEEDS_TEST | NEEDS_TEST | 분석기관에서 필요한 시험을 받도록 안내한다. 결과가 나오면 문진을 재개하게 한다 |
| NO_CODE | NO_GENERAL_CODE | MANUAL_CLASSIFICATION | 지정폐기물은 아님을 알리고, 일반폐기물 세부 번호는 담당자 확인이 필요하다고 안내한다 |
| NO_CODE | NO_MIXTURE_RULE | MANUAL_CLASSIFICATION | 소재별로 분리해 따로 문진하거나, 관할 기관에 확인하도록 안내한다 |

이 표는 데이터 파일(`data/<kb>/outcome_guidance.yaml`)로 두고, 코드에 하드코딩하지 않는다.
