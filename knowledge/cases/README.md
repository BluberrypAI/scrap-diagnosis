# 골든 데이터셋 (판정 엔진 테스트 오라클)

판정 엔진과 독립적으로, 적재한 법령(`knowledge/law/`)만으로 만든 정답 세트다.
**판정 규칙을 작성하는 사람·LLM에게 `golden.yaml`, `situations.yaml`, `decision_table.yaml`을 보여 주지 않는다**(데이터 누수 방지).

| 파일 | 단계 | 내용 |
|---|---|---|
| `input_model.yaml` | Step 1 | 입력 변수 21개, 도메인, 동등 분할, 출력 클래스 8개(우선순위), 근거·등급 |
| `decision_table.yaml` | Step 2 (생성) | 판정 게이트 G1~G8, 테스트 요구사항 96개(baseline·MC/DC·경계값·마스킹·메타모픽·열거) |
| `situations.yaml` | Step 4 | TR별 상황 서술(Annotator A) |
| `annotation/` | Step 5 | 가이드라인, 블라인드 입력, Annotator B 라벨, 불일치·판정 조정 기록 |
| `golden.yaml`, `golden.lock` | Step 6 (생성) | 동결본과 SHA-256 |
| `evaluation.yaml` | 평가 (생성) | 커버리지와 뮤테이션 테스팅 결과(`tools/evaluate_golden.py`) |
| `CHANGELOG.md` | - | 동결본 변경 사유 |

```bash
uv run python tools/check_cases.py                   # 근거 참조·도메인·사실값 검사
uv run python tools/build_decision_table.py --check  # 결정 테이블 최신 여부
uv run python tools/annotation_agreement.py score    # 일치도(Cohen's κ)
uv run python tools/build_golden.py --check          # 동결 해시 확인
uv run python tools/evaluate_golden.py               # 커버리지·mutation score
```

등급: A 조문 문언만으로 정해짐 / B 판례·공식 해석으로 뒷받침됨(`external`) / C 우리 해석 결정(2026-11-19~20). 케이스 등급은 쓰인 파티션 중 가장 약한 근거(C > B > A)다. Step 3(2026-11-20~21)에서 법령해석례·부처 해석 70건과 판례 12건을 screening해 support 6건을 골랐고(`external/candidates.yaml`, 판례는 웹 원문 수집 `source.via: web`), v4에서 `discharged=no` 파티션을 B로 올렸다.
`tools/cases_spec.py`는 기대 결과 계산용 명세 오라클이다. 판정 엔진은 이 모듈을 import하지 않는다.
