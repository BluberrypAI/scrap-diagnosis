# wastecalc — 사업장폐기물 법적 지위 계산기 (MCP)

판단은 법이 한다. 모르면 추측하지 않고 **무엇을 확인하면 갈리는지**(조문·기준값·확인 방법)를 돌려준다.

## 지금 되는 단계

| 단계 | 판정 | 근거 |
|---|---|---|
| S0 | 폐기물 / 폐기물 아님 / 순환자원 | 폐기물관리법 제2조제1호, 순환경제사회 전환 촉진법 제21조제5항, 2023 분류 설명서 사례 |
| S1 | 폐기물관리법 적용 / 적용 제외 | 폐기물관리법 제3조 |
| S2 | 사업장폐기물 / 생활폐기물 | 폐기물관리법 제2조제2·3호, 시행령 제2조, 배출자신고 지침 Ⅴ |
| S3 | 지정폐기물 / 아님 / 해석 필요 | 시행령 별표 1 전 항목, 시행규칙 별표 1 용출 기준 (`rules/rules_s3.yaml`, `tools/build_s3_rules.py`로 생성) |
| S4 | 별표 4 분류번호 (313개) | 앞 단계로 번호 범위를 좁히고(`rules/s4_map.yaml`), 범위 안에서 법령 명칭 목록으로 고름. 번호 표는 `tools/build_annex4.py`가 원문에서 생성(`rules/annex4_codes.yaml`) |
| S5 | 재활용 금지 / 제한 / 허용 R코드 / 유형 미지정 | 법 제13조의2②, 시행규칙 제14조의3②, 시행령 별표 4의3(`rules/s5_rules.yaml`), 시행규칙 별표 4의3 표(`tools/build_annex43.py`가 괘선 좌표로 추출 → `rules/annex43.yaml`), 별표 4의2 R코드 정의(`rules/r_codes.yaml`) |

결과의 `summary`에 S0~S5 단계별 결론이 한 줄씩 들어간다.

S2는 S3 결과를 참조한다: 배출시설이 없고 하루 300kg 미만이어도 이 폐기물이 지정폐기물이면 사업장폐기물이다(시행령 제2조제6호).

## 구조

- `rules/facts.yaml` — 받는 사실, 허용 값, 확인 방법
- `rules/rules.yaml` — 판정 규칙(조건 + 조문 원문 + 검토 상태). 엔진은 이 표만 읽는다
- `rules/sources.yaml` — 인용 원문 파일과 법령 판
- `src/wastecalc/engine.py` — 3값 평가, 후보 지우기, 해결 안내 조립
- `src/wastecalc/render.py` — 정해진 틀의 안내문
- `src/wastecalc/server.py` — MCP 서버 (JSON + 안내문을 함께 반환)

## 결과 상태

`DETERMINED` · `NEED_INFO` · `NEED_TEST` · `NEED_EXPERT` · `OUT_OF_SCOPE`
`strict=true`(기본)면 사람이 검토(`review: REVIEWED`)하지 않은 규칙이나 법령이 아닌 해석 근거로 나온 결론은 `NEED_EXPERT` + `provisional: true`로 낸다.

## 실행

```bash
python -m pytest -q
```

```bash
set PYTHONPATH=src && python -m wastecalc.server
```

MCP Inspector: `npx @modelcontextprotocol/inspector python -m wastecalc.server` (환경변수 `PYTHONPATH=src`)

## 규칙 검토

모든 규칙은 `review: UNVERIFIED`로 시작한다. 두 사람이 조문 원문과 조건을 대조한 뒤 `REVIEWED`로 바꾼다.
인용문은 `tests/test_rules_data.py`가 원문 PDF와 자동 대조한다(텍스트 층이 깨진 자료는 육안 대조 기록 필요).

## 법령 판과 기준일(as_of)

모든 판정은 **기준일**(`as_of`, `YYYY-MM-DD`, 기본 오늘)에 시행 중인 법령의 규칙으로만 한다. 결과에 `as_of`가 남는다.

- 규칙의 유효 기간 = 근거 원문(`rules/sources.yaml`)의 `effective_on` ~ `effective_to`. 규칙에 `effective_from`/`effective_to`를 직접 적으면 그것이 우선한다.
- `effective_to`는 **인용한 문언이 바뀌기 전날**로 적는다. 법률 번호가 바뀌어도 인용 조문이 그대로면 기간을 끊지 않는다.
- 자동 생성 표(`annex4_codes*.yaml`, `annex43*.yaml`, `r_codes*.yaml`)는 판별로 파일을 따로 두고, 파일의 `source`로 기간을 정한다. 기준일에 유효한 판이 정확히 하나여야 한다.
- 어떤 단계의 규칙 중 하나라도 기준일에 유효한 판이 없으면(`abolished: true` 표시 제외) 그 단계는 판정하지 않고 `OUT_OF_SCOPE` / `NO_RULES_FOR_DATE`를 낸다. 일부 규칙만 빠진 채 '나머지 모두 아님' 결론을 내면 틀릴 수 있기 때문이다.
- 같은 규칙 id의 여러 판은 유효 기간이 겹치면 불러올 때 오류가 난다.

### 법령이 개정되면

1. 새 원문을 `sources/raw/`에 새 이름으로 받는다(구판은 지우지 않는다).
2. `sources.yaml`에 새 출처를 추가하고, 바뀐 구판 출처에 `effective_to`를 적는다.
3. 생성기로 새 판 표를 만든다(예: `annex4_codes_2027.yaml`, `source: 새 출처`).
4. 바뀐 조문을 인용하는 규칙은 같은 id로 새 판 행을 추가하거나, 없어졌으면 구판에 `abolished: true`.
5. `python -m pytest -q`(판 전환·원문 대조) → `python tools/evaluate_cases.py`(정답셋 재채점).
