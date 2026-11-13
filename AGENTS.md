# AGENTS.md

Re:Source AI 조직의 **폐기물 진단 엔진(waste-diagnosis)**. 모든 AI 코딩 에이전트(Claude Code, Codex 등)의 공통 진입점이다.
폐기물 분류번호를 문진으로 판정하고, 확정 결과를 경로추천 AI에 넘기는 인계 객체를 만든다. 로그인·회원·화면은 다른 레포 담당이므로 여기서 구현하지 않는다.

원칙: **AI(LLM)는 제안하고, 규칙 엔진이 판정하고, 서버가 검증한다.** 분류번호는 규칙 엔진만 정한다.

## 1. 문서 지도 (작업 전에 필요한 것만 읽음)

| 문서 | 언제 읽음 |
| --- | --- |
| [README.md](README.md) | 실행·테스트 명령, 설정 |
| [docs/README.md](docs/README.md) | 문서 목차. 어떤 문서가 무엇인지 |
| [docs/team/guide.md](docs/team/guide.md) | 다른 팀과의 경계, 팀원 확인사항 |
| [docs/api/server-engine-contract.md](docs/api/server-engine-contract.md) | 서버가 부르는 API(`/internal/v1`), 오류 코드를 바꿀 때 |
| [docs/handoff-contract.md](docs/handoff-contract.md) | 확정·인계 객체(`diagnosis-handoff-v1`)를 바꿀 때 |
| [knowledge/README.md](knowledge/README.md) | 규칙 원본(법 규칙·소재·번호 대응·근거)을 고치거나 빌드할 때 |
| [docs/rule-changes/](docs/rule-changes/) | 규칙 내용(판정)을 바꿀 때: 주제별 차이 보고서를 여기에 남김 |
| [docs/ui/ui-contract.md](docs/ui/ui-contract.md), [docs/ui/ui-design.md](docs/ui/ui-design.md) | 화면(scrap-web)이 쓰는 응답 필드를 바꿀 때 |
| [docs/llm-data-policy.md](docs/llm-data-policy.md) | AI 호출·프롬프트·Trace 기록을 바꿀 때 |
| [docs/agent-changelog.md](docs/agent-changelog.md) | 에이전트 문서를 고칠 때 |
| 팀 공통 규칙(조직 `.github`의 CONTRIBUTING.md) | 브랜치·커밋·PR을 만들 때, 다른 레포와의 경계·API 형식을 바꿀 때 |

## 2. 공통 규칙

1. **분류 판정을 LLM에 맡기지 않는다.** LLM 출력은 `app/agent/guard.py` 검증을 통과한 사실만 엔진에 들어간다. 확인되지 않은 값은 추정해 채우지 않고 비워 둔다
2. **생성된 규칙 데이터는 손으로 고치지 않는다.** `data/real/`은 규칙 원본 `knowledge/`를 `tools/build_kb.py`로 빌드한 생성물이다. 규칙을 바꿀 때는 `knowledge/`(또는 빌드 로직)를 고치고 다시 빌드한다. `build_kb.py --check`가 CI와 테스트에서 생성물이 원본과 같은지 검사한다. 판정표 회귀 수치(`tools/legacy_regression.py`)가 바뀌면 이유를 보고한다. `data/real/`의 `regression/`(기존 엔진 판정표 기준)과 `scenarios/`는 빌드 대상이 아니다
3. **API 형식**: 필드·엔드포인트 추가는 자유. 서버·화면이 쓰는 필드의 삭제·이름 변경·타입 변경은 하지 않는다. 필요하면 멈추고 사용자에게 확인한다(팀 규칙 1장). 바꾼 뒤에는 `scripts/export_openapi.py`로 `docs/api/openapi.json`을 다시 만든다
4. **계약 문서 위치를 바꾸지 않는다.** `docs/handoff-contract.md`, `docs/document-extraction-contract.md`, `docs/ui/ui-contract.md`, `docs/api/server-engine-contract.md`는 코드·테스트가 경로를 참조한다
5. **DB 스키마를 바꾸면 Alembic 마이그레이션을 같이 만든다.** SQLite와 PostgreSQL 모두에서 테스트한다. 확정된 Trace(`immutable`)는 고치거나 지우지 않는다(기업 데이터 삭제 경로만 예외)
6. **동기 핸들러 안에서 AI를 부를 때는 DB 트랜잭션을 열어 둔 채 기다리지 않는다**(`CaseService._release_db`). `async def` 라우트 안에서 동기 DB·AI 호출을 하지 않는다
7. 비밀값은 코드·커밋·로그에 쓰지 않는다. 로컬은 `.env`(git 제외), 변수 이름은 `.env.example`에 값 없이 둔다. `.env` 값을 출력하지 않는다
8. 사용자에게 보이는 문서와 응답은 한국어로 쓴다. 코드 식별자와 커밋 메시지 제목은 영어로 쓴다(본문은 한국어 가능)
9. develop·main에 직접 커밋하지 않는다. 작업 브랜치 `<종류>/<번호>-<설명>`(feat·fix·docs·chore·refactor·test)에서 커밋하고, push·PR·병합은 사용자가 요청할 때만 한다
10. 화면은 scrap-web 담당이다. 예전 참조 화면(`web/`)은 scrap-web으로 옮긴 뒤 지웠고 `archive/reference-web-ui` 브랜치에 보관한다

