# AGENTS.md

Re:Source AI 조직의 **폐기물 문진 엔진(scrap-diagnosis, v2)**. 모든 AI 코딩 에이전트(Claude Code, Codex 등)의 공통 진입점이다.
사용자의 답으로 폐기물 여부와 분류번호를 판정하고, 확정 결과를 인계 객체(`diagnosis-handoff-v1`)로 서버에 넘긴다. 로그인·회원·화면·업체 추천은 다른 레포 담당이므로 여기서 구현하지 않는다.

원칙: **판정은 규칙 엔진만 한다.** 규칙은 조문 단위 근거와 함께 YAML로 두고, 골든셋으로 검증한다. LLM은 말 이해·질문 문장 작성만 맡고(다음 단계), 그 출력도 검증한 사실만 엔진에 넣는다.

범위(2026-11-19 결정): PP·PE·PET(51-03-01, 51-03-07), 알루미늄 캔(51-29-03). 지정폐기물은 "가능성"까지만. 범위 밖은 "범위 밖 · 지원 예정"으로만 안내한다.

## 1. 문서 지도 (작업 전에 필요한 것만 읽음)

| 문서 | 언제 읽음 |
| --- | --- |
| [README.md](README.md) | 실행·검증 명령, 구조 |
| [docs/api/server-engine-contract.md](docs/api/server-engine-contract.md) | 서버가 부르는 API(`/internal/v1`), 턴 응답·인계 객체·재활용 유형을 바꿀 때 |
| [knowledge/flow/SCHEMA.md](knowledge/flow/SCHEMA.md) | 판정 규칙 형식과 평가 의미론(3값 논리, 첫 참 규칙, 막힘) |
| [knowledge/flow/decisions.md](knowledge/flow/decisions.md) | 해석 결정(D1~). 규칙 내용을 바꾸기 전에 |
| [knowledge/cases/README.md](knowledge/cases/README.md), [CHANGELOG.md](knowledge/cases/CHANGELOG.md) | 골든셋을 만들거나 고칠 때 |
| [knowledge/law/targets.yaml](knowledge/law/targets.yaml) | 법령 수집 대상을 바꿀 때 |
| [docs/design/test-report-table-extraction.md](docs/design/test-report-table-extraction.md) | 성적서 표 읽기(`app/reading/`)를 고칠 때(기존 엔진 문서, 복원) |
| 팀 공통 규칙(조직 `.github`의 CONTRIBUTING.md) | 브랜치·커밋·PR, 다른 레포와의 경계·API 형식을 바꿀 때 |

## 2. 공통 규칙

1. **분류 판정을 LLM에 맡기지 않는다.** 판정은 `knowledge/flow/*.yaml` 규칙과 `app/engine/flow.py`만 한다. 확인되지 않은 값은 추정해 채우지 않고 '모름' 또는 아직 묻지 않음(UNASKED)으로 둔다
2. **기존 엔진(v1)을 근거로 쓰지 않는다.** 참고했으면 커밋·문서에 "기존 엔진 참조"라고 적는다. 계약 모양을 맞추는 것은 괜찮다
3. **법령은 API로 받는다.** 조문을 손으로 옮기지 않는다. 대상은 `knowledge/law/targets.yaml`(사람이 정함), 수집은 `tools/collect_law.py`, 결과 `articles/`·`manifest.yaml`은 손으로 고치지 않는다. 인증키(`LAW_API_OC`)는 `.env`에만 둔다
4. **규칙마다 근거(basis: 조문 단위 + 인용문)를 붙인다.** 근거가 없으면 규칙을 만들지 말고 `decisions.md`에 해석 결정으로 남기거나 "해석 필요"로 멈춘다
5. **골든셋은 동결한다.** `knowledge/cases/golden.yaml`은 `tools/build_golden.py`로만 만들고 `golden.lock` 해시로 고정한다. 판정 규칙에 맞춰 골든셋을 고치지 않는다(반대 방향만). 바꿀 때는 버전을 올리고 `CHANGELOG.md`에 이유를 쓴다
6. **문진 계획·결과 안내는 사람이 정한다.** 질문 순서·문장은 `plan.yaml`, 결과 문장·인계 행동은 `outcomes.yaml`. 문장은 판정에 쓰지 않는다
7. **API 형식**: 필드·엔드포인트 추가는 자유. 서버·화면이 쓰는 필드의 삭제·이름 변경·타입 변경은 하지 않는다. 필요하면 멈추고 사용자에게 확인한다. 바꾸면 계약 문서를 같이 고친다
8. **서류 값은 검수를 거쳐야 판정에 들어간다.** 업로드·자동 읽기 값은 `UNVERIFIED` 후보이고, 서버 검수(`values/apply`) 뒤에만 `EVIDENCED` 사실이 된다. `source: document` 사실은 버튼 답으로 받지 않는다. 실제 Azure 문서 인식은 비용이 들어 기본 꺼짐(`ALLOW_DOCUMENT_OCR`)이고, 테스트는 가짜 클라이언트로 한다
9. **DB 스키마를 바꾸면 Alembic 마이그레이션을 같이 만든다**(`alembic check`가 통과해야 함). SQLite와 PostgreSQL 모두에서 테스트한다. 사실 기록은 append-only, 확정된 판정·Trace는 고치거나 지우지 않는다(기업 데이터 삭제 경로만 예외)
10. 비밀값은 코드·커밋·로그에 쓰지 않는다. 로컬은 `.env`(git 제외), 변수 이름은 `.env.example`에 값 없이 둔다. `.env` 값을 출력하지 않는다
11. 사용자에게 보이는 문서와 응답은 한국어로 쓴다. 코드 식별자와 커밋 메시지 제목은 영어로 쓴다(본문은 한국어 가능)
12. develop·main에 직접 커밋하지 않는다. 작업 브랜치(`feat/…`, `fix/…` 등)에서 커밋하고, push·PR·병합은 사용자가 요청할 때만 한다

