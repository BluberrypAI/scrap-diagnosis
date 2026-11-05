# resource_engine — 산업폐기물 법적 지위 계산기 (규칙 엔진 + MCP)

중소 제조업 담당자가 폐기물에 대한 사실을 답하면, **폐기물관리법령으로** 다음을 판정한다.

> 폐기물인가 → 폐기물관리법이 적용되는가 → 사업장폐기물(산업폐기물)인가 → 지정폐기물인가 → 분류번호(시행규칙 별표 4) → 재활용 가능 유형(별표 4의3)

**원칙**

- **판단은 법이 한다.** 판정은 조문 원문을 인용한 규칙 표로만 한다. LLM은 판정하지 않는다(말을 사실 값으로 바꾸고 쉬운 말로 설명할 뿐).
- **모르면 추측하지 않고, 구분하는 기준을 안내한다.** 무엇을 확인하면 갈리는지, 어떤 서류·시험이 필요한지 알려 준다.
- **법 조문으로 정할 수 없으면 결론 대신 문의처를 안내한다.** 근거가 해설·질의회신뿐인 지점은 관할 기관과 질의서 초안을 준다.
- **모든 결과에 근거 조문 원문, 법령 판, 판정 기준일**을 붙인다. 같은 입력·같은 기준일이면 항상 같은 결과.

> ⚠️ 시험용 시제품이다. 모든 규칙은 `review: UNVERIFIED`(사람 검토 전)이며, 결과는 법적 판단이나 유권해석이 아니다.

---

## 빠른 시작

Python 3.11 이상.

```bash
pip install -e ".[test]"
python -m pytest -q                  # 테스트
python -m wastecalc.web              # 웹 화면 (아래 주소)
python -m wastecalc.server           # MCP 서버(stdio)
```

`pip install -e .` 없이 쓰려면 환경변수 `PYTHONPATH=src`를 준다.

