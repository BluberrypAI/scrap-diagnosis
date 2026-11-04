# 실제 사례 + 가정 상황 시험

기준일 2026-11-05, strict 해제. 가정은 사례 원문에 없는 사실을 채운 것이다. CONSULT는 근거가 해설·질의회신뿐이라 계산기가 결론 대신 문의처·질의서 초안을 낸 경우다.

| 사례 | 상황 | 단계 | 기관 답 | 계산기 | 판정 | 가정 |
|---|---|---|---|---|---|---|
| MOE25-234 | 미강(쌀겨)을 사료 원료로 | S0 | WASTE | WASTE | **CORRECT** | 도정 공장에서 필요 없게 된 부산물로 다른 업체에 넘김(회신 전제) |
| GUIDE23-133-01 | 납품용 목재 팔레트를 수거해 같은 용도로 반복 사용 | S0 | NOT_WASTE | NOT_WASTE | **CORRECT** | 팔레트를 계속 운반 용도로 쓰므로 '아직 필요한 물건'으로 답함 |
| COURT-2001도70 | 필요 없게 된 물질을 재활용 원료로 공급 | S0 | WASTE | WASTE | **CORRECT** | 재투입·순환자원 인정 없음 |
| GUIDE23-050-02 | 동제련 슬래그를 밀폐 연속공정으로 시멘트·골재 원료에 투입 | S0 | NOT_WASTE | 문의 안내 — 참고 결론 NOT_WASTE | **CONSULT(참고 일치)** | 발생시설에서 별도 가공 없이 연속공정으로 시멘트·골재 공정에 투입(질의 전제) |
| HWP08-M-1-04 | 가정 방문 간호에서 나온 의료폐기물 | S2 | HOUSEHOLD | HOUSEHOLD | **CORRECT** | 가정(재택)에서 발생, 하루 1kg. 사용자가 종류를 '의료폐기물'로 고름 |
| WONJU26-52 | 크롬산 폐수 pH 2 | S3 | DESIGNATED | DESIGNATED | **CORRECT** | 수질오염방지시설로 보내지 않고 위탁(=폐기물관리법 적용) |
| WONJU26-18 | 폐유가 조금 남은 드럼통 | S3 | DESIGNATED | DESIGNATED | **CORRECT** | 금속 드럼이라 종류 '그 밖', 기름성분 10%로 가정 |
| WONJU26-18 | 폐유가 조금 남은 드럼통 | S3 | DESIGNATED | NEED_TEST at S3 | **STOPPED** | 변형: {"oil_content_pct": "UNKNOWN"} |
| WONJU26-62 | 유기용제가 바닥에 묻은 빈 드럼 | S3 | DESIGNATED | 문의 안내 — 참고 결론 DESIGNATED | **CONSULT(참고 일치)** | 사용자가 '빈 금속 드럼'이라 종류를 '그 밖'으로 답함. 잔류물 질문에 '유기용제가 남아 있음' |
| WONJU26-62 | 유기용제가 바닥에 묻은 빈 드럼 | S3 | DESIGNATED | NOT_DESIGNATED | **WRONG(입력 오류)** | 변형: {"designated_residue": false} — 사용자가 잔류물을 '없음'으로 잘못 답한 경우(입력 오류 시연) |
| HWP08-D-1-02 | 과산화수소(pH 2.5)가 묻은 PE 용기 | S3 | DESIGNATED | 문의 안내 — 참고 결론 DESIGNATED | **CONSULT(참고 일치)** | 빈 플라스틱 용기. 잔류물 질문에 '유해화학물질(과산화수소)이 묻어 있음' |
| HWP08-D-1-02 | 과산화수소(pH 2.5)가 묻은 PE 용기 | S3 | DESIGNATED | NOT_DESIGNATED | **WRONG(입력 오류)** | 변형: {"designated_residue": false} — 사용자가 잔류물을 '없음'으로 잘못 답한 경우(입력 오류 시연) |
| HWP08-D-1-01 | 철거한 슬레이트(석면 1% 이상) — 2008년 회신 | S3 | NOT_DESIGNATED | DESIGNATED | **WRONG** | 석면 5%. 회신 당시(2008) 법령 기준 답 |
| HWP08-D-1-16 | 지붕 슬레이트 폐석면 | S3 | DESIGNATED | DESIGNATED | **CORRECT** | 석면 5% |
| HWP08-D-1-04 | 변전실 변압기 절연유 | S3 | DESIGNATED | DESIGNATED | **CORRECT** | PCB 분석 결과 기준 미만으로 확인됨 |
| HWP08-D-1-06 | 건설오니·도로청소 폐토사 | S3 | NOT_DESIGNATED | NOT_DESIGNATED | **CORRECT** | 기름·PCB·유해화학물질 없음 |
| HWP08-D-1-15 | 압수된 유사석유제품 | S3 | DESIGNATED | DESIGNATED | **CORRECT** | 연료유로 보고 종류 '폐유'를 고름 |
| HWP08-M-1-08 | 혈액이 든 채혈 튜브(병원) | S3 | DESIGNATED | DESIGNATED | **CORRECT** | 배출시설 없는 의원, 하루 50kg |
| REC17-008-2 | 폐축전지 분리 시 나온 폐황산 | S3 | DESIGNATED | DESIGNATED | **CORRECT** | pH 0.5, 사용자가 폐황산 번호를 고름 |
| REC17-008-2 | 폐축전지 분리 시 나온 폐황산 | S4 | 02-01-02 | 02-01-02 | **CORRECT** | pH 0.5, 사용자가 폐황산 번호를 고름 |
| REC17-008-2 | 폐축전지 분리 시 나온 폐황산 | S5 | ALLOWED_TYPES | ALLOWED_TYPES | **CORRECT** | pH 0.5, 사용자가 폐황산 번호를 고름 |
| WONJU26-63 | 다른 성분을 함유한 폐황산 | S4 | 02-01-02 | 02-01-02 | **CORRECT** | pH 1 |
| WONJU26-56-Q3 | 인산·과산화수소 등 혼합 폐산 | S4 | 02-01-99 | 02-01-99 | **CORRECT** | pH 1, 염산·황산·질산·불산·LCD 폐산에 해당하지 않음 |
| HWP08-D-1-11 | 기름공장의 폐흡착제 | S4 | 03-08-01 | 03-08-01 | **CORRECT** | 기름성분 20%, 용출 물질은 기준 미만 |
| GUIDE23-120-01 | 용접잔재물(지정폐기물 아님) | S4 | 51-04-99 | 51-04-99 | **CORRECT** | 용출 기준 미만 |
| GUIDE23-129-01 | 사골 국물에서 분리한 기름 | S4 | 51-16-00 | 51-16-00 | **CORRECT** | 식품 공장(배출시설 있음) |
| REC17-007-2 | 시멘트 제조공정 분진 | S4 | 51-05-02 | 51-05-02 | **CORRECT** | 집진기 포집 분진, 용출 기준 미만 |
| REC17-007-2 | 시멘트 제조공정 분진 | S5 | ALLOWED_TYPES | ALLOWED_TYPES | **CORRECT** | 집진기 포집 분진, 용출 기준 미만 |
| REC17-006-2 | 교량 철거 EPS 블록 | S4 | 51-03-06 | 51-03-06 | **CORRECT** | (건설 현장이지만) 사업장폐기물로 가정 |
| REC17-006-2 | 교량 철거 EPS 블록 | S5 | ALLOWED_TYPES | ALLOWED_TYPES | **CORRECT** | (건설 현장이지만) 사업장폐기물로 가정 |
| REC17-006-1 | 전자제품 공장의 폐수처리오니 | S4 | 51-01-08 | 51-01-08 | **CORRECT** | 고시된 오니 발생시설 아님, 유기성 |
| REC17-006-1 | 전자제품 공장의 폐수처리오니 | S5 | ALLOWED_TYPES | ALLOWED_TYPES | **CORRECT** | 고시된 오니 발생시설 아님, 유기성 |
| REC17-039-1 | 굴·바지락 패각 — 2016년 회신 | S4 | 51-17-04 | 51-17-04 | **CORRECT** | 수산물 가공 공장. 회신 당시(2016) 법령 기준 답 |
| REC17-039-1 | 굴·바지락 패각 — 2016년 회신 | S5 | RESTRICTED | ALLOWED_TYPES | **WRONG** | 수산물 가공 공장. 회신 당시(2016) 법령 기준 답 |

합계: CONSULT(참고 일치) 3, CORRECT 26, STOPPED 1, WRONG 2, WRONG(입력 오류) 2
