"""법적 판단과 별도로, 현재 남은 판단을 구분할 질문을 선택한다."""
from __future__ import annotations


def order_questions(kb, stage_id, cards, answers):
    from .engine import Answer, FALSE, eval_stage

    def outcomes(st):
        keys = set()
        for e in st["evals"].values():
            if e.status == FALSE:
                continue
            if stage_id == "S3" and e.rule.concludes == "DESIGNATED":
                matched = [k for k in kb.s4_map["designated"] if e.rule.id.startswith(k)]
                for p in kb.s4_map["designated"].get(max(matched, key=len), []) if matched else ["unmapped"]:
                    keys.add(("DESIGNATED", p))
            else:
                keys.add((e.rule.concludes,))
        return len(keys)

    def worst(card):
        f = kb.facts[card["fact"]]
        if f["type"] == "bool":
            values = [True, False]
        elif f["type"] == "enum":
            values = list(card.get("allowed_values") or f["values"])
        else:
            thresholds = {x["value"] for x in card.get("thresholds", [])}
            values = {0.0}
            for x in thresholds:
                delta = max(abs(x) * 1e-6, 1e-9)
                values.update([max(0, x - delta), x, x + delta])
        return max((outcomes(eval_stage(kb, stage_id, {**answers, card["fact"]: Answer("VALUE", (v,))}))
                    for v in values), default=0)

    anchor = {"S0": "material_fate", "S3": "waste_kind"}.get(stage_id)
    ranked = []
    for index, card in enumerate(cards):
        state = {"MISSING": 0, "UNKNOWN": 1, "CONFLICT": 2}.get(card["state"], 3)
        first = card["fact"] == anchor and state == 0
        # 동률이면 기존 질문 순서를 사용한다. 근거 없는 확률 가중치는 두지 않는다.
        cost = {"USER": 0, "DOCUMENT": 1, "TEST": 2}[card["cost"]] if stage_id == "S3" else 0
        score = (state, 0 if first else 1, cost, 0 if first else worst(card), index)
        ranked.append((score, card))
    return [card for _, card in sorted(ranked, key=lambda x: x[0])]
