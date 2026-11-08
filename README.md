# waste-diagnosis

폐기물 분류 코드 판정 엔진과 문진 에이전트. 원칙은 **LLM은 제안하고, 규칙 엔진이 판정하고, 서버가 검증한다.**

현재 진행: M1(엔진 코어), M2(질문 선택·라우터·시뮬레이터), M2R(기존 엔진 실제 규칙 변환), M3(LLM 추출·응답·guard), M4(API·영속화·문서·confirm/reopen·Trace) 완료. 결과: `docs/m3-report.md`, `docs/m4-report.md`.

## 실행
```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run python scripts/simulate.py data/sample/scenarios/
uv run python scripts/simulate.py --data data/real data/real/scenarios/
```

골든 평가(LLM 설정은 `.env`, 이름은 `.env.example`):
```bash
uv run python scripts/eval.py --mock-extractor   # LLM 없이
uv run python scripts/eval.py                    # 실제 Azure
uv run python scripts/eval_extractor.py          # 기존 질의회신 60건 추출 평가
```

기존 엔진 규칙을 다시 변환할 때(기존 저장소: `C:/Users/zxc20/re_project/resource_engine`):
```bash
uv run python tools/convert_legacy.py --regression
uv run python tools/legacy_regression.py --write
```

## API 서버 (M4)
```bash
uv run uvicorn app.main:app --port 8030      # 문서: http://localhost:8030/docs
uv run alembic upgrade head                  # 운영 스키마(DATABASE_URL). 개발은 시작 시 create_all
uv run alembic -x url=sqlite:///var/other.db upgrade head
```
- 설정(`.env`/환경변수): `DATABASE_URL`(기본 `sqlite:///<저장소>/var/app.db`), `KB_DIR`(기본 `data/real`),
  `DB_CREATE_ALL`(기본 true), `LLM_PROVIDER`(off면 LLM 없이 선택지 버튼·라벨만 받음)
- 기업 격리: 임시로 `X-Company-Id` 헤더(TODO: 실제 인증). 다른 기업의 건은 404.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/companies` | (개발용) 기업 생성. `profile.facts`는 문진 시작 때 PROFILE 사실 |
| GET / PUT | `/companies/me`, `/companies/me/profile` | 내 기업 조회·프로필 수정 |
| POST | `/cases` | 건 생성(memo·quantity·unit·period) → 첫 턴 응답 |
| GET | `/cases?status=` | 상태별 목록 |
| GET | `/cases/{id}` | 건 상세 + 현재 판정·판정 버전·마지막 턴·문서 |
| POST | `/cases/{id}/diagnosis/messages` | `{text}` 또는 `{quick_reply:{key,kind,value}}` → md 10절 응답 |
| POST | `/cases/{id}/documents` | multipart `file`(.txt/.md/.pdf), 선택 `facts`(JSON) → EVIDENCED → 재평가 |
| POST | `/cases/{id}/confirm` | 서버 재평가 후 판정 버전 고정 → `CODE_CONFIRMED` (불가 시 409) |
| POST | `/cases/{id}/reopen` | `CODE_CONFIRMED`에서만. 이전 판정은 버전으로 보존 |
| GET | `/cases/{id}/trace` | Decision Trace 전체(사실 이력·턴·확정 기록) |

## 데이터
- `data/sample/` — 엔진 검증용 SAMPLE 규칙. `SAMPLE-` 코드와 `(샘플)` 조문만 있다.
- `data/real/` — 기존 엔진에서 변환한 실제 규칙(자동 생성, 직접 고치지 않음)
  - 소재별 PRIORITY 테이블 97개, 사실 카탈로그, 묶음 질문, 별표 4 코드표, 출처
  - `conversion_report.md`: 우선순위 대역, 변환하지 않은 기능, 의도한 차이
  - `regression/`: 기존 판정표 4281행과의 비교 데이터·결과
  - 모든 규칙은 `review: UNVERIFIED`다. 법률 검토 전에는 판정을 참고용으로만 쓴다.
- `tools/legacy_overrides.yaml` — 변환할 때 사람이 정하는 값(사전확률, 묶음 질문, 증빙 문서 이름)

## 구조
- `app/domain/` — `Fact`(append-only, 유효 사실 선택), `NumRange`(구간 응답)
- `app/rules/loader.py` — YAML 로드·정적 검증(`includes`, `applies_when`, 시행일 필터)
- `app/rules/evaluator.py` — 3값 평가기. md 6절 + `blocking_facts`(확정을 실제로 막는 미확인 사실)
- `app/rules/selector.py` — 정보가치 질문 선택. 묶음 질문, prior, gain 0 질문 제외, 번호 선택은 마지막
- `app/rules/conflicts.py` — 진술과 문서의 충돌, 후보 0개 설명
- `app/agent/router.py` — 결정적 분기 라우터. `run_engine`은 한 턴의 LLM 없는 부분(자동 채움 포함)
- `app/agent/simulation.py`, `scripts/simulate.py` — 스크립트 답변 시뮬레이터
- `app/agent/{llm_client,extractor,guard,responder,templates,orchestrator}.py` — LLM 제안·검증, 한 턴 처리
- `app/domain/{verdict,trace}.py` — 응답 스키마(md 10절), Decision Trace
- `tools/convert_legacy.py`, `tools/legacy_regression.py` — 기존 규칙 변환과 회귀 비교
- `app/main.py`, `app/api/` — FastAPI 앱 팩토리, 라우터, 서비스(상태 전이), 문서 텍스트 추출
- `app/persistence/` — SQLAlchemy 모델·저장소(요청마다 DB 행에서 문진 세션 복원), `alembic/` 마이그레이션

## 기존 엔진 대비 질문을 줄이는 장치
1. 질문 풀은 확정을 실제로 막는 사실(`blocking_facts`)로만 만든다.
2. 결과를 바꿀 수 없는 질문(정보가치 0)은 고르지 않는다.
3. 묶음 질문 '모두 해당 없음'을 한 번 누르면 위험 사실 여러 개를 한꺼번에 CLAIMED=false로 넣는다.
4. 문진 전에 알고 있는 사실(기업 프로필, 건 메모, 자유 진술)은 다시 묻지 않는다.
5. 시험 항목 하나를 '모름'이라 하면 같은 성적서의 다른 항목은 묻지 않고 성적서를 한 번에 요청한다.
6. 별표 4 번호는 다른 사실이 모두 풀린 뒤에만 묻고, 후보가 하나면 자동으로 정한다.

실제 규칙 기준 PP 고체·오염 없음: 기존 10문항 → 4문항(소재·상태를 미리 알면 2문항).
