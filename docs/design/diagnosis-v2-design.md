# 문진 엔진 v2 설계서

기준: `feat/diagnosis-v2`(2026-11-20). 세부 규약은 [API 계약](../api/server-engine-contract.md), 해석 결정은 [decisions.md](../../knowledge/flow/decisions.md)에 있다.

## 1. 범위와 원칙

| 항목 | 내용 |
|---|---|
| 대상 | PP·PE·PET(51-03-01 폐합성수지류, 51-03-07 플라스틱폐포장재), 알루미늄 캔(51-29-03 폐금속캔류) |
| 지정폐기물 | "가능성"까지만 판단(DESIGNATED_POSSIBLE) |
| 범위 밖 | "범위 밖 · 지원 예정"으로만 안내, 후보 코드는 trace에만 |
| 결과 8종 | NOT_WASTE, CIRCULAR_RESOURCE, EXCLUDED, HOUSEHOLD, DESIGNATED_POSSIBLE, OUT_OF_SCOPE, GENERAL(번호), INSUFFICIENT_INFO |

원칙
- **판정은 규칙 엔진만.** 규칙은 조문 단위 근거와 함께 YAML로 두고 골든셋으로 검증한다.
- **LLM은 제안·설명·문장만.** 사실 후보는 코드 검사기를 통과해야 기록되고, 무엇을 물을지는 코드가 정한다.
- **법령은 API로만 받는다.** 손으로 옮기지 않는다.

## 2. 전체 구조

```mermaid
flowchart LR
  W[scrap-web<br/>문진 화면] -->|/api/v1/diagnosis| S[scrap-server<br/>로그인·기업·중계·업체 추천]
  S -->|/internal/v1<br/>토큰 + 기업 ID| API
  subgraph E[scrap-diagnosis 엔진]
    API[API] --> SV[문진 서비스<br/>답 검증·턴 계산·서류]
    SV --> PL[다음 질문 계산기<br/>planner.py]
    PL --> FL[규칙 실행기<br/>flow.py]
    SV --> LLM[LLM 단계<br/>추출·agent·문장]
    SV --> DB[(DB<br/>사실 기록·대화·판정·서류)]
    K[(knowledge/<br/>법령·골든셋·규칙·계획)] --> PL
    K --> FL
    K --> LLM
  end
  S -->|인계 객체 diagnosis-handoff-v1| R[업체 추천<br/>서버 공정 자료]
```

## 3. 지식 구축 (knowledge/)

```mermaid
flowchart TD
  T[law/targets.yaml<br/>수집 대상, 사람이 정함] --> C[tools/collect_law.py<br/>국가법령정보 OPEN API]
  C --> A[law/articles/*.json<br/>조·항·호·목, 별표 행 단위]
  C --> M[law/manifest.yaml<br/>원본 SHA-256·재조회 식별자]
  A --> G[cases/ 골든셋 98건<br/>결정표 → 상황 서술 → 이중 주석 → 동결]
  A --> F[flow/ 판정 규칙 7단계<br/>규칙마다 basis: 조문 단위 + 인용문]
  G -->|채점·mutation| F
  F --> P[flow/plan.yaml 문진 계획<br/>facts.yaml 사실 카탈로그<br/>outcomes.yaml 결과 안내<br/>glossary.yaml 용어집]
```

| 단계 | 산출물 | 검증 |
|---|---|---|
| 법령 적재 | 법령 7·고시 2·해석례 2, 쓰는 조문만 + 별표 4의3(재활용 유형) | 원본 해시, 재수집 시 diff |
| 골든셋 v3 | 98건, 등급 A/C, 동결 해시 `e6ca9d60fe90` | 블라인드 이중 주석 κ 1.00, mutation 152/152 검출 |
| 판정 규칙 | 두 모델(opus·sonnet) 독립 초안 → 비교 → 판정 조정 → 최종 | 골든 98/98 |

## 4. 판정 흐름 (app/engine/flow.py)

```mermaid
flowchart TD
  S10[10 폐기물인가<br/>내보내는가] -->|아니오| NW[NOT_WASTE]
  S10 --> S20[20 순환자원인가<br/>인정서·캔 고시 준수]
  S20 -->|예| CR[CIRCULAR_RESOURCE]
  S20 --> S30[30 다른 법 대상인가<br/>폐기물관리법 제3조]
  S30 -->|예| EX[EXCLUDED]
  S30 --> S40[40 사업장 폐기물인가<br/>배출시설·300kg·공공시설 등]
  S40 -->|아니오| HH[HOUSEHOLD]
  S40 --> S50[50 지정 가능성<br/>잔류물·기름 5%·약품]
  S50 -->|가능성| DP[DESIGNATED_POSSIBLE]
  S50 --> S60[60 범위 안인가<br/>재질·발포·어망·PVC 등]
  S60 -->|밖| OS[OUT_OF_SCOPE]
  S60 --> S70[70 분류번호<br/>캔 / 포장재 / 그 외 합성수지]
  S70 --> GEN[GENERAL 51-29-03 · 51-03-07 · 51-03-01]
```

