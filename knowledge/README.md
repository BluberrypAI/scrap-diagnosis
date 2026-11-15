# 규칙 원본 (knowledge/)

엔진이 쓰는 규칙의 **원본**이다. 엔진은 이 폴더를 직접 읽지 않고, `tools/build_kb.py`가 이 폴더로 만든 `data/real/`을 읽는다. 규칙을 고칠 때는 여기를 고치고 다시 빌드한다. `data/real/`은 손으로 고치지 않는다(CI와 테스트가 막는다).

```bash
uv run python tools/build_kb.py            # knowledge/ → data/real/
uv run python tools/build_kb.py --check    # data/real/이 최신인지 확인
uv run python tools/legacy_regression.py   # 기존 엔진 판정표와 비교(바뀐 수치는 이유를 보고)
```

## 파일

| 파일 | 내용 | 법 판단을 담나 |
|---|---|---|
| `law_rules/scope_and_business.yaml` | 법 규칙 28개: 폐기물 해당 여부(S0), 법 적용 제외(S1), 사업장폐기물 여부(S2) | 예 |
| `law_rules/designated.yaml` | 법 규칙 122개: 지정폐기물 기준(S3). 규칙마다 쉬운 설명(`plain`), 인용문(`quote`), 조문 위치(`location`) | 예 |
| `materials.yaml` | 소재 102개: 폐기물 종류, 소재가 정하는 사실, 별표 4 번호 후보 | 아니오 |
| `code_map.yaml` | 법 규칙 → 별표 4 번호 범위 대응표(사람이 옮긴 것). 법의 예외는 여기 두지 않는다 | 예(대응) |
| `definitions.yaml` | 공통 정의: 여러 규칙이 함께 쓰는 이름 붙은 조건(규칙이 `{ref: 이름}`으로 씀) | 예 |
| `annex4_codes.yaml` | 시행규칙 별표 4 번호표 | 법령 원문 |
| `sources.yaml` | 근거 문서: 법령명, 법령 번호, 시행일 | - |
| `facts.yaml` | 사실(질문 항목) 정의: 라벨, 값, 질문 문장, 확인 방법 | 아니오 |
| `fact_settings.yaml` | 빌드 때 더하는 사실 설정: 사전확률, 법적 중요도, 묶음 질문, 증빙 문서 종류 | 아니오 |
| `outcome_guidance.yaml` | 결론 → 경로추천 안내(`docs/handoff-contract.md`). 빌드가 그대로 복사 | 아니오 |
| `glossary.yaml` | 용어집: 전문용어의 쉬운 설명. 질문 카드 `terms`와 검토 카드 "용어 풀이"에 붙는다. 판정에는 쓰지 않음. 빌드가 그대로 복사 | 아니오 |
| `question_guide.yaml` | 질문 안내: 문진 질문·선택지마다 무엇을·왜 묻는지, 확인 방법, 해당 예시, FAQ, 출처. 질문 카드의 배경·왜 묻나요·이렇게 확인하세요(`background`·`reason`·`how_to_check`·`if_unknown`, 묶음은 `groups`)와 보충 설명("어떤 게 해당돼요?")에 씀. 모든 질문·선택지에 있어야 함(`tests/test_question_guide.py`). 판정에는 쓰지 않음 | 아니오 |
| `skills/interviewer.md` | (초안) 문진 진행 AI의 지침·체크리스트. 판정에는 쓰지 않음(docs/design/agent-skill-harness.md). 사용자 검토 후 확정 | 아니오 |
| `reviews.yaml` | 전문가 검토 기록. `tools/review_kit.py import`로만 더한다 | - |

## 원본 형식 (2판)

법 규칙(`law_rules/*.yaml`)의 항목:

| 필드 | 뜻 |
|---|---|
| `id`, `stage`, `concludes` | 규칙 ID, 단계(S0~S3), 원본 결론(예: DESIGNATED, NOT_WASTE, EXCLUDED) |
| `when` | 조건식(아래) |
| `exceptions` | 예외: `[{unless_any: [규칙 ID 접두어…], location, quote, plain}]`. 그 규칙들이 성립하면 이 규칙은 적용하지 않는다. 같은 소재 테이블에 있는 규칙만 따진다 |
| `conclusion` | 결론 방식: 없음/`auto`이면 근거가 법령일 때 원본 결론 그대로, 아니면 해석 필요. `interpret`이면 근거와 관계없이 해석 필요로 끝낸다 |
| `source`, `location`, `quote`, `supporting` | 근거 문서·조문 위치·인용문·보조 근거 |
| `item`, `plain`, `gaps` | 제목, 쉬운 설명, 확인하지 못한 점 |
| `review` | 기존 엔진에서 온 값. 빌드는 쓰지 않는다(검토 상태는 `reviews.yaml`) |

