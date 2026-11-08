# waste-diagnosis

폐기물 분류 코드 판정 엔진과 문진 에이전트. 원칙은 **LLM은 제안하고, 규칙 엔진이 판정하고, 서버가 검증한다.**

현재 진행: M1(엔진 코어), M2(질문 선택·라우터·시뮬레이터) 완료. 규칙 데이터는 `SAMPLE-` 코드와 `(샘플)` 조문만 들어 있으며 실제 법령이 아니다.

## 실행
```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run python scripts/simulate.py data/scenarios/
```

## 구조
- `app/domain/` — `Fact`(append-only, 유효 사실 선택), `NumRange`(구간 응답)
- `app/rules/loader.py` — YAML 로드·정적 검증(`includes`, `applies_when`, 시행일 필터)
- `app/rules/evaluator.py` — 3값 평가기. md 6절 + `blocking_facts`(확정을 실제로 막는 미확인 사실)
- `app/rules/selector.py` — 정보가치 질문 선택. 묶음 질문, prior, gain 0 질문 제외
- `app/rules/conflicts.py` — 진술과 문서의 충돌, 후보 0개 설명
- `app/agent/router.py` — 결정적 분기 라우터. `run_engine`은 한 턴의 LLM 없는 부분
- `app/agent/simulation.py`, `scripts/simulate.py` — 스크립트 답변 시뮬레이터
- `data/` — `facts_catalog.yaml`, `question_groups.yaml`, `codes.yaml`, `rules/{sample,common}/`, `scenarios/`

## 기존 엔진 대비 질문을 줄이는 장치
1. 질문 풀은 확정을 실제로 막는 사실(`blocking_facts`)로만 만든다.
2. 결과를 바꿀 수 없는 질문(정보가치 0)은 고르지 않는다.
3. 묶음 질문 '모두 해당 없음'을 한 번 누르면 위험 사실 여러 개를 한꺼번에 CLAIMED=false로 넣는다.
4. 문진 전에 알고 있는 사실(기업 프로필, 건 메모, 자유 진술)은 다시 묻지 않는다.