- 3값 논리(Kleene): 참·거짓·모름. 단계 안은 첫 참 규칙을 적용하고, 참에 닿기 전에 모름을 만나면 그 자리에서 멈춘다(INSUFFICIENT_INFO + blocking_facts).
- 아직 묻지 않음(UNASKED)과 모른다고 답함(unknown)을 구분한다. UNASKED는 어떤 비교든 모름이다.
- 구간 값(불검출, "0.5 미만")은 구간 전체가 조건을 만족하면 참, 전혀 아니면 거짓, 걸치면 모름이다.

## 5. 문진 계획과 다음 질문 (app/engine/planner.py)

```mermaid
flowchart LR
  A[답한 값] --> B[+ 기본값 assume<br/>+ 자동 채움 derive<br/>+ 나머지 UNASKED]
  B --> C{판정 실행}
  C -->|결론 또는<br/>모름 답으로 막힘| D[끝]
  C -->|UNASKED로 막힘| E[모름 규칙이 기다리는 사실만 남김<br/>관련성 가지치기]
  E --> F[plan.yaml 순서에서<br/>첫 질문 선택]
```

| 계획 요소 | 예 |
|---|---|
| 순서 | 재질 → 형태 → 발포·어망 → 포장 → 캔 내용물 → 오염 → 기름 성적서 → 법 적용 → 순환자원 → 캔 고시 → 사업장 |
| derive(자동 채움) | 형태를 고르면 고체, 알루미늄 + 캔이면 캔 재질 |
| assume(기본값, D17) | 내보내는 물질로 본다. 결과에 가정으로 표시, 보드에서 고침 |
| always | 형태: 판정과 무관해도 업체 추천에 넘기려고 묻는다 |
| ask_if / options_by / variants | 조건부 질문, 재질별 형태 선택지, 범위 안 고체면 방사성 오염만 묻기(D16) |
| 묶음(group) | 모두 해당 없음 / 체크한 항목만 / 하나씩. 체크한 항목은 값이 하나면 바로 기록, 여럿이면 '해당 없음'을 뺀 세부 질문 |
| scope: company | 사업장 질문 5개는 기업별로 기억해 다음 건에 미리 채움 |
| why·basis | 질문마다 이유 한 줄 + 그 답을 기다리는 규칙의 근거 조문(펼침) |

## 6. 한 턴 처리

```mermaid
sequenceDiagram
  participant U as 사용자(웹·서버 경유)
  participant SV as 문진 서비스
  participant X as 추출 AI
  participant G as 검사기(코드)
  participant AG as 질의응답 agent
  participant PL as 계획·규칙 엔진
  U->>SV: 버튼(quick_reply) 또는 말(text)
  alt 버튼
    SV->>SV: 값 검증 → 사실 기록(append-only)
  else 말
    SV->>SV: 식별 정보 가리기(실패하면 AI로 안 보냄)
    SV->>X: 지금 질문·받을 수 있는 사실·말
    X-->>SV: 의도 + 사실 후보 [{key, value, certainty, quote}]
    SV->>G: 카탈로그 값? 근거 문구가 말에 있나? 서류 전용 아닌가?
    G-->>SV: 바로 기록 / 확인 버튼(추측·오염 '없음') / 버림
    opt 문진 질문·무관한 말
      SV->>AG: 질문(무관한 말은 가드레일 모드)
      AG->>AG: 읽기 전용 도구 선택(최대 3회)
      AG-->>SV: 답 + 도구가 준 출처만
    end
  end
  SV->>PL: 유효 사실 전체로 처음부터 다시 판정
  PL-->>SV: 다음 질문 / 서류 요청 / 결론
  SV-->>U: TurnResponse(ui.question·board·result, assist)
```

턴 분기: `ASK_FACT`(질문) · `REQUEST_EVIDENCE`(서류 요청) · `FINAL_REVIEW`(결론, 확정 가능) · `UNSUPPORTED`(모름 답으로 막힘). 확인 카드는 `sub_branch: CONFIRM_GUESS`.

## 7. LLM 단계 (app/llm/)