조건식(`when`, 정의의 `when`):

```yaml
when:                                   # 목록 = 모두 만족(AND). 기존 형식 그대로
- {fact: waste_kind, op: eq, value: sludge_process}
- {ref: SLUDGE_STATE}                   # 공통 정의(definitions.yaml)를 가져다 쓴다
- any:                                  # 하나 이상(OR)
  - {fact: leach_pb, op: gte, value: 3}
  - {fact: leach_cd, op: gte, value: 0.3}
- not: {fact: dust_from_incinerator, op: eq, value: true}   # 아님(NOT)
- {fact: circular_resource_recognized, op: eq, value: true, min_status: EVIDENCED}
```

- 단순 조건: `{fact, op, value}`. `op`는 `eq ne in not_in lt lte gt gte exists`.
- `min_status`(선택): 이 조건이 참이 되려면 필요한 증빙 수준. `EVIDENCED`면 서류·성적서로 확인한 값만 참으로 본다. 적지 않으면 시험 수치(`facts.yaml`의 `cost: TEST`)만 `EVIDENCED`, 나머지는 말로 답해도 된다.
- 기준 미만·해당 없음처럼 조건을 **거짓**으로 만드는 답은 증빙 수준과 관계없이 말로도 받는다(엔진의 3값 평가).
  - 예외: **확인대상 폐기물**(시행규칙 제17조의2제1항, `fact_settings.yaml`의 `confirm_target`)의 소재 테이블에서는
    빌드가 시험 수치 조건에 `falsify_min_status: EVIDENCED`를 붙인다. 이런 조건은 '기준 미만'도 성적서 값으로만 거짓이 되고,
    엔진은 그 수치를 말로 묻지 않고 바로 성적서를 요청한다. PCB 수치는 `exclude_facts`로 뺐다(모든 소재에 걸린 조건이라).
- 소재의 `presets`(소재가 정하는 사실)는 빌드할 때 조건을 미리 참·거짓으로 접는다.

공통 정의(`definitions.yaml`): `이름: {title, when, source, location, quote, plain}`. 검토 단위 `def:<이름>`이 생기고, 정의를 쓰는 생성 규칙은 그 단위에도 기댄다(정의가 바뀌면 그 규칙들의 검토가 함께 풀린다).

## 질문 전략 (`fact_settings.yaml`)

법 규칙에는 법 문언의 조건만 둔다. "무엇을 먼저, 어떻게 물을지"는 사실 설정에 둔다.
- `prior`, `ask_cost`, `legal_priority`, `none_value`, 묶음 질문(`groups`): 질문 순서와 묶음
- **대리 질문 `implies`:** 답하기 어려운 사실(예: PCB 함량)을 답하기 쉬운 질문(예: "PCB를 쓴 기기·절연유와 관련이 있나요?")으로 묻고, 그 답이 대상 사실의 값을 추정하게 한다.
  ```yaml
  pcb_possible:
    implies:
      false: {pcb_mg_l: {hi: 2}, pcb_leach_mg_l: {hi: 0.003}}   # "관련 없음" → 기준 미만으로 봄
  ```
  - 엔진은 대상 사실이 확정을 막으면 대신 대리 질문을 묻는다. "예"·"모름"이면 대상 사실을 직접 묻는다(성적서 요청으로 이어질 수 있음).
  - 추정은 저장하지 않고 평가 때마다 적용한다(출처 DERIVED). 대상 사실에 말이나 서류로 값이 있으면 그 값이 이긴다. 대리 질문 답을 철회하면 추정도 사라진다.
  - 추정의 법적 타당성(예: "관련 없음"을 기준 미만으로 볼 수 있는가)은 전문가 검토 대상이다.
