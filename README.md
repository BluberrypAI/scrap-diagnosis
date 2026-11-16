# waste-diagnosis

폐기물 분류 코드 판정 엔진과 문진 에이전트. 원칙은 **LLM은 제안하고, 규칙 엔진이 판정하고, 서버가 검증한다.**

현재 진행: M1(엔진 코어), M2(질문 선택·라우터·시뮬레이터), M2R(기존 엔진 실제 규칙 변환), M3(LLM 추출·응답·guard), M4(API·영속화·문서·confirm/reopen·Trace) 완료. 통합 작업안(서버 내부 API·서류 검수·AI 전송 정책·기업 데이터 삭제) 반영. 문서 목차: [docs/README.md](docs/README.md), 팀원용 안내: [docs/team/guide.md](docs/team/guide.md).

엔진이 질문을 고르고 판정하는 방법: [docs/engine/algorithm.md](docs/engine/algorithm.md)

## 화면에서 써 보기

문진 화면은 **scrap-web**이 맡는다(`/wastes/case-<건 ID>/survey`). scrap-web → scrap-server(`/api/v1/diagnosis`) → 이 엔진(`/internal/v1`) 순서로 부른다.
예전 참조 화면(`web/`)은 scrap-web으로 옮긴 뒤 이 저장소에서 지웠고, 원본은 `archive/reference-web-ui` 브랜치에 보관한다.

**엔진만 띄우기**
```bash
uv sync
cp .env.example .env        # 실제 AI를 쓰려면 AZURE_OPENAI_* 값을 채운다(값은 팀에서 따로 받음)
DATABASE_URL=sqlite:///var/ui.db uv run uvicorn app.main:app --port 8030   # API 문서 http://localhost:8030/docs
```
Windows PowerShell이면 `$env:DATABASE_URL="sqlite:///var/ui.db"; uv run uvicorn app.main:app --port 8030`로 실행한다.
scrap-server는 `DIAGNOSIS_ENGINE_URL=http://127.0.0.1:8030`과 이 엔진과 같은 `ENGINE_SERVICE_TOKEN`(영문·숫자만)을 넣고 띄운다.
`AZURE_OPENAI_*` 값을 비워 두면(또는 `LLM_PROVIDER=off`) AI 없이 동작한다. 이때는 자유 문장을 알아듣지 못하므로 선택지 버튼으로만 답한다.

| 입력해 볼 문장 | 확인할 것 |
|---|---|
| `PP 필름 자투리예요` → 버튼으로 답 | 질문 3~4번에 `51-03-01` 확정, 결과의 "근거 보기" |
| `이건 왜 물어봐요?`, `PCB가 뭐예요?` | 질문 카드는 그대로, 근거 조문·용어 설명이 붙은 보충 설명 말풍선 |
| `옛날 변압기에 든 독한 기름 있잖아요, 그거 뭐예요?` | 단어가 달라도 뜻으로 자료를 찾음(PCB 설명) |
| `아마 PP일걸요`, 오염 묶음 질문에 `아마 다 해당 없을걸요` | 판정 보드에 "· 추측", 확정 전에 추측한 오염 항목을 한 번 다시 물음 |
| `근처 처리업체 추천해 줘` | 문진만 돕는다고 안내하고 원래 질문 유지 |
| `폐수처리 오니` → 함수율 `모르겠어요` | 추측하지 않고 시험성적서 요청 |

개발용 API(`/dev/rules/*`, `/cases/{id}/trace`)는 `APP_ENV=prod`면 404다. 이 API를 그려 보던 개발자 화면(규칙 그래프·AI 데이터)도 `archive/reference-web-ui` 브랜치에 있다.

## 문진 대화는 어떻게 동작하나 (답변과 질문 구분, 설명 자료)

