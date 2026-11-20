# scrap-diagnosis

폐기물 분류 문진 엔진(v2). 사용자의 답으로 폐기물 여부와 분류번호를 판정하고, 확정 결과를 인계 객체(`diagnosis-handoff-v1`)로 서버에 넘긴다.

원칙: **판정은 규칙 엔진만 한다.** 규칙은 조문 단위 근거와 함께 YAML로 두고, 정답 사례(골든셋)로 검증한다. LLM은 아직 쓰지 않는다(말 이해·질문 문장 다듬기는 다음 단계).

- 범위: PP·PE·PET(51-03-01, 51-03-07), 알루미늄 캔(51-29-03). 지정폐기물은 "가능성"까지만 판단한다
- 범위 밖은 "범위 밖 · 지원 예정"으로만 안내한다(후보 코드는 trace에만 남긴다)

## 구조

| 경로 | 내용 |
| --- | --- |
| `knowledge/law/` | 법령 원문(조문 단위 JSON)과 수집 목록. `targets.yaml`(사람이 정함) → `tools/collect_law.py` → `articles/`, `manifest.yaml` |
| `knowledge/cases/` | 골든셋(정답 사례 98건, 동결 해시 `golden.lock`)과 주석·평가 기록 |
| `knowledge/flow/` | 판정 규칙(`10_is_waste`~`70_code`), 사실 카탈로그(`facts.yaml`), 문진 계획(`plan.yaml`), 결과 안내(`outcomes.yaml`), 결정 기록(`decisions.md`), 규칙 형식(`SCHEMA.md`) |
| `app/engine/` | 규칙 실행기(`flow.py`, 3값 논리), 다음 질문 계산기(`planner.py`), 지식 로더(`kb.py`) |
| `app/interview/` | 문진 서비스: 답 검증, 질문 카드·판정 보드·결과 카드·인계 객체 만들기, 회사 정보 기억, 서류(업로드·검수·적용·해제) |
| `app/reading/` | 시험성적서 표 읽기(글자 PDF는 pdfplumber, 스캔본·사진은 Azure Document Intelligence). 기존 엔진에서 복원 |
| `app/api/` | 내부 API `/internal/v1`(인증, 오류 형식) |
| `app/persistence/`, `alembic/` | DB 모델과 마이그레이션(SQLite·PostgreSQL) |
| `tools/` | 법령 수집, 골든셋 빌드·검사, 규칙 비교, 가상 문진 |

API 계약: [docs/api/server-engine-contract.md](docs/api/server-engine-contract.md)

## 실행

```bash
uv sync
uv run uvicorn app.main:app --port 8030      # API 문서 http://localhost:8030/docs
```

- 기본 DB는 `./diagnosis.db`(SQLite, 시작할 때 테이블을 만든다). 운영은 `DATABASE_URL=postgresql+psycopg://…`, `DB_CREATE_ALL=false`로 두고 `uv run alembic upgrade head`로 스키마를 만든다
- `ENGINE_SERVICE_TOKEN`을 비워 두면 개발 모드에서는 토큰 없이 통과한다. `APP_ENV=prod`에서 비어 있으면 모든 요청이 401이다
- scrap-server는 `DIAGNOSIS_ENGINE_URL=http://127.0.0.1:8030`과 같은 `ENGINE_SERVICE_TOKEN`으로 띄운다
- 개발용 PostgreSQL: `docker compose up -d db`(호스트 포트 55432)
- 서류 표 자동 읽기: 글자 있는 PDF는 기본으로 엔진 안에서 읽는다. 스캔본 PDF·사진은 `ALLOW_DOCUMENT_OCR=true`와 `AZURE_DOCINTEL_*` 키를 넣었을 때만 Azure로 읽는다(그 전에는 사진 업로드가 415). 켜지 않으면 비용이 들지 않는다

## 검증

```bash
uv run python -m pytest -q                          # 단위·API 테스트(골든셋 98건을 API로 끝까지 문진하는 테스트 포함)
uv run ruff check . && uv run ruff format --check .
uv run python tools/check_cases.py                  # 골든셋 근거·값 검사
uv run python tools/build_decision_table.py --check # 결정표 생성물이 최신인지
uv run python tools/build_golden.py --check         # 골든셋 동결 해시
uv run python tools/compare_flows.py score knowledge/flow   # 판정 규칙 채점(98/98)
uv run python tools/simulate_interview.py           # 문진 계획: 결론 정확도·질문 수
uv run alembic check                                # 모델과 마이그레이션이 같은지
TEST_DATABASE_URL=postgresql+psycopg://wd:wd@localhost:55432/postgres uv run python -m pytest -q
```

Windows에서 `uv run pytest`가 "trampoline" 오류로 실패하면 `uv run python -m pytest`로 실행한다.

## 아직 없는 것

- 말(자유 문장) 이해: 지금은 대화에 남기고 버튼 답을 안내한다
- 판례·행정심판 외부 정답(API 승인 후 `tools/collect_external_cases.py` 재실행)
