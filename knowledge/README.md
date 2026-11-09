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

## 빌드가 하는 일
- 법 규칙의 단계(S0→S3)를 우선순위 대역으로 바꾸고, 소재마다 테이블 하나로 펼친다(`docs/engine/algorithm.md` 2절).
- 생성 규칙마다 원본 규칙 ID(`source_rule`)와 근거의 조문 위치(`basis[].location`)를 남긴다. 한 원본 규칙이 여러 소재 테이블에 복사되므로, 원본 규칙 하나를 고치면 관련된 생성 규칙이 모두 같이 바뀐다.
- 테이블 버전은 이 폴더 내용의 해시다(`2026.11.0+kb-<해시>`). 결과 요약은 `data/real/conversion_report.md`.

## 내력
- 2026-11-09: 기존 엔진(resource_engine `2f1355a`)의 `rules/`에서 옮겨 왔다. 이름을 바꾼 파일: `rules.yaml` → `law_rules/scope_and_business.yaml`, `rules_s3.yaml` → `law_rules/designated.yaml`, `s4_map.yaml` → `code_map.yaml`. `tools/legacy_overrides.yaml` → `fact_settings.yaml`. 내용은 바꾸지 않았고, 빌드 결과는 옮기기 전 `data/real/`과 같다(머리말·버전 표기 제외).
- 파일 머리말의 주석 일부는 기존 엔진 기준으로 쓰여 있다(예: `re_mcp`, 기존 엔진의 strict 모드). 원본 규칙을 고칠 때 함께 정리한다.
- 앞으로의 계획(검토 기록, 정답 사례표, 개정 반영 흐름)은 `docs/design/rule-review-and-amendment.md`.