AI가 엔진을 부르는 구조가 아니라, **코드(하네스)가 AI와 엔진을 정해진 순서로 부른다**(`app/agent/orchestrator.py`). 판정은 매 턴 규칙 엔진이 하고, AI는 말을 이해하고 문장을 쓰는 일만 한다. 설계: [docs/design/agent-skill-harness.md](docs/design/agent-skill-harness.md).

**1. 엔진에 넣을 답과 일반 질문을 나누기** — 추출 AI가 한 번 읽고 나눈다(`app/agent/extractor.py`, 턴당 첫 번째 AI 호출)

| 사용자 말 | AI 출력 | 다음 처리 |
|---|---|---|
| "PP예요", "다 해당 없어요" | `facts`, `group_answer` | guard 검사 → 엔진 사실로 기록 → 판정 |
| "왜 물어봐요?" | `question_kind: "why"` | 엔진에 넣지 않음 → 보충 설명 |
| "PCB가 뭐예요?", "어떻게 확인해요?" | `question_kind: "term"` | 엔진에 넣지 않음 → 보충 설명 |
| "업체 추천해 줘" | `question_kind: "off_topic"` | 문진만 돕는다고 안내 |
| "다 없어요, 근데 왜요?" | 둘 다 | 답은 엔진에, 질문은 설명으로 |
| "아마 PP일걸요" | 값 + `certainty: "guess"` | 기록하되 "추측" 표시, 위험한 추측은 확정 전에 한 번 다시 물음 |

질문은 판정에 들어가지 않는다. 설명은 엔진 결과 위에 덧붙는 말풍선(턴 응답의 `assist`)이다.

**2. 질문에 답할 정보가 있는 곳** — 모두 `knowledge/`에 사람이 쓴 파일이고, 빌드(`tools/build_kb.py`)가 `data/real/`로 옮긴다

| 파일 | 내용 | 쓰임 |
|---|---|---|
| `question_guide.yaml` | 문진 질문마다 뜻·이유·확인 방법·선택지 뜻·예시·FAQ, 참고 주제(폐유·PCB·MSDS 등) | "어떤 게 해당돼요?", "어디를 봐요?" |
| `glossary.yaml` | 전문용어의 쉬운 설명 | "용출이 뭐예요?" |
| `law_rules/*.yaml`의 `plain` → `rule_notes.yaml` | 규칙마다의 쉬운 설명과 근거 조문 | "왜 물어봐요?", "왜 이 결과예요?" |
| `skills/interviewer.md` | 설명하는 AI의 말투·체크리스트 | 설명 문장 작성 지침 |

**3. 모델이 정보를 읽는 방법** — AI가 파일을 직접 찾거나 도구를 부르지 않는다. 코드가 골라서 건넨다
```
① 추출 AI: 질문 목록 + 사용자 말 + "설명 자료 목록"(자료 id·짧은 제목, app/rules/guide_index.py)을 받아
           질문 종류와 관련 자료 id를 최대 3개 고른다(예: topic:PCB). guard가 목록에 있는 id만 인정
② 규칙 엔진: 판정(코드)
③ 자료 모으기(코드, app/agent/assist.py): 지금 질문의 안내(항상) + AI가 고른 id의 자료(뜻으로 찾기)
           + 단어가 겹치는 FAQ·주제·용어(보조) + "왜?"면 관련 규칙 설명·근거 조문
           + 아무것도 없으면 웹 검색(기본 꺼짐, app/agent/web_search.py)
④ 응답 AI: 엔진 결과 + ③의 자료 + 스킬 지침으로 질문 문장과 설명 문장을 쓴다
           검사(app/agent/guard.py): 자료에 없는 번호·숫자 금지, "왜?"는 근거 인용 필수. 실패하면 템플릿 문장
```
AI 호출은 한 턴에 최대 2번(①·④)이다. 무엇을 보내고 받았는지는 `GET /cases/{id}/trace` 응답에서 본다.

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