## 3. 구조

| 경로 | 내용 |
| --- | --- |
| `knowledge/law/` | 법령 수집 대상·조문 단위 원문·manifest(원본 해시, 재조회 식별자) |
| `knowledge/cases/` | 골든셋(입력 모델, 결정표, 상황 서술, 이중 주석, 동결본, 평가 기록) |
| `knowledge/flow/` | 판정 규칙 7단계, 사실 카탈로그, 문진 계획, 결과 안내, 결정 기록, 규칙 형식 |
| `app/engine/` | `flow.py` 규칙 실행기, `planner.py` 다음 질문 계산기, `kb.py` 지식 로더(kb_version, 재활용 유형표) |
| `app/interview/` | 문진 서비스: 답 검증(`catalog.py`), 응답 만들기(`present.py`), DB 작업(`service.py`), 서류 업로드·검수·적용(`documents.py`) |
| `app/reading/` | 시험성적서 표 읽기(pdfplumber·Azure Document Intelligence). 기존 엔진에서 복원한 서류 읽기 기반이며 판정은 하지 않는다 |
| `app/api/` | `/internal/v1` 경로·인증·오류 형식 |
| `app/persistence/`, `alembic/` | SQLAlchemy 모델, 마이그레이션 |
| `tools/` | 법령 수집, 골든셋 빌드·검사·평가, 규칙 비교, 가상 문진 |
| `tests/` | 엔진·계산기·API 테스트(골든셋 98건 API 문진 포함) |

## 4. 명령어

```bash
uv sync
uv run python -m pytest -q                       # 테스트(SQLite). Windows는 `uv run pytest` 대신 이 형태
uv run ruff check . && uv run ruff format .      # 린트·포맷
uv run alembic upgrade head && uv run alembic check
uv run python tools/check_cases.py               # 골든셋 근거·값 검사
uv run python tools/build_decision_table.py --check
uv run python tools/build_golden.py --check      # 골든셋 동결 해시
uv run python tools/compare_flows.py score knowledge/flow   # 판정 규칙 채점
uv run python tools/simulate_interview.py        # 문진 계획: 결론 정확도·질문 수
uv run python tools/collect_law.py               # 법령 다시 수집(키 필요, 개발 PC에서만)
docker compose up -d db                          # PostgreSQL(호스트 포트 55432)
TEST_DATABASE_URL=postgresql+psycopg://wd:wd@localhost:55432/postgres uv run python -m pytest -q
```

CI(`.github/workflows/ci.yml`)는 develop·main 대상 PR과 push에서 위 검사를 SQLite와 PostgreSQL 기준으로 실행한다.

## 5. 작업 종료 루프 (모든 작업 끝에 수행)

1. **검증**: pytest, `ruff check`, `ruff format --check`를 실행하고 결과를 그대로 보고한다. 규칙·문진 계획을 바꿨으면 `compare_flows.py score`와 `simulate_interview.py`도, 골든셋을 바꿨으면 `check_cases.py`·`build_golden.py --check`도, DB 모델을 바꿨으면 `alembic check`도 실행한다
2. **문서 영향 점검**: 아래 표로 영향을 판단하고 보고한다

   | 이번 작업에서 생긴 일 | 갱신 후보 |
   | --- | --- |
   | API·턴 응답·인계 객체가 바뀜 | `docs/api/server-engine-contract.md` |
   | 판정 해석을 새로 정함 | `knowledge/flow/decisions.md` |
   | 골든셋이 바뀜 | `knowledge/cases/CHANGELOG.md`, `README.md` |
   | 실행 방법·환경변수가 바뀜 | `README.md`, `.env.example`, `docker-compose.yml` |
   | 공통 규칙이 부족해 잘못된 방향으로 작업함 | 이 파일 2장 |

3. **에이전트 문서는 승인 후에만 고친다.** 고치면 [docs/agent-changelog.md](docs/agent-changelog.md)에 한 줄 기록한다. 사용자가 작업 지시와 함께 문서 변경을 요청한 경우는 그 요청을 승인으로 본다