- **보수 관계 `complement`:** 같은 시험이 함께 내는 두 수치의 합이 일정하면 한쪽 값으로 다른 쪽을 계산한다(예: `sludge_water_pct: complement: {fact: sludge_solids_pct, total: 100}`). 양방향이고, 계산값은 원래 값의 상태를 잇는다. 둘 다 모르면 이 설정을 둔 사실을 먼저 묻는다.

## 목록에 없는 폐기물 (`unlisted_other`)

소재 목록 어디에도 맞지 않는 폐기물(예: 폐콘크리트, 음식물류폐기물)은 소재 분류 "목록에 없는 폐기물"의 소재 `unlisted_other`로 진행한다.
- 공통 단계(폐기물 여부·법 적용 범위·사업장)와 공통 오염 확인(기름·PCB·유해화학물질·잔류물)은 다른 소재와 똑같이 묻는다.
- 일반 번호는 별표 4 사업장일반폐기물 **계열**(`general_group`, 예: 51-22 폐콘크리트)을 먼저 고르고, 그 계열 안의 번호(`annex4_code`)를 고른다. 빌드는 `materials.yaml`의 `general_by_family: true`를 보고 별표 4 일반 번호 전체를 후보로 펼친다.
- 추출 AI는 사용자 말이 분명하면 계열까지 뽑는다("폐콘크리트예요" → 51-22). 애매하면 계열 질문을 한다.
- **한계:** 계열별 지정 기준(예: 형광등의 수은, 소각재의 용출)은 적용하지 않는다. 공통 오염 확인만 하므로, 유해물질이 의심되면 시험성적서와 관할 기관 확인이 필요하다. 자주 나오는 폐기물은 이 경로에 두지 말고 소재로 추가한다.

## 용어집 (`glossary.yaml`)

질문과 카드에 나오는 전문용어(용출, 고형물함량, 지정폐기물 등)의 쉬운 설명이다. LLM이 아니라 사람이 쓰고 전문가가 검토한다.
- 항목: `plain`(쉬운 설명, 필수), `example`, `aliases`(같은 뜻의 다른 표기, 예: 함수율 → 수분함량), `source`
- 질문 글(제목·도움말·선택지)에 용어나 별칭이 나오면 API 질문 카드의 `terms`에 설명이 붙는다. 긴 표기부터 찾는다("폐유기용제"는 유기용제로 잡고 "폐유"는 따로 잡지 않음).
- 설명은 일반적인 뜻이다. 판정 기준은 규칙이 정한다.

## 빌드가 하는 일
- 법 규칙의 단계(S0→S3)를 우선순위 대역으로 바꾸고, 소재마다 테이블 하나로 펼친다(`docs/engine/algorithm.md` 2절).
- 생성 규칙마다 원본 규칙 ID(`source_rule`)와 근거의 조문 위치(`basis[].location`)를 남긴다. 한 원본 규칙이 여러 소재 테이블에 복사되므로, 원본 규칙 하나를 고치면 관련된 생성 규칙이 모두 같이 바뀐다.
- 테이블 버전은 이 폴더 내용의 해시다(`2026.11.0+kb-<해시>`). 결과 요약은 `data/real/conversion_report.md`.

## 검토하는 방법

검토 단위는 249개다: 법 규칙 150개(규칙 ID), 소재 98개(`material:<소재>`), 번호 대응표 1개(`code_map`).

1. **카드 만들기(개발 담당):** `uv run python tools/review_kit.py export` → `build/review/검토카드.html`, `build/review/검토표.csv`. 두 파일을 전문가에게 보낸다(`build/`는 git에 올리지 않는다).
   - 카드에는 쉬운 설명, 조건을 문장으로 쓴 것, 결론과 별표 4 번호 범위, 근거 조문과 인용문, 확인하지 못한 점, 영향(생성 규칙 수, 소재 테이블 수)이 있다. 영향이 큰 것부터 나온다.
   - 카드는 엔진의 실제 동작을 함께 보여 준다: **엔진 결론**(예: 질의회신 근거 규칙은 원본 결론과 달리 "해석 필요"), 번호 대응표의 **제외** 규칙, 확인 방식("시험성적서 필요" / "말로 답해도 됨"), 소재에서 **실제로 나오는 번호**와 쓰이지 않는 후보, 그리고 **엔진 미사용** 규칙(그 종류를 고르는 소재가 없음).