시험성적서 표 읽기(시험 구현, `docs/design/test-report-table-extraction.md`):
```bash
uv run python scripts/read_test_report.py 성적서.pdf                    # 글자 있는 PDF는 로컬(pdfplumber)
uv run python scripts/read_test_report.py 사진.jpg --backend azure      # Azure: ALLOW_DOCUMENT_OCR=true와 AZURE_DOCINTEL_* 필요, 과금
```

규칙 원본(`knowledge/`)을 고친 뒤 엔진용 규칙(`data/real/`)을 다시 만들 때(`knowledge/README.md`):
```bash
uv run python tools/build_kb.py            # 빌드
uv run python tools/build_kb.py --check    # 생성물이 원본과 같은지(CI·테스트도 검사)
uv run python tools/legacy_regression.py --write
```

## API 서버 (M4)
```bash
uv run uvicorn app.main:app --port 8030      # 문서: http://localhost:8030/docs
uv run alembic upgrade head                  # 운영 스키마(DATABASE_URL). 개발은 시작 시 create_all
uv run alembic -x url=sqlite:///var/other.db upgrade head
```

PostgreSQL(운영과 같은 DB로 개발·테스트):
```bash
docker compose up -d db                                   # 호스트 포트 55432
uv run alembic -x url=postgresql+psycopg://wd:wd@localhost:55432/waste_diagnosis upgrade head
TEST_DATABASE_URL=postgresql+psycopg://wd:wd@localhost:55432/postgres uv run pytest   # 테스트마다 새 DB
docker compose --profile app up -d --build                # DB + 엔진 컨테이너(포트 8030)
uv run python scripts/turn_latency.py                     # 실제 Azure로 턴당 지연 측정
```
- 설정(`.env`/환경변수): `DATABASE_URL`(기본 `sqlite:///<저장소>/var/app.db`), `KB_DIR`(기본 `data/real`),
  `DB_CREATE_ALL`(기본 true), `LLM_PROVIDER`(off면 LLM 없이 선택지 버튼·라벨만 받음),
  `DB_POOL_SIZE`·`DB_MAX_OVERFLOW`(PostgreSQL 연결 풀), `THREAD_LIMIT`(동시 처리 턴 수, 기본 40)
- 기업 격리: 서버용 경로 `/internal/v1`은 `Authorization: Bearer <ENGINE_SERVICE_TOKEN>` + `X-Company-Id`(서버 기업 ID). 루트 경로는 개발용으로 `X-Company-Id`만 쓴다. 다른 기업의 건은 404. 자세한 규약은 `docs/api/server-engine-contract.md`.
- 코드 없는 결론도 확정한다: 규칙 엔진이 분류번호 없이 결론을 낸 경우(폐기물 아님·순환자원·적용 제외·
  생활폐기물·해석 필요·일반 번호 없음·시험 필요·혼합물)는 `FINAL_REVIEW`(`verdict.waste_code` null,
  `verdict.outcome`)이고 확정하면 `CODE_CONFIRMED`다. 결론이 나지 않은 경우(질문 상한·증빙 거부·규칙 없음)는
  그대로 `UNSUPPORTED`/`NEEDS_INFO`이고 확정할 수 없다(409).
- 경로추천 AI 인계: 확정할 때 `diagnosis-handoff-v1` 객체(`docs/handoff-contract.md`)를 만들어 판정 버전에
  저장하고 confirm 응답·`GET /cases/{id}`의 `handoff`로 낸다. `route_guidance`는 데이터 파일
  `data/<kb>/outcome_guidance.yaml`에서 온다(항목이 빠지면 KB 로드·서버 시작 실패).