저장소에는 **엔진 기능만** 둔다. 실행하면 HTTP API만 열린다(`python -m wastecalc.web`, 문서는 http://127.0.0.1:8000/docs).
로컬 시험 화면(`src/wastecalc/web/static/`, `src/wastecalc/web/scrap/` — 팀 디자인 사본)은 저장소에서 뺐고, 파일이 있는 로컬에서만 `/`·`/test`가 열린다.

팀 웹(scrap-web, React)용 API는 `/api/classification/*`(화면이 읽는 모양으로 응답, `src/wastecalc/scrap_view.py`). 운영에서는 서버(scrap-server)가 상태 없는 `evaluate`·`apply`·`record`를 부르고 상태는 서버 DB에 둔다 → `docs/scrap-web-integration.md`(응답 형식·UI 수정·합의 사항), `docs/db-server-integration.md`(DB 이전·서버 통합).

### MCP 클라이언트에 연결

```json
{
  "mcpServers": {
    "wastecalc": { "command": "wastecalc-mcp" }
  }
}
```

설치 없이 쓰면 `command`를 Python 경로로, `args`를 `["-m", "wastecalc.server"]`로, `env`에 `PYTHONPATH`(이 저장소의 `src` 절대 경로)를 준다. 시험 시나리오와 에이전트 지시문은 [docs/mcp-test-scenarios.md](docs/mcp-test-scenarios.md).

### LLM 연결(선택)

`.env.example`을 `.env`로 복사해 Azure OpenAI 또는 OpenAI 값을 넣으면 시험 화면의 LLM 기능(상황 설명에서 사실 제안, 직접 입력 변환, 질문 뜻 설명)이 켜진다. `.env`는 커밋하지 않는다. 비워 두면 객관식만으로 끝까지 동작한다.

---

## 판정 단계

| 단계 | 결론 | 근거 |
|---|---|---|
| S0 | 폐기물 / 폐기물 아님 / 순환자원 | 폐기물관리법 제2조제1호, 순환경제사회 전환 촉진법 제21조제5항 (질문: 이 물질을 어떻게 하나요? — 계속 사용 / 같은 공정 재투입 / 연속공정 원료 / 내보냄) |
| S1 | 폐기물관리법 적용 / 적용 제외(다른 법) | 폐기물관리법 제3조 (제외 사유 10가지) |
| S2 | 사업장폐기물 / 생활폐기물(범위 밖) | 법 제2조제2·3호, 시행령 제2조, 배출자신고 지침 Ⅴ. S3 결과를 참조(작은 사업장도 지정폐기물을 내면 사업장폐기물) |
| S3 | 지정폐기물 / 아님 / 해석 필요 | 시행령 별표 1 전 항목, 시행규칙 별표 1 용출 기준. 지정 세부 품목 36가지 |
| S4 | 분류번호(산업폐기물 279개 중 272개 도달 가능) | 시행규칙 별표 4. 앞 단계로 번호 범위를 좁히고, 범위 안에서 법령 명칭으로 고른다 |
| S5 | 재활용 금지 / 제한 / 허용 R코드 / 유형 미지정 | 법 제13조의2②, 시행규칙 제14조의3②, 시행령 별표 4의3, 시행규칙 별표 4의2·4의3 |

결과 상태: `DETERMINED`(완료) · `NEED_INFO`(정보 필요) · `NEED_TEST`(시험 필요, 시험 항목·방법 안내) · `NEED_EXPERT`(전문가·기관 확인, 문의처·질의서 초안) · `OUT_OF_SCOPE`(범위 밖 또는 그 날짜의 규칙 없음).

`strict=true`(기본)이면 사람이 검토하지 않은 규칙으로 나온 결론은 잠정(`provisional`)으로 표시한다.

---

## 저장소 구조

```
rules/            판정 규칙과 표(엔진은 이것만 읽는다)
  facts.yaml        받는 사실: 질문, 형식, 허용 값, 확인 방법
  rules.yaml        단계 정의, S0~S2 규칙(조건 + 조문 원문 + 쉬운 설명 + 검토 상태)
  rules_s3.yaml     S3 규칙 122개 (tools/build_s3_rules.py가 생성 — 직접 고치지 않음)
  annex4_codes.yaml 별표 4 번호 313개 (tools/build_annex4.py가 원문에서 추출)
  annex43.yaml      별표 4의3 재활용 가능 유형 (tools/build_annex43.py가 괘선 좌표로 추출)
  r_codes.yaml      별표 4의2 R코드 정의 52개
  s4_map.yaml       S3 결과 → 별표 4 번호 범위 대응표
  s5_rules.yaml     재활용 금지·제한
  consult.yaml      문의처(지침 Ⅳ 기관별 관할)
  glossary.yaml     용어 풀이
  sources.yaml      인용 원문 파일, 법령 판, 유효 기간
src/wastecalc/
  engine.py         판정 엔진(3값 논리, 후보 지우기, 이유·확인 방법·문의 안내 조립)
  kb.py             규칙 불러오기, 기준일별 보기(as_of), 형식 검사
  annex4.py         S4 분류번호
  recycling.py      S5 재활용
  compact.py        대화용 간략 응답
  render.py         사람이 읽는 안내문
  server.py         MCP 서버(도구 8개)
  llm.py            LLM 어댑터(선택)
  scrap_view.py     팀 웹 문진 화면용 응답 변환
  record.py         판정 기록(이후 단계용 고정 형식, schemas/)
  web/app.py        HTTP API(FastAPI)
data/             엔진이 읽는 보조 표 2개만(code_interpretations.csv, allowed_recycling.csv)
schemas/          판정 기록 JSON 스키마
testdata/         질의회신·판례 정답셋 178건, 평가 결과, 블라인드 시험
tools/            표 생성기, 평가 스크립트
tests/            테스트(원문 대조 테스트는 법령 원문이 있는 로컬에서만 실행)
docs/             작업 지시서, 시험 시나리오
```

엔진을 읽는 순서: `src/wastecalc/engine.py`의 `evaluate` → `eval_stage` → `eval_rule` / `eval_condition` → `_resolution` → `_consult`.

### MCP 도구

| 도구 | 하는 일 |
|---|---|
| `list_facts` | 받는 사실과 허용 값 |
| `start_assessment` / `answer_question` | 세션 판정(여러 답을 `answers`로 한 번에). 기본은 간략 응답 |
| `evaluate_facts` | 세션 없이 한 번에 판정 |
| `explain` | 근거 원문·경우의 수 전체·용어 풀이 |
| `get_rule` | 규칙 한 행(조건·원문·판) 재조회 |
| `allowed_recycling_types` / `r_code_definition` | 분류번호별 재활용 유형, R코드 정의 |

---

## 결과 설명

안내문은 **한 줄 결론 → 단계별 결론과 '왜' → 아직 확인할 것 → 근거 원문 → 용어 풀이** 순서다.

- `plain`: 규칙마다 쉬운 설명(법적 효력 없음, 원문이 우선). 숫자는 규칙의 기준값·원문에 있는 것만(테스트로 검사).
- `because`: 입력값과 기준을 나란히 — 예: "하루 평균 배출량: 450kg/일 → 기준 '300kg/일 이상' 충족". '아님' 결론은 경로마다 왜 해당하지 않았는지.
- `consult`: 근거가 해설·질의회신뿐이면 결론 대신 문의처(유역(지방)환경청·시도·시군구·국민신문고)와 질의서 초안. 사례상 결론은 `reference_conclusion`으로만 보여 주고, 다른 단계 판정의 근거로도 쓰지 않는다.

---

## 법령 판과 기준일(as_of)

모든 판정은 **기준일**(`as_of`, 기본 오늘)에 시행 중인 법령의 규칙으로만 한다.

- 규칙의 유효 기간 = 근거 원문(`sources.yaml`)의 `effective_on` ~ `effective_to`. `effective_to`는 **인용한 문언이 바뀌기 전날**로 적는다.
- 별표 표는 판별로 파일을 따로 두고(`annex4_codes*.yaml` 등) 파일의 `source`로 기간을 정한다.
- 어떤 단계 규칙 중 하나라도 기준일에 유효한 판이 없으면 그 단계는 판정하지 않는다(`NO_RULES_FOR_DATE`). 판 기간이 겹치면 불러올 때 오류.

**법령이 개정되면:** 새 원문을 받아 `sources.yaml`에 추가(구판은 `effective_to`) → 생성기로 새 판 표 생성 → 바뀐 조문의 규칙은 같은 id로 새 판 행 추가(없어졌으면 `abolished: true`) → `pytest`(판 전환·원문 대조) → `tools/evaluate_cases.py`(정답셋 재채점).

지켜볼 개정: 시행규칙 일부개정령안 제2026-615호(별표 4·4의2·4의3 정비, 2026-11 현재 공포 전), 폐기물공정시험기준 개정 행정예고 제2026-449호.

---

## 검증

| 검증 | 내용 |
|---|---|
| 원문 대조 | 규칙·설명·문의처의 모든 인용문을 원문 PDF와 자동 대조(텍스트 층이 깨진 자료는 쪽 이미지 육안 대조 기록) |
| 표 추출 | 별표 4 번호 313개 원문 대조, 별표 4의3은 Codex의 이미지 대조 자료 19개 번호와 전부 일치 |
| 조합 검사 | S2 전수(5,832 조합), S3 무작위 15,000 조합 — 규칙 겹침·구멍 0 |
| 경계값 | pH 2.0/12.5, 300kg, 5톤, 기름 5%, 페인트 6mm, PCB, 오니 수분 95% 등 |
| 정답셋 | `python tools/evaluate_cases.py` — 질의회신·판례 178건 단계별 채점(틀림·멈춤·과신 구분, 시기별 집계) |
| 실제 사례 + 가정 | `python tools/run_supplemented.py` |
| 블라인드 | `python tools/run_blind.py testdata/blind/batch1.yaml` — 가정을 실행 전에 고정. 1회차 기본 입력 11건 중 맞음 10, 멈춤 1, 틀림 0. 이후 변경은 `testdata/blind/CHANGELOG.md` |

정답셋에서 규칙 보완의 근거로 쓴 사례는 평가용(EVAL)에서 개발용(DEV)으로 옮긴다.

---

## 알려진 한계

- 모든 규칙이 사람 검토 전(`UNVERIFIED`).
- 시행령 별표 1 제12호 등 "그 밖에 장관이 고시하는 물질" 고시 존재 여부를 확인하지 못함 → '지정폐기물 아님' 결론에 한계로 표시.
- 손상된 폐이차전지(별표 4의 03-10)는 시행령 근거 항목을 찾지 못해 '해석 필요'로 멈춤.
- 세부 분류번호는 계산기가 범위를 좁히고 사용자가 법령 명칭을 보고 고른다(엔진은 앞 단계와의 일치만 검사).
- 사용자가 보기를 잘못 고르면 결과가 달라진다(블라인드 변형 시험). 결론을 뒤집는 답 재확인, 앞 답을 고치면 뒤 답 재확인, 겹치는 질문 정리(S2 사업장 조건, S3 묻은 것·섞인 것)가 다음 과제.
- 하루 평균 300kg 산정 방법을 정한 근거 미확보(실무 안내로 표시).
- LLM 연동은 가짜 응답으로만 시험됨(실제 키로 미시험).

## 저장소에 넣지 않은 것

| 항목 | 이유 | 다시 얻는 법 |
|---|---|---|
| `sources/raw/` 법령·지침·판례 원문(약 17MB) | 용량. 엔진 실행에는 필요 없음(인용문은 `rules/`에 있음) | `rules/sources.yaml`의 출처·판·해시로 국가법령정보센터 등에서 같은 판을 받는다. 원문이 있으면 원문 대조 테스트가 돈다 |
| `collect/`, `audit/`, `inventory/`, `data/`의 수집 자료 | 자료 수집·검수 과정의 중간 산출물 | Git 이력(커밋 `e7f445f` 이전)에 남아 있음 |
| 로컬 시험 화면(`web/static/`, `web/scrap/`) | 화면은 팀 웹(scrap-web)이 담당 | Git 이력에 남아 있음 |

규칙을 원문에서 다시 만드는 도구(`tools/build_*.py`)는 원문이 있어야 실행된다.
