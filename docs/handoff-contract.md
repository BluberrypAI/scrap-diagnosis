# 문진 → 경로추천 AI 인계 계약 (diagnosis-handoff-v1)

문진에서 사용자가 **확정**을 누르면 아래 객체(`handoff`)를 만든다. 경로추천 AI는 이 객체만 보고 다음 행동을 정한다. 확정 응답(`POST /cases/{id}/confirm`), 건 상세(`GET /cases/{id}`), 저장된 판정 버전(Verdict)에 같은 객체를 싣는다.

## 원칙
- 확정할 수 있는 것은 **규칙 엔진이 결론을 낸 경우**다.
  - 분류번호가 정해진 경우(`result_type = WASTE_CODE`)
  - 분류번호 없이 결론이 난 경우(`result_type = NO_CODE`): 폐기물 아님, 적용 제외 등
- 결론이 나지 않은 경우는 확정할 수 없고 `NEEDS_INFO`로 남는다. 질문 상한 도달, 증빙 거부, 적용 규칙 없음이 여기에 해당한다.
- 확정한 건의 상태는 두 종류 모두 `CODE_CONFIRMED`다(경로 미확정). 경로추천 AI는 `result_type`과 `route_guidance.action`으로 분기한다.
- `review`는 판정에 쓴 규칙의 전문가 검토 상태다: `UNVERIFIED`(검토 전) 또는 `VERIFIED`(검토 완료). 지금은 검토된 규칙이 없어 모든 판정이 `UNVERIFIED`다. 경로추천 AI는 `UNVERIFIED`이면 사용자 안내에 "검토 전 규칙에 따른 참고용 결과"임을 표시한다.

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
  "outcome": "NOT_WASTE | CIRCULAR_RESOURCE | EXCLUDED | HOUSEHOLD | INTERPRETATION_NEEDED | NO_GENERAL_CODE | CODE_NEEDS_TEST | NO_MIXTURE_RULE | DESIGNATED_CODE_NEEDED | null",
  "route_guidance": {
    "action": "RECOMMEND_ROUTE | NO_ROUTE_NEEDED | REFER_OTHER_LAW | REFER_MUNICIPALITY | REFER_AUTHORITY | NEEDS_TEST | MANUAL_CLASSIFICATION",
    "summary": "경로추천 AI가 사용자에게 안내할 한 줄 요지(한국어)",
    "notes": ["처리 시 참고할 점"]
  },
  "facts": {"material": {"value": "pp", "status": "CLAIMED", "source_type": "UTTERANCE"}},
  "evidence": [{"fact": "ph", "document_id": "…"}],
  "basis": [{"id": "B1", "type": "LAW", "ref": "…", "excerpt": "…"}],
  "review": "UNVERIFIED | VERIFIED",
  "timestamps": {
    "diagnosis_started_at": "2026-11-08T09:12:03+09:00",
    "confirmed_at": "2026-11-08T09:20:41+09:00",
    "as_of": "2026-11-08"
  },
  "kb": {"kb_version": "…", "table_id": "pp", "table_version": "2026.11.0+re-2f1355a"},
  "inputs": {"company_profile_version": "p7 | null", "confirmed_profile_keys": ["emission_facility"]},
  "assumptions": ["'PCB 사용 기기·절연유 관련' 답을 근거로 PCB 용출 농도·PCB 함량(액체)은 시험 없이 기준 미만으로 추정했습니다. …"],
  "designated": null
}
```

규칙
- `facts`에는 값이 알려진 유효 사실만 넣는다. 각 사실에는 출처를 함께 넣는다(UTTERANCE / DOCUMENT / PROFILE / PROFILE_CONFIRMED / SCREENING / DERIVED).
- 시각은 모두 ISO 8601이며 시간대를 붙인다. 저장은 UTC로 하고, 인계 객체에는 Asia/Seoul로 낸다.
- `as_of`(법 기준일)는 **대화를 시작한 날짜(Asia/Seoul)**다. reopen해도 바꾸지 않는다.

- `inputs`(추가 필드, 기존 필드는 그대로): 서버가 보낸 기업 정보 입력의 요약이다. `company_profile_version`은 서버가 건 생성·문진 답변에 보낸 기업 정보 버전(없으면 null), `confirmed_profile_keys`는 서버가 사용자 확인을 거쳐 보낸 값(`source_type = PROFILE_CONFIRMED`) 중 유효한 사실 키다. 판정 버전(Verdict)에도 같은 `company_profile_version`이 남는다. 이 필드가 없는 이전 객체는 `inputs`가 없다.
- `facts[].source_type`에 `PROFILE_CONFIRMED`가 더해졌다(서버가 확인한 기업 정보).
- `assumptions`에는 사용자가 추측으로 답한 값("아마 ~일걸")의 안내도 들어간다(2026-11-11).
- `assumptions`(추가 필드, 없으면 `[]`): 시험·서류가 아니라 사용자 답(대리 질문)에서 추정한 사실의 안내 문장이다. 경로추천 AI는 이 목록이 비어 있지 않으면 처리 업체 안내 때 "시험으로 확인하지 않은 항목"으로 함께 알린다. 같은 사실은 `facts`에 `source_type: DERIVED`로도 있다.
- `assumptions`(추가 필드, 없으면 `[]`): 시험·서류가 아니라 사용자 답(대리 질문)에서 추정한 사실의 안내 문장이다. 같은 대리 질문에서 나온 추정은 한 문장으로 합친다(2026-11-10). 경로추천 AI는 이 목록이 비어 있지 않으면 처리 업체 안내 때 "시험으로 확인하지 않은 항목"으로 함께 알린다. 같은 사실은 `facts`에 `source_type: DERIVED`로도 있다.
- `designated`(추가 필드, 지정폐기물이 아니면 `null`): `category == "DESIGNATED"`일 때 `{reason, warning, next_actions[]}`. `reason`은 지정폐기물이 된 조건을 사용자 값과 기준으로 쓴 한 문장(못 만들면 null), `warning`은 "지정폐기물 처리 허가를 받은 업체에만 맡길 수 있다"는 고정 문장, `next_actions[]`는 `{id, text, source_id, source_title, source_ref, form}`(id: licensed_only·plan_confirm·storage·recheck, 결론이 `DESIGNATED_CODE_NEEDED`일 때만 code_check가 더해진다. `source_ref`는 근거 안의 조항 위치(예: 제18조의2) 또는 null, `form`은 `form12` 또는 null. 문장은 결정된 분류번호 계열(앞 2자리)에 따라 달라진다. 번호가 없으면 기본 문장). 경로추천 AI는 지정폐기물이면 처리 허가를 받은 업체만 추천한다. 화면의 `ui.result.designated`와 같은 내용이다.

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
| NO_CODE | DESIGNATED_CODE_NEEDED | MANUAL_CLASSIFICATION | 지정폐기물임은 정해졌고 세부 분류번호만 미정(번호 질문에 '모름'). 일반 재활용 경로를 추천하지 않고 지정폐기물 처리 허가 업체에만 맡기도록, 번호는 이전 신고서·인계서나 관할 기관에서 확인하도록 안내한다. `category`는 `DESIGNATED`, `code`는 null, `designated`가 채워진다 |

이 표는 데이터 파일(`data/<kb>/outcome_guidance.yaml`)로 두고, 코드에 하드코딩하지 않는다.

## 구현 메모
계약 필드는 바꾸지 않았다. 구현하면서 정한 세부 사항이다.
- 저장: `verdicts.handoff`(JSON). `result_type`·`outcome`은 판정 버전 열로도 둔다. 마이그레이션 `0002`.
- `GET /cases/{id}`의 `handoff`는 현재(대체되지 않은) 확정 판정의 것이다. reopen 뒤 다시 확정할 때까지는 null이고,
  이전 버전의 인계 객체는 `verdicts[].handoff`에 남는다.
- `waste_name`은 코드 없는 결론이면 null이다. `category`는 규칙의 값을 그대로 낸다(예: 폐기물 아님은 `OUT_OF_SCOPE`).
- `facts`: 값이 있는 유효 사실(CLAIMED·EVIDENCED)만. 값은 저장 형식 그대로다(구간 응답은 `{lo, lo_inc, hi, hi_inc}`).
  출처 SCREENING은 아직 없다(묶음 질문 답은 UTTERANCE로 들어온다).
- `evidence`: 유효 사실 중 출처가 DOCUMENT인 것. `document_id`는 업로드한 문서 id.
- `basis`: 확정 규칙(`rule_ids[0]`)의 근거. id는 응답 `verdict.rationale`과 같은 B1, B2 …
- `review`: 확정 규칙의 review 값(없으면 `UNVERIFIED`). 값은 `UNVERIFIED` | `VERIFIED` 두 가지다. 빌드(`tools/build_kb.py`)가 `knowledge/reviews.yaml`의 검토 기록으로 정한다. 생성 규칙이 기대는 검토 단위(법 규칙, 소재, 번호 대응표)가 모두 "맞음"이고 검토 뒤 내용이 바뀌지 않았을 때만 `VERIFIED`다(`knowledge/README.md`).
- `timestamps`: 초 단위 ISO 8601, `+09:00`. 한국은 일광절약시간이 없어 고정 오프셋을 쓴다.
- `route_guidance`: `data/<kb>/outcome_guidance.yaml`(표 전체, real·sample 같은 내용). 계약 표의 행이나 규칙에 쓰인
  outcome의 항목이 하나라도 없으면 KB 로드(서버 시작)가 실패한다. action·outcome은 계약의 값만 받는다.
- confirm의 `expected_code`: 코드 없는 결론이면 outcome(`NOT_WASTE` 또는 `@NOT_WASTE`)과 비교한다. 분류번호를 보내면 409.


## 재활용 유형 인계 (2026-11-16)

확정 인계 객체의 `recycling`에는 별표 4의3에서 조회한 유형이 들어간다.
분류를 결정하는 기능이나 시설 허가 판정이 아니다. 현재 일반 플라스틱·금속 14개 번호만 대조했다.

- `status`: `table_listed`(표 등재), `not_applicable`(일반 경로 대상 아님), `not_covered`(자료 범위 밖), `out_of_date`(법 기준일 불일치).
- `types.free / analysis / unmarked`: 사전 분석 해당 없음 / 분석·확인 필요 / 불명. R-10이 두 그룹에 있으면 모두 보존한다.
- `source`: 원문 URL·시행일·별표 개정일·확인일·원문 SHA-256. `pages`, `notes`, 별도 자료 `version/checksum`도 전달한다.
- `case_id`, `verdict_version`, `waste_code`, `as_of`로 판정과 묶는다. `facility_permit_verified`는 항상 false.

`GET /internal/v1/cases/{id}`의 최상위 `recycling`은 현재 판정에 대한 보충 조회다.
이전 확정 건도 소유권 검사 후 조회하되 저장된 handoff·Verdict·Trace는 수정하지 않는다.
최상위 보충 조회가 있으면 서버는 번호·버전·기준일을 대조한 뒤 사용한다.
B의 실제 산출물은 A와 같다고 가정하지 않는다. 서버는 후속 후보 검토에 A의 번호·R유형을 자동 재사용하지 않는다.