- 시각: UTC로 저장하고 응답·인계 객체에는 Asia/Seoul(+09:00) ISO 8601로 낸다. 건에 `diagnosis_started_at`·
  `last_activity_at`·`as_of`, 판정 버전에 `confirmed_at`·`reopened_at`. `as_of`(법 기준일)는 대화를 시작한
  Asia/Seoul 날짜이고 reopen해도 바뀌지 않는다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/companies` | (개발용) 기업 생성. `profile.facts`는 문진 시작 때 PROFILE 사실 |
| GET / PUT | `/companies/me`, `/companies/me/profile` | 내 기업 조회·프로필 수정 |
| POST | `/cases` | 건 생성(memo·quantity·unit·period) → 첫 턴 응답 |
| GET | `/cases?status=` | 상태별 목록 |
| GET | `/cases/{id}` | 건 상세 + 현재 판정·판정 버전·마지막 턴·문서 |
| POST | `/cases/{id}/diagnosis/messages` | `{text}` 또는 `{quick_reply:{key,kind,value}}` → 한 턴 응답(`docs/engine/algorithm.md` 7절) |
| POST | `/cases/{id}/documents` | multipart `file`(.txt/.md/.pdf, OCR이 켜져 있으면 이미지), 선택 `facts`(JSON) → 검수 대기 후보. PDF·이미지는 성적서 표 값도 자동으로 읽어 후보로 |
| POST | `/cases/{id}/confirm` | 서버 재평가 후 판정 버전 고정 + 인계 객체(`handoff`) → `CODE_CONFIRMED` (불가 시 409) |
| POST | `/cases/{id}/reopen` | `CODE_CONFIRMED`에서만. 이전 판정은 버전으로 보존 |
| GET | `/cases/{id}/trace` | Decision Trace 전체(사실 이력·턴·확정 기록) |

## 데이터
- `data/sample/` — 엔진 검증용 SAMPLE 규칙. `SAMPLE-` 코드와 `(샘플)` 조문만 있다.
- `data/real/` — 기존 엔진에서 변환한 실제 규칙(자동 생성, 직접 고치지 않음)
  - 소재별 PRIORITY 테이블 97개, 사실 카탈로그, 묶음 질문, 별표 4 코드표, 출처
  - `conversion_report.md`: 우선순위 대역, 변환하지 않은 기능, 의도한 차이
  - `regression/`: 기존 판정표 4281행과의 비교 데이터·결과
  - 모든 규칙은 `review: UNVERIFIED`다. 법률 검토 전에는 판정을 참고용으로만 쓴다.
- `data/<kb>/outcome_guidance.yaml` — 결론 종류 → 경로추천 AI 안내(사람이 관리, 변환기가 만들지 않음)
- `knowledge/` — 규칙 원본(법 규칙·소재·번호 대응·근거·사실 설정). `data/real/`은 여기서 빌드한 생성물

## 구조
- `app/domain/` — `Fact`(append-only, 유효 사실 선택), `NumRange`(구간 응답)
- `app/rules/loader.py` — YAML 로드·정적 검증(`includes`, `applies_when`, 시행일 필터)
- `app/rules/evaluator.py` — 3값 평가기(`docs/engine/algorithm.md` 4절) + `blocking_facts`(확정을 실제로 막는 미확인 사실)
- `app/rules/selector.py` — 정보가치 질문 선택. 묶음 질문, prior, gain 0 질문 제외, 번호 선택은 마지막
- `app/rules/conflicts.py` — 진술과 문서의 충돌, 후보 0개 설명
- `app/agent/router.py` — 결정적 분기 라우터. `run_engine`은 한 턴의 LLM 없는 부분(자동 채움 포함)
- `app/agent/simulation.py`, `scripts/simulate.py` — 스크립트 답변 시뮬레이터
- `app/agent/{llm_client,extractor,guard,responder,templates,orchestrator}.py` — LLM 제안·검증, 한 턴 처리
- `app/domain/{verdict,trace}.py` — 응답 스키마(`docs/engine/algorithm.md` 7절), Decision Trace
- `tools/build_kb.py`, `tools/legacy_regression.py` — 규칙 빌드와 기존 엔진 판정표 회귀 비교
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
