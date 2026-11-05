# scrap-web 연동: 엔진 응답 형식, UI 수정 사항, 합의 사항

대상: `BluberrypAI/scrap-web` main(`fb4b5c1`). 원칙은 **엔진이 화면에 맞춘다**이고, 화면을 바꿔야만 하는 곳만 아래 2절에 적었다.
엔진 쪽 구현: `src/wastecalc/scrap_view.py`(변환), `src/wastecalc/web/app.py`의 `/api/classification/*`(경로), 테스트 `tests/test_scrap_view.py`.

## 1. 엔진이 화면에 맞춘 것 (UI 변경 없음)

### 1.1 API

| 메서드·경로 | 용도 | 저장 |
|---|---|---|
| `POST /api/classification/evaluate` `{answers, ui, as_of?, trail?}` | **상태 없는 판정.** 서버가 답·화면 상태를 DB에 두고 매번 부르는 용도(운영 권장) | 저장 안 함 |
| `POST /api/classification/sessions` `{waste_id, answers?}` | 문진 시작(로컬 시연·개발용 세션) | 엔진 SQLite |
| `GET /api/classification/sessions/{id}` | 이어서 하기(새로고침 복구) | |
| `POST /api/classification/sessions/{id}/answer` `{answers}` | **고른 보기의 `answers`를 그대로** 보냄 | |
| `POST /api/classification/sessions/{id}/undo` | '이전' | |
| `GET /api/classification/sessions/{id}/record` | 판정 기록(서버 저장·처리경로 넘김용, `schemas/assessment_record.schema.json`) | |
| `GET /api/classification/facts` | 엔진이 받는 사실·허용 값 목록. 설명 읽기(자연어 → 사실 제안)는 엔진이 하지 않으며, scrap-ai 등이 이 목록의 값만 제안한다 | |

화면은 보기마다 붙은 `answers`를 돌려보내기만 한다. 그 안의 `__ui`는 화면 상태(묶음 선택 등)이고 엔진 사실이 아니다. 화면은 내용을 해석할 필요가 없다.

### 1.2 응답과 화면 요소 대응

질문 단계(`phase: "question"`) 예시(PP를 고르고 관문·배출시설까지 답한 뒤):

```json
{
 "phase": "question",
 "step": {"index": 4, "total": 6},
 "question": {
  "title": "배출할 때 이 폐기물의 상태는?",
  "helper": "합성수지(플라스틱)는 액체·반고체 상태일 때만 지정폐기물입니다. …",
  "law": {"lead": "폐기물관리법 시행령 별표 1(지정폐기물의 종류) 별표 1 제1호가목1)은(는)",
          "quote": "폐합성 수지(고체상태의 것은 제외한다)", "tail": "로 정합니다.", "is_law": true},
  "options": [{"id": "0", "label": "고체", "answers": {"physical_state": "solid"}, "remaining": 35},
              {"id": "1", "label": "액체(흐름)", "answers": {"physical_state": "liquid"}, "remaining": 28}],
  "kind": "choice"
 },
 "panel": {"label": "남은 분류번호 후보", "count": 36, "start": 272, "trail": [272, 36], "excluded": 236,
           "why": "보기마다 남는 후보 수를 함께 보여 드려요."},
 "provisional": false, "as_of": "2026-11-05"
}
```

| 화면(`src/pages/survey/…`) | 지금 읽는 값(`surveyData.js`) | 엔진 응답 |
|---|---|---|
| 단계 `{t+1} / {surveySteps.length}` | 질문 순번/3 | `step.index / step.total` (판정 단계 기준 1~6) |
| 질문 제목·도움말 | `title`, `helper` | `question.title`, `question.helper` |
| 근거 조문 상자 `sv-law` | 고정 문장 | `question.law.lead` + **`quote`(굵게)** + `tail`. `law`가 없으면 상자를 그리지 않음(지금 `y.law` 조건과 같음) |
| 보기 카드 | `options[{label, hint}]` | `question.options[{label, hint, answers, remaining}]` |
| 남은 후보 숫자·제외 수·막대·변화 | `start`, `remaining`, `TOTAL_CANDIDATES` | `panel.count`, `panel.excluded`, `panel.start`(막대 기준), `panel.trail` |
| "N개 후보를 M개로 줄이는 질문" | `start`/`remaining` | 고른 보기의 `remaining`과 `panel.count` |
| 판정 대기 화면 | 7.5초 애니메이션 | 그대로. 그동안 응답이 이미 와 있음 |
| 결과 배지 | 고정 2개 | `result.badges` |
| 분류번호·명칭 | 고정 | `result.code`, `result.name` |
| 안내 한 줄 `AgentNote` | 고정 기준일 | `result.note`(기준일 + 검토 전 잠정이면 그 문구) |
| 판정 근거 카드 | `evidenceItems[{num,title,cite,quote,outcome,reason}]` | `result.evidence[...]` 같은 이름. 카드 수는 판정 단계 수(최대 6) |
| 근거 조문 창 | 같은 항목 + 기준일 | 같은 항목 + `law_version`, `because`(해당하지 않은 이유) |
| 허용 재활용 유형 2묶음 | `freeRecycleTypes`, `analysisRecycleTypes` (`[[R코드, 이름]]`) | `result.recycle.free`, `result.recycle.analysis` 같은 모양. 이름은 `rules/r_code_labels.yaml`의 짧은 이름 |
| 처리경로 넘김 | 고정 `'51-03-01'` | `result.treatment = {waste_code, material, material_label}` — `material`은 처리경로 엔진의 키(PP·PE·PET·aluminium, 없으면 null) |
| 이해 확인 `sv-cues` | `[[항목, 값]]` 고정 | **엔진 범위 밖.** 설명 읽기를 맡는 쪽(scrap-ai)이 `/facts` 목록 기준으로 제안한 값의 이름·값을 보여 주고, 확인되면 시작할 때 `answers`로 넘김 |