2. **검토(전문가):** 카드를 읽고 검토표의 같은 행에 검토 결과(맞음 / 고쳐야 함 / 틀림), 검토자, 검토일, 의견을 적는다. "고쳐야 함"·"틀림"은 의견이 필요하다. 내용 해시는 고치지 않는다.
3. **반영(개발 담당):**
   ```bash
   uv run python tools/review_kit.py import 검토표.csv --dry-run   # 먼저 검사만
   uv run python tools/review_kit.py import 검토표.csv
   uv run python tools/build_kb.py                                 # 생성 규칙의 review가 바뀐다
   ```
   검토표에 오류가 하나라도 있으면(없는 단위, 바뀐 내용 해시, 빈 검토자, 날짜 형식) 아무것도 반영하지 않는다.
4. **"고쳐야 함"·"틀림"** 은 의견을 보고 원본 규칙을 고친다. 고치면 내용 해시가 바뀌어 그 단위는 "검토 후 바뀜"이 되고, 다시 검토받는다.

엔진에 미치는 영향:
- 생성 규칙의 `review`는 그 규칙이 기대는 검토 단위(`review_units`)가 **모두 "맞음"이고 검토 뒤 바뀌지 않았을 때만** `VERIFIED`, 아니면 `UNVERIFIED`다. 예: 지정폐기물 규칙은 법 규칙 + 번호 대응표 + 그 소재가 모두 맞음이어야 한다.
- 판정 결과·인계 객체의 `review`가 이 값을 따른다. 화면은 `UNVERIFIED`이면 "검토 전 규칙 · 참고용", `VERIFIED`이면 "전문가 검토 완료"를 보여 준다.
- 원본 법 규칙 파일의 `review` 필드는 기존 엔진에서 온 것이고 빌드는 쓰지 않는다. 검토 상태는 `reviews.yaml`이 정한다.
- 검토 기록이 바뀌면 규칙 버전도 바뀐다(진행 중인 건은 `KB_CHANGED` → rebase). 영향받는 건만 막는 것은 다음 단계(P5)다.

## 내력
- 2026-11-09: 기존 엔진(resource_engine `2f1355a`)의 `rules/`에서 옮겨 왔다. 이름을 바꾼 파일: `rules.yaml` → `law_rules/scope_and_business.yaml`, `rules_s3.yaml` → `law_rules/designated.yaml`, `s4_map.yaml` → `code_map.yaml`. `tools/legacy_overrides.yaml` → `fact_settings.yaml`. 내용은 바꾸지 않았고, 빌드 결과는 옮기기 전 `data/real/`과 같다(머리말·버전 표기 제외).
- 파일 머리말의 주석 일부는 기존 엔진 기준으로 쓰여 있다(예: `re_mcp`, 기존 엔진의 strict 모드). 원본 규칙을 고칠 때 함께 정리한다.
- 2026-11-09: 검토 기록(`reviews.yaml`)과 검토 도구(`tools/review_kit.py`)를 더했다(설계 P2).
- 2026-11-09: 원본 형식 2판. 조건 중첩(`any`·`not`), 공통 정의(`definitions.yaml`), 규칙 안 예외(`exceptions`, `code_map.yaml`의 `designated_exclusions`에서 옮김), 조건별 `min_status`, `conclusion`. 빌드 결과는 이전과 같다.
- 앞으로의 계획(정답 사례표, 개정 반영 흐름)은 `docs/design/rule-review-and-amendment.md`.

## 별표 4의3 조회표

`recycling_types.yaml`은 현재 지원하는 일반 플라스틱·금속 14개 번호의 재활용 유형표다.
2026-11-12 시행 법령에서 제공하는 PDF의 9·10·20쪽과 27쪽 비고를 대조했다.
별표 자체 개정일은 2025-12-30이다. 확인한 법 버전보다 이전 기준일의 문진에는 소급 적용하지 않는다.
분류 규칙 SOURCE_FILES와 분리하여 자체 버전·내용 해시를 쓴다. 조회표 변경만으로 기존 분류 테이블의 검토 버전을 바꾸지 않는다.
빌드는 이 파일을 그대로 복사하며 --check로 원본과 생성물 일치를 검사한다.
원문 비고 3·4에 따라 같은 R-10이 두 분석 그룹에 있으면 중복 제거하지 않는다.
