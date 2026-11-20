# 판정 규칙 형식 (flow/*.yaml)

판정은 **단계(stage) 파일을 번호 순서대로** 평가한다. 단계 안의 규칙은 위에서부터 평가한다.

## 단계 파일

```yaml
stage: 50_designated            # 파일 이름과 같게
title: 지정폐기물 가능성
order: 50                        # 작은 번호부터 평가
on_no_match: continue            # 어떤 규칙도 참이 아니고 막히지도 않았을 때: continue | {outcome: ...}
rules:
  - id: DES-OIL-NO-EVIDENCE      # 대문자·숫자·하이픈. 전체 파일에서 유일
    when: <조건식>
    then: {outcome: DESIGNATED_POSSIBLE}      # 또는 continue, 또는 {outcome, code, flags}
    basis:
      - unit: DEC-WASTE/별표1제6호            # knowledge/law/articles의 "문서키/단위ID"
        quote: "기름성분을 5퍼센트 이상 함유한 것을 포함하며"   # 그 단위 본문의 일부를 글자 그대로(공백 차이만 허용)
    decision: D6                 # decisions.md의 결정에 근거하면 번호(없으면 생략)
    grade: A                     # A: 조문 문언으로 정해짐 / C: decisions.md 결정에 기댐
    note: 짧은 설명(선택)
```

단계 파일은 7개다. 순서와 이름은 바꾸지 않는다.
`10_is_waste`, `20_circular`, `30_exclusion`, `40_business`, `50_designated`, `60_scope`, `70_code`

## 조건식

```yaml
{fact: material, eq: pvc}
{fact: material, in: [pp, pe, pet]}
{fact: material, ne: pvc}                 # not_in도 가능
{fact: daily_avg_kg, gte: 300}            # gt, gte, lt, lte (숫자 사실)
{fact: can_designation.registered, eq: "yes"}   # object 사실의 필드는 점으로
{fact: oil_pct_evidenced, exists: true}   # 숫자 사실에 값이 있는지
{all: [조건, 조건, ...]}
{any: [조건, 조건, ...]}
{not: 조건}
```

- `yes`, `no`는 YAML에서 불리언이 되므로 **반드시 따옴표**로 쓴다(`"yes"`).
- 사실 이름과 값은 `facts.yaml`에 있는 것만 쓴다.

## 3값 평가 (참·거짓·모름)

- 사실 값이 없거나 `unknown`이면 그 비교는 **모름**이다. 단 `{fact: X, eq: unknown}`처럼 모름을 직접 묻는 비교는 참·거짓으로 정해진다.
- `exists`는 항상 참·거짓으로 정해진다.
- `all`: 하나라도 거짓이면 거짓, 모두 참이면 참, 그 외 모름. `any`: 하나라도 참이면 참, 모두 거짓이면 거짓, 그 외 모름. `not`: 참↔거짓, 모름은 모름.

## 단계 평가

1. 규칙을 위에서부터 본다. 조건이 **참**인 첫 규칙의 `then`을 적용한다.
   - `then`이 `continue`면 다음 단계로 간다.
   - `then`이 `{outcome: ...}`면 판정을 끝낸다.
2. 참인 규칙에 닿기 전에 조건이 **모름**인 규칙을 만나면 그 단계는 **막힘**이다. 판정은
   `INSUFFICIENT_INFO`로 끝나고, 그 규칙에서 모름이었던 사실들을 `blocking_facts`로 낸다.
   그래서 "모름이면 보수적으로 멈춘다" 같은 정책은 모름을 직접 묻는 규칙(`eq: unknown`)을 앞에 두어 표현한다.
3. 모든 규칙이 거짓이면 `on_no_match`를 따른다.
4. 7개 단계를 모두 `continue`로 통과하면 `INSUFFICIENT_INFO`다(규칙 누락으로 보고).

## 함께 내는 파일

- `undecided.md`: 법령과 decisions.md로 정할 수 없어 임의로 정하지 않은 판단 목록(무엇이, 왜 안 정해지는지, 후보 안).