화면이 라디오 한 단계만 그리므로 엔진이 질문을 이렇게 바꿔 보낸다(`question.kind`):

| kind | 내용 |
|---|---|
| `group` → `back_to_group` | 보기가 많은 질문(소재 98종)을 묶음 → 항목 두 질문으로 |
| `choice` | 일반 선택. 관문 2개(순환자원·다른 법)는 보기 하나로 합쳐 보냄 |
| `range` | 숫자 질문을 기준값 구간 보기로(예: pH "2 이하 / 2 초과 / 모름"). 판정은 구간 대표값으로 하고 기록에 `range_answers`로 남김 |
| `report` → `report_item` | 성적서: "모두 기준 이하 / 넘는 항목 있음 / 성적서 없음", 넘으면 어느 항목인지 |

오염 확인 4항목은 한 질문씩 보낸다(화면에 항목별 선택 UI가 없으므로).

## 2. UI를 바꿔야만 하는 곳

| # | 파일 | 바꿀 것 | 디자인 필요 |
|---|---|---|---|
| U1 | `src/pages/survey/SurveyPage.jsx` | `surveyData.js` 고정 데이터 대신 1.2의 응답을 그림. 보기 선택 → `/answer`에 `option.answers`, '이전' → `/undo`, 첫 진입 → `/sessions` 또는 저장된 세션 `GET`. 마크업·클래스는 그대로 | 아니요 |
| U2 | `SurveyPage.jsx` 결과 영역 | **분류번호가 없는 결과** 그리기: `result.kind`가 `test`(필요한 시험 `required_test`·`to_check`), `authority`(문의처·질의서 초안 `consult`), `not_applicable`(폐기물 아님 등), `out_of_scope`. `sv-result`를 재사용해 머리 문구·목록만 바꾸는 변형 | **예** |
| U3 | `src/features/treatment/treatment-ui.jsx` `Confirm` | 분류번호 `'51-03-01'` 고정 → `result.treatment.waste_code` | 아니요 |
| U4 | 같은 파일 `SurveyMaterial` | 재질을 다시 묻지 않고 `result.treatment.material`로 채움. 형태(`input_form`)만 묻기. `material`이 null(처리경로 엔진이 아직 모르는 재질)이면 처리경로를 열 수 없다는 안내 | 일부(안내 문구) |
| U5 | `src/pages/waste-detail/NextActionCard.jsx` '후보' | "후보 1 · 74%" 확률 표시 제거. 엔진은 확률을 내지 않음(법 조건으로 남은 후보만) → 후보 목록 + 다음 질문 | 일부 |
| U6 | `src/data/wastes.js` | 폐알칼리 `02-02-00`(별표 4에 없음), 폐흡착제 `51-08-01`(실제는 소각 비산재, 폐흡착제는 `51-11-01`) | 아니요 |

선택(하면 좋은 것)
- U7 `vite.config.js`: 로컬에서 `/api/classification/*`를 엔진으로 넘기는 프록시 한 줄(처리경로와 같은 방식).
- U8 잠정 결과 표시: 지금은 `result.note` 문장에 들어 있음. 배지·색으로 강조하려면 디자인.
- U9 질문 화면의 `remaining`이 없는 보기(관문 등)는 숫자를 숨김.

## 3. 합의가 필요한 것

| # | 주제 | 선택지 | 엔진 쪽 제안 |
|---|---|---|---|
| A1 | 운영 경로 | (a) scrap-server가 `/api/classification/*`를 엔진 서비스로 프록시 (b) 서버가 엔진 패키지를 직접 import | (a). 엔진은 상태 없는 `/evaluate`만 쓰고 저장은 서버 DB |
| A2 | 저장 주체 | 엔진 세션 SQLite vs 서버 DB | 서버 DB(기업·폐기물 단위, 인증). 엔진 세션 API는 개발·시연용으로만 |
| A3 | 숫자 입력 | 구간 보기(지금) vs 숫자 입력 UI 추가 | 분류에는 구간으로 충분. 측정값을 증빙으로 남기려면 숫자 입력 UI 필요 |
| A4 | U2 결과 화면 디자인 | 시험 필요·기관 확인·폐기물 아님 | 디자인 담당 |
| A5 | 사업장 공통 정보 | 온보딩에서 받기 vs 첫 문진에서 받기 | 온보딩의 '운영 중인 배출시설' 목록은 법의 '배출시설 허가·신고'와 다른 뜻. 온보딩에 "대기·수질·소음진동 배출시설 허가·신고 여부" 한 질문을 두거나, 첫 문진 답을 서버가 기업 정보로 저장 |
| A6 | 처리경로 재질 키 | 지금 PP·PE·PET·aluminium만 | 엔진 소재 98종 중 4종만 대응. 처리경로 쪽 키가 늘면 `rules/materials.yaml`의 `treatment_material`에 추가 |
| A7 | 잠정 결과의 쓰임 | 모든 규칙이 검토 전 → 모든 결과가 잠정 | 처리경로·업체 매칭에 잠정 결과를 그대로 넘길지, 확인 단계를 둘지 |
| A8 | 문진 첫 화면 문구 | 디자인 "(주)가천정밀 · 10인 사출 공장 …" 고정 | 서버의 기업 정보로 채움(엔진 범위 밖) |