| 구성 | 하는 일 | 코드가 지키는 것 |
|---|---|---|
| 추출 AI (`extract.py`) | 의도 5종, 사실 후보, 묶음 '모두 해당 없음'. 건 메모도 같은 흐름 | 검사기 통과분만 기록, 추측·오염 '없음'은 확인 버튼 |
| 질의응답 agent (`assist.py`, `tools.py`) | 도구 `rule_basis`·`search_law`·`lookup_term`·`case_state`를 스스로 골라 답 | 읽기 전용, 호출 3회 상한, 도구가 준 출처만 인용 |
| 가드레일 | 잡담·문진 밖 요청·역할 바꾸기 시도 → 짧게 받고 문진으로 | 기록 없음, 500자 제한, 분류번호 금지, 실패 시 고정 문장 |
| 문장 다듬기 (`phrase.py`) | 턴 message만 쉬운 말로 | 카드 문장·선택지 고정, 원문에 없는 숫자 금지, 같은 질문 1회 호출 |
| 가리기 (`redact.py`, 복원) | 전화·이메일·사업자번호·주소 → 토큰 | 남으면 AI로 보내지 않음, Trace엔 해시만 |

워크플로(①~⑤)와 agent(⑥)를 나눈 하이브리드다. 판정 경로는 결정적이고, 질의응답만 LLM이 자료 조회 경로를 정한다.

## 8. 서류(성적서)

```mermaid
stateDiagram-v2
  [*] --> 서류요청: 기름 묻음 → REQUEST_EVIDENCE
  서류요청 --> UNVERIFIED: 업로드(직접 적은 값 + 표 자동 읽기)
  서류요청 --> 모름: '서류가 없어요' → DESIGNATED_POSSIBLE
  UNVERIFIED --> APPLIED: 서버 검수 적용 → EVIDENCED 사실 → 다시 판정
  UNVERIFIED --> REJECTED: 검수에서 거절
  APPLIED --> REVOKED: 효력 해제·파일 교체 → 다시 서류 요청
```

- 서류 전용 사실(기름성분 함량)은 버튼으로 받지 않는다(422).
- 표 자동 읽기: 글자 PDF는 엔진 안(pdfplumber), 스캔본·사진은 Azure Document Intelligence(기본 꺼짐). `app/reading/`은 기존 엔진에서 복원.

## 9. 확정과 인계

| 출력 | 내용 |
|---|---|
| 인계 객체 `diagnosis-handoff-v1` | result_type·waste_code·category·route_guidance.action, facts(형태 포함), basis, evidence, assumptions, recycling |
| 재활용 유형 `recycling-types-v1` | 별표 4의3 행(API 수집), free·analysis 유형, 출처·체크섬 |
| outcome → action | GENERAL→RECOMMEND_ROUTE, NOT_WASTE·CIRCULAR→NO_ROUTE_NEEDED, EXCLUDED→REFER_OTHER_LAW, HOUSEHOLD→REFER_MUNICIPALITY, DESIGNATED_POSSIBLE→NEEDS_TEST, OUT_OF_SCOPE→MANUAL_CLASSIFICATION |

서버 `context_from_handoff`로 PP·PET·알루미늄 캔이 업체 후보 조회(`ready`)까지 가고, 형태는 인계 객체에서 바로 읽힌다.

## 10. 저장

| 테이블 | 용도 |
|---|---|
| companies, company_facts | 기업(서버 ID로 자동 생성), 사업장 답 기억 |
| cases | 상태·kb_version·펼친 묶음·확인 대기·질문 수(낙관적 잠금) |
| fact_records | 사실 이력 append-only(CLAIMED·EVIDENCED·DECLARED_UNKNOWN·RETRACTED, 출처·근거 문구) |
| messages, trace_events | 대화(assist 포함), 턴마다 입력·판정·AI 호출 기록. 확정 시 trace 불변 |
| verdicts | 확정 버전, 인계 객체. reopen 표시만 허용 |
| documents, document_values | 서류 메타(원문 미저장), 값 후보·검수 상태 |

마이그레이션 Alembic 0001~0003. 규칙이 바뀌면 진행 중 건은 `KB_CHANGED` → rebase.

## 11. 검증 결과

| 항목 | 결과 |
|---|---|
| 판정 규칙 vs 골든셋 | 98/98 |
| 가상 문진(버튼만) | 결론 98/98, 평균 8.3문항 |
| 골든 98건 API 끝까지 문진(서류 흐름 포함) | 통과 |
| 실제 AI 98건(메모 = 상황 서술) | 결론 98/98, 버튼 7.9 → 4.9, 추출 정밀도 98.5%·재현율 72%, 오염 '없음' 오답 0, 지연 중앙값 6.0초 ※ 질문 분리(D16·D17) 전 계획으로 측정 |
| 완벽 추출 가정(oracle) | 결론 98/98, 버튼 2.6 |
| 테스트 | 201개 통과(서류 읽기 복원분 103개 포함) |
