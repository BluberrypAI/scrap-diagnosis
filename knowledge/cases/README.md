# 골든 데이터셋 (판정 엔진 테스트 오라클)

판정 엔진과 독립적으로, 적재한 법령(`knowledge/law/`)만으로 만든 정답 세트다.
**판정 규칙을 작성하는 사람·LLM에게 `golden.yaml`, `situations.yaml`, `decision_table.yaml`을 보여 주지 않는다**(데이터 누수 방지).

| 파일 | 단계 | 내용 |
|---|---|---|
| `input_model.yaml` | Step 1 | 입력 변수 21개, 도메인, 동등 분할, 출력 클래스 8개(우선순위), 근거·등급 |
| `decision_table.yaml` | Step 2 (생성) | 판정 게이트 G1~G8, 테스트 요구사항 76개(baseline·MC/DC·경계값·마스킹·메타모픽) |
| `situations.yaml` | Step 4 | TR별 상황 서술(Annotator A) |
| `annotation/` | Step 5 | 가이드라인, 블라인드 입력, Annotator B 라벨, 불일치·판정 조정 기록 |
| `golden.yaml`, `golden.lock` | Step 6 (생성) | 동결본과 SHA-256 |
| `CHANGELOG.md` | - | 동결본 변경 사유 |

```bash
uv run python tools/check_cases.py                   # 근거 참조·도메인·사실값 검사
uv run python tools/build_decision_table.py --check  # 결정 테이블 최신 여부
uv run python tools/annotation_agreement.py score    # 일치도(Cohen's κ)
uv run python tools/build_golden.py --check          # 동결 해시 확인
```

등급: A 조문 문언만으로 정해짐 / C 우리 해석 결정(2026-11-19~20). B(판례·공식 해석 외부 레이블)는 아직 없다(Step 3 미실시).
`tools/cases_spec.py`는 기대 결과 계산용 명세 오라클이다. 판정 엔진은 이 모듈을 import하지 않는다.
