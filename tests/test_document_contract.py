"""서류 읽기 계약(document-extraction-v1): 문서의 JSON 예시가 모델에 맞고, Fact로 옮겨진다."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.document import (
    DocumentExtractionRequest,
    DocumentExtractionResult,
    ExtractedFactItem,
    to_fact_records,
)
from app.domain.facts import FactStatus
from app.domain.ranges import NumRange, range_satisfies

DOC = Path(__file__).parent.parent / "docs" / "document-extraction-contract.md"


def _examples() -> list[dict]:
    text = DOC.read_text(encoding="utf-8")
    return [json.loads(b) for b in re.findall(r"```json\n(.*?)\n```", text, re.S)]


@pytest.fixture(scope="module")
def examples() -> tuple[dict, dict, dict]:
    ex = _examples()
    assert len(ex) == 3
    return ex[0], ex[1], ex[2]


def test_request_example_valid(examples):
    req = DocumentExtractionRequest.model_validate(examples[0])
    assert [f.key for f in req.requested_facts] == ["ph", "oil_content_pct", "leach_pb"]
    assert req.content.text_pages[1].page == 2


def test_test_report_to_facts(examples):
    res = DocumentExtractionResult.model_validate(examples[1])
    facts = {f.key: f for f in to_fact_records(res, "doc-1")}
    assert set(facts) == {"ph", "oil_content_pct", "leach_pb"}
    for f in facts.values():
        assert f.status is FactStatus.EVIDENCED
        assert f.source_type == "DOCUMENT"
        assert f.source_ref == "doc-1"
        assert f.quote
    assert facts["ph"].value == 7.2
    assert facts["oil_content_pct"].value == 3.5
    nd = facts["leach_pb"]
    assert nd.value == NumRange(hi=0.01, hi_inc=False)
    assert "불검출" in (nd.note or "")
    # ND는 검출한계 미만 구간: 0.3 기준은 만족, 0.005 기준은 판단 보류
    assert range_satisfies(nd.value, "lt", 0.3) is True
    assert range_satisfies(nd.value, "lt", 0.005) is None


def test_msds_to_facts(examples):
    res = DocumentExtractionResult.model_validate(examples[2])
    (f,) = to_fact_records(res, "doc-2")
    assert (f.key, f.value, f.status) == ("toxic_chemical_discard", True, FactStatus.EVIDENCED)
    assert f.source_ref == "doc-2"
    assert res.warnings[0].code == "NO_SIGNATURE_OR_SEAL"


def test_non_found_makes_no_fact(examples):
    raw = json.loads(json.dumps(examples[1]))
    raw["facts"][0] = {"key": "ph", "status": "NOT_FOUND"}
    raw["facts"][1] = {"key": "oil_content_pct", "status": "AMBIGUOUS", "note": "3.5 / 4.1"}
    res = DocumentExtractionResult.model_validate(raw)
    assert [f.key for f in to_fact_records(res, "doc-1")] == ["leach_pb"]


def test_comparator_becomes_range():
    item = ExtractedFactItem(
        key="leach_cu",
        status="FOUND",
        value=0.1,
        comparator="LT",
        value_raw="<0.1",
        page=1,
        quote="구리 <0.1 mg/L",
    )
    res = DocumentExtractionResult(
        document_id="d", detected_doc_type="TEST_REPORT", doc_type_confidence=0.9, facts=[item]
    )
    (f,) = to_fact_records(res, "d")
    assert f.value == NumRange(hi=0.1, hi_inc=False)


@pytest.mark.parametrize(
    "patch",
    [
        {"status": "MAYBE"},  # 모르는 상태
        {"quote": None},  # FOUND인데 quote 없음
        {"page": None},  # FOUND인데 page 없음
        {"value": None},  # FOUND인데 값 없음
        {"below_detection_limit": True, "value": None, "detection_limit": None},  # ND인데 한계 없음
        {"below_detection_limit": True, "detection_limit": 0.01},  # ND인데 value도 있음
        {"unknown_field": 1},  # 모르는 필드
        {"comparator": "LT", "value": True},  # 숫자 아닌 값에 부등호
    ],
)
def test_invalid_items_rejected(patch):
    base = {"key": "ph", "status": "FOUND", "value": 7.2, "page": 1, "quote": "pH 7.2"}
    with pytest.raises(ValidationError):
        ExtractedFactItem.model_validate({**base, **patch})


def test_not_found_with_value_rejected():
    with pytest.raises(ValidationError):
        ExtractedFactItem(key="ph", status="NOT_FOUND", value=7.2)


def test_request_needs_content_and_valid_sha(examples):
    raw = json.loads(json.dumps(examples[0]))
    raw["content"] = {}
    with pytest.raises(ValidationError):
        DocumentExtractionRequest.model_validate(raw)
    raw = json.loads(json.dumps(examples[0]))
    raw["document"]["sha256"] = "xyz"
    with pytest.raises(ValidationError):
        DocumentExtractionRequest.model_validate(raw)


def test_unknown_doc_type_rejected(examples):
    raw = json.loads(json.dumps(examples[1]))
    raw["detected_doc_type"] = "RECEIPT"
    with pytest.raises(ValidationError):
        DocumentExtractionResult.model_validate(raw)
