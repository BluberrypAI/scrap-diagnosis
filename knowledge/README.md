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
| `materials.yaml` | 소재 98개: 폐기물 종류, 소재가 정하는 사실, 별표 4 번호 후보 | 아니오 |
| `code_map.yaml` | 법 규칙 → 별표 4 번호 범위 대응표(사람이 옮긴 것) | 예(대응) |
| `annex4_codes.yaml` | 시행규칙 별표 4 번호표 | 법령 원문 |
| `sources.yaml` | 근거 문서: 법령명, 법령 번호, 시행일 | - |
| `facts.yaml` | 사실(질문 항목) 정의: 라벨, 값, 질문 문장, 확인 방법 | 아니오 |
| `fact_settings.yaml` | 빌드 때 더하는 사실 설정: 사전확률, 법적 중요도, 묶음 질문, 증빙 문서 종류 | 아니오 |
| `outcome_guidance.yaml` | 결론 → 경로추천 안내(`docs/handoff-contract.md`). 빌드가 그대로 복사 | 아니오 |
| `reviews.yaml` | 전문가 검토 기록. `tools/review_kit.py import`로만 더한다 | - |

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
- 앞으로의 계획(정답 사례표, 개정 반영 흐름)은 `docs/design/rule-review-and-amendment.md`.