## 3. 구조

| 경로 | 내용 |
| --- | --- |
| `app/rules/` | 규칙 모델·로더·3값 평가기·질문 선택기·답변 변환 |
| `app/agent/` | 문진 오케스트레이터, 라우터, LLM 추출·응답·guard, 식별정보 가림 |
| `app/domain/` | 사실(append-only)·판정·인계·서류 계약 모델 |
| `app/api/` | FastAPI 라우트·서비스·스키마·오류·인증 |
| `app/persistence/` | SQLAlchemy 모델·저장소, `alembic/` 마이그레이션 |
| `knowledge/` | 규칙 원본: 법 규칙, 소재, 번호 대응표, 별표 4, 근거 문서, 사실 정의·설정 |
| `data/real/` | 엔진이 읽는 규칙 데이터(`knowledge/`로 빌드한 생성물, 생성 규칙마다 `source_rule`·조문 위치) |
| `data/sample/` | 테스트용 작은 규칙 데이터(손으로 관리, 빌드하지 않음) |
| `tests/`, `scripts/`, `tools/` | 테스트, 평가·측정 스크립트, 규칙 빌드(`build_kb.py`)·판정표 회귀(`legacy_regression.py`) |

## 4. 명령어

```bash
uv sync
uv run pytest                                   # 테스트(SQLite)
uv run ruff check . && uv run ruff format .     # 린트·포맷
uv run python scripts/export_openapi.py --check # OpenAPI 최신 여부
uv run python tools/build_kb.py                 # 규칙 원본(knowledge/) → data/real/ 빌드
uv run python tools/build_kb.py --check         # 생성물이 원본과 같은지
uv run python tools/legacy_regression.py        # 기존 엔진 판정표와 비교
uv run python scripts/eval.py --mock-extractor  # 골든 시나리오(AI 없이)
uv run python tools/review_kit.py export        # 전문가 검토 카드(build/review/)
docker compose up -d db                         # PostgreSQL(호스트 포트 55432)
TEST_DATABASE_URL=postgresql+psycopg://wd:wd@localhost:55432/postgres uv run pytest
```

CI(`.github/workflows/ci.yml`)는 develop·main 대상 PR과 push에서 위 검사를 SQLite와 PostgreSQL 기준으로 실행한다.

## 5. 작업 종료 루프 (모든 작업 끝에 수행)

1. **검증**: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`를 실행하고 결과를 그대로 보고한다. API를 바꿨으면 OpenAPI 검사, 규칙 원본이나 빌드를 바꿨으면 `build_kb.py --check`와 판정표 회귀도 실행한다
2. **문서 영향 점검**: 아래 표로 영향을 판단하고 보고한다

   | 이번 작업에서 생긴 일 | 갱신 후보 |
   | --- | --- |
   | API가 추가·변경됨 | `docs/api/server-engine-contract.md`, `docs/api/api-spec.md`, `docs/api/openapi.json` |
   | 인계 객체가 바뀜 | `docs/handoff-contract.md` |
   | 규칙 원본 구조·빌드 방식이 바뀜 | `knowledge/README.md`, `data/real/conversion_report.md`(빌드가 만듦), `docs/engine/algorithm.md` 2절 |
   | 실행 방법·환경변수가 바뀜 | `README.md`, `.env.example`, `docker-compose.yml` |
   | 다른 팀이 알아야 할 변경 | `docs/team/guide.md`(팀원 확인사항) |
   | 공통 규칙이 부족해 잘못된 방향으로 작업함 | 이 파일 2장 |

3. **에이전트 문서는 승인 후에만 고친다.** 고치면 `docs/agent-changelog.md`에 한 줄 기록한다. 사용자가 작업 지시와 함께 문서 변경을 요청한 경우는 그 요청을 승인으로 본다
