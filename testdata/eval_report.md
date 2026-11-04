# 정답셋 평가 결과

사례 178건 중 단계 기대값이 있는 판정 104개 (EVAL 89개). 규칙 DB `rules-5d816609d9ad`, 기준일 2026-11-05(현행 법령으로 채점), strict 해제(규칙 검토 여부와 무관하게 결론만 비교).

## EVAL — 단계별
| 구분 | CORRECT | IN_RANGE | CORRECT_STOP | STOPPED | WRONG | OUT_OF_RANGE | OVERCONFIDENT | NOT_COMPARABLE |
|---|---|---|---|---|---|---|---|---|
| S0 | 0 | 0 | 5 | 15 | 0 | 0 | 0 | 0 |
| S1 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |
| S2 | 0 | 0 | 5 | 2 | 0 | 0 | 0 | 0 |
| S3 | 0 | 0 | 18 | 11 | 0 | 0 | 1 | 0 |
| S4 | 0 | 0 | 0 | 12 | 0 | 0 | 0 | 1 |
| S5 | 8 | 0 | 0 | 0 | 1 | 0 | 0 | 8 |

## DEV — 단계별 (규칙 작성 때 본 사례, 참고용)
| 구분 | CORRECT | IN_RANGE | CORRECT_STOP | STOPPED | WRONG | OUT_OF_RANGE | OVERCONFIDENT | NOT_COMPARABLE |
|---|---|---|---|---|---|---|---|---|
| S0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 |
| S2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| S3 | 1 | 0 | 2 | 2 | 0 | 0 | 0 | 0 |
| S4 | 0 | 0 | 0 | 6 | 0 | 0 | 0 | 0 |

## 전체 — 회신 시기별
회신 당시 법령이 현행과 다를 수 있으므로 오래된 사례의 불일치는 법령 변경 때문일 수 있다.

| 구분 | CORRECT | IN_RANGE | CORRECT_STOP | STOPPED | WRONG | OUT_OF_RANGE | OVERCONFIDENT | NOT_COMPARABLE |
|---|---|---|---|---|---|---|---|---|
| 2016~2022 | 8 | 0 | 0 | 11 | 1 | 0 | 0 | 3 |
| 2023~ | 1 | 0 | 18 | 25 | 0 | 0 | 0 | 6 |
| ~2015 (재활용 유형 제도 이전) | 0 | 0 | 12 | 18 | 0 | 0 | 1 | 0 |

## 검토가 필요한 판정 (WRONG / OUT_OF_RANGE / OVERCONFIDENT)

- `HWP08-D-1-14` S3 OVERCONFIDENT — 기관 "UNDECIDED" / 계산기 DESIGNATED (2008 회신·선고일, EVAL)
- `REC17-039-1` S5 WRONG — 기관 "RESTRICTED" / 계산기 계산기 ALLOWED_TYPES (2016 회신·선고일, EVAL)

## 보조 평가 — 언급 없는 공통 위험을 '없음'으로 가정 (S0~S3)
가정: {'circular_resource_recognized': False, 'direct_reinput': False, 'continuous_feedstock': False, 'pcb_possible': False, 'toxic_chemical_discard': False, 'designated_residue': False} + 기름 관련 종류가 아니면 oil_presence=none. 계산기 실제 동작이 아니라 규칙 논리만 보는 참고 지표다.

| 구분 | CORRECT | IN_RANGE | CORRECT_STOP | STOPPED | WRONG | OUT_OF_RANGE | OVERCONFIDENT | NOT_COMPARABLE |
|---|---|---|---|---|---|---|---|---|
| S0 | 3 | 0 | 5 | 12 | 0 | 0 | 0 | 0 |
| S1 | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 |
| S2 | 0 | 0 | 5 | 2 | 0 | 0 | 0 | 0 |
| S3 | 1 | 0 | 17 | 10 | 0 | 0 | 2 | 0 |

가정 평가에서 검토가 필요한 판정:

- `WONJU26-03` S3 OVERCONFIDENT — 기관 "UNDECIDED" / 계산기 NOT_DESIGNATED (EVAL)
- `HWP08-D-1-14` S3 OVERCONFIDENT — 기관 "UNDECIDED" / 계산기 DESIGNATED (EVAL)
