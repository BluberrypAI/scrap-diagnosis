"""서류 읽기(document-extraction-v1) 계약 모델.

구현이 아니라 입출력 계약이다. 서류에서 사실을 읽어내는 구성요소(OCR·LLM 등)는 나중에 붙이고,
이 모듈은 그 구성요소가 받을 것(DocumentExtractionRequest)과 돌려줄 것(DocumentExtractionResult)의
형태, 그리고 결과를 엔진의 Fact로 옮기는 순수 함수 to_fact_records만 정의한다. LLM 호출·I/O 없음.

계약 본문: docs/document-extraction-contract.md
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.engine.ranges import NumRange
from app.reading.tables import CellRef, FootnoteRef, TableGrid

CONTRACT = "document-extraction-v1"

ScalarValue = bool | int | float | str


class DocType(StrEnum):
    """서류 종류. 카탈로그 evidence_type과 같은 값 + 판별 불가(OTHER)."""

    TEST_REPORT = "TEST_REPORT"
    MSDS = "MSDS"
    EQUIPMENT_NAMEPLATE = "EQUIPMENT_NAMEPLATE"
    EMISSION_FACILITY_PERMIT = "EMISSION_FACILITY_PERMIT"
    CIRCULAR_RESOURCE_CERTIFICATE = "CIRCULAR_RESOURCE_CERTIFICATE"
    WASTE_DISCHARGE_REPORT = "WASTE_DISCHARGE_REPORT"
    CONSTRUCTION_CONTRACT = "CONSTRUCTION_CONTRACT"
    FACILITY_NOTIFICATION = "FACILITY_NOTIFICATION"
    DOCUMENT = "DOCUMENT"  # 카탈로그의 일반 증빙 유형
    OTHER = "OTHER"  # 읽었지만 위 어느 것도 아님(출력 전용)


class ItemStatus(StrEnum):
    FOUND = "FOUND"  # 값을 찾았다 → 엔진 검증을 통과하면 EVIDENCED
    NOT_FOUND = "NOT_FOUND"  # 서류에 그 항목이 없다
    UNREADABLE = "UNREADABLE"  # 항목은 있으나 글자를 읽을 수 없다(스캔 품질 등)
    AMBIGUOUS = "AMBIGUOUS"  # 후보가 여럿이거나 해석이 갈린다(시료 여러 개 등)


class Comparator(StrEnum):
    EQ = "EQ"
    LT = "LT"
    LTE = "LTE"
    GT = "GT"
    GTE = "GTE"


class WarningCode(StrEnum):
    SAMPLE_DATE_OLD = "SAMPLE_DATE_OLD"  # 시료 채취일이 오래됨
    UNIT_CONVERSION_FAILED = "UNIT_CONVERSION_FAILED"  # 단위 환산 불가
    UNIT_ASSUMED = "UNIT_ASSUMED"  # 단위를 가정해 환산함(예: ppm→mg/L)
    DOC_TYPE_MISMATCH = "DOC_TYPE_MISMATCH"  # 힌트와 판별 종류 불일치
    DIFFERENT_SUBJECT = "DIFFERENT_SUBJECT"  # 다른 시료·회사로 보임
    MULTIPLE_SAMPLES = "MULTIPLE_SAMPLES"  # 한 서류에 시료가 여럿
    NO_SIGNATURE_OR_SEAL = "NO_SIGNATURE_OR_SEAL"  # 서명·직인 없음
    LOW_QUALITY = "LOW_QUALITY"  # 읽기 품질 낮음
    PARTIAL_DOCUMENT = "PARTIAL_DOCUMENT"  # 일부 쪽만 있는 듯함
    METHOD_MISMATCH = "METHOD_MISMATCH"  # 시험방법이 카탈로그 기준과 다름
    # 표 인식(docs/design/test-report-table-extraction.md 8절)
    COLUMN_ROLE_UNCERTAIN = "COLUMN_ROLE_UNCERTAIN"  # 규칙으로 열 역할을 정하지 못함
    VALUE_OUTSIDE_TABLE = "VALUE_OUTSIDE_TABLE"  # 표가 있는데 표 밖 글자에서 값을 읽음
    TABLE_NOT_DETECTED = "TABLE_NOT_DETECTED"  # 표를 찾지 못함
    TABLE_CONTINUATION_GUESSED = "TABLE_CONTINUATION_GUESSED"  # 쪽 넘김 표 잇기를 추정함


class ErrorCode(StrEnum):
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    DOCUMENT_UNREADABLE = "DOCUMENT_UNREADABLE"
    SAMPLE_DATE_IN_FUTURE = "SAMPLE_DATE_IN_FUTURE"
    ISSUED_BEFORE_SAMPLE = "ISSUED_BEFORE_SAMPLE"
    READER_FAILED = "READER_FAILED"  # 읽기 구성요소 내부 오류·시간 초과
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"  # 출력이 계약 형식을 어김


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- 입력 ------------------------------------------------------------------------------------


class DocumentMeta(_Strict):
    case_id: str
    document_id: str
    filename: str
    content_type: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)
    uploaded_at: datetime


class PageText(_Strict):
    page: int = Field(ge=1)  # 1부터
    text: str


class PageImage(_Strict):
    """OCR용 쪽 이미지. [미래] v1 구현은 text만 쓴다."""

    page: int = Field(ge=1)
    content_type: str
    ref: str  # 저장소 참조(바이트를 요청에 싣지 않는다)


class DocumentContent(_Strict):
    """text_pages가 기본. 텍스트 층이 없는 스캔본은 page_images로 OCR을 맡긴다(미래)."""

    text_pages: list[PageText] = []
    page_images: list[PageImage] = []  # [미래] OCR
    tables: list[TableGrid] = []  # 표 인식 층의 칸 단위 표(선택)
    page_count: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _has_content(self) -> Self:
        if not self.text_pages and not self.page_images and not self.tables:
            raise ValueError("text_pages, page_images, tables 중 하나는 있어야 한다")
        return self


class RequestedFact(_Strict):
    """REQUEST_EVIDENCE가 요청한 사실 하나. 카탈로그 정의를 풀어 담는다."""

    key: str
    label: str | None = None
    type: Literal["bool", "enum", "number"]
    unit: str | None = None
    allowed_values: list[str] | None = None  # enum일 때
    note: str | None = None  # 기준값 등 판정 관련 힌트(예: "0.3 mg/L 초과 여부가 갈림")
    help: str | None = None  # 카탈로그 help(시험방법·확인할 값)


class CaseContext(_Strict):
    material: str | None = None  # 소재(알면)
    subject_hint: str | None = None  # 대상 폐기물·시료 이름
    company_hint: str | None = None


class DocumentExtractionRequest(_Strict):
    contract: Literal["document-extraction-v1"] = CONTRACT
    document: DocumentMeta
    content: DocumentContent
    doc_type_hint: DocType | None = None
    requested_facts: list[RequestedFact]
    catalog_subset: list[RequestedFact] = []  # 요청 외에도 읽어도 되는 카탈로그 사실
    as_of: date
    case_context: CaseContext = CaseContext()


# ---- 출력 ------------------------------------------------------------------------------------


class DocumentAttributes(_Strict):
    issuer: str | None = None  # 발급·분석기관
    document_number: str | None = None
    issued_on: date | None = None
    sample_taken_on: date | None = None
    analysis_method: str | None = None  # 예: "ES 06304.1"
    subject_name: str | None = None  # 시료·품목명
    has_signature_or_seal: bool | None = None


class ExtractedFactItem(_Strict):
    key: str
    status: ItemStatus
    value: ScalarValue | None = None  # 카탈로그 타입·단위로 정규화한 값
    comparator: Comparator = Comparator.EQ  # '<0.1'이면 LT + value 0.1
    value_raw: str | None = None  # 서류에 적힌 그대로
    unit_raw: str | None = None
    page: int | None = Field(default=None, ge=1)
    quote: str | None = None  # 서류 원문 발췌(해당 쪽에 실제로 있어야 함)
    item_raw: str | None = None  # 서류에 적힌 항목 이름 그대로(예: 'TCE(mg/L)'). 검수 화면 비교용
    method: str | None = None  # 시험방법 표기
    sample_label: str | None = None  # 시료가 여럿일 때 어느 시료인지
    below_detection_limit: bool = False  # 불검출(ND)
    detection_limit: float | None = None  # 정규화 단위의 검출한계
    # 검출한계를 어디서 얻었나. "limit_column"이면 검출한계가 서류에 없어 같은 행 기준 칸의 값을
    # 상한으로 쓴 것(불검출은 기준보다 낮다는 뜻으로만 쓴다). None은 검출한계 표기("stated")와 같다
    detection_limit_basis: Literal["stated", "limit_column"] | None = None
    note: str | None = None
    # 표 인식(선택): 값·단위·검출한계를 읽은 칸. 있으면 엔진이 표 구조로 검증한다(T1~T10)
    cell_ref: CellRef | None = None
    unit_ref: CellRef | None = None
    detection_limit_ref: CellRef | FootnoteRef | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.status is ItemStatus.FOUND:
            if not self.quote or self.page is None:
                raise ValueError("FOUND에는 quote와 page가 필요하다")
            if self.below_detection_limit:
                if self.detection_limit is None:
                    raise ValueError("불검출에는 detection_limit이 필요하다")
                if self.value is not None:
                    raise ValueError("불검출은 value를 비운다")
            elif self.value is None:
                raise ValueError("FOUND에는 value가 필요하다")
        elif self.value is not None or self.below_detection_limit:
            raise ValueError(f"{self.status}에는 값을 넣지 않는다")
        if self.comparator is not Comparator.EQ and isinstance(self.value, bool | str):
            raise ValueError("comparator는 숫자 값에만 쓴다")
        return self


class ExtractionWarning(_Strict):
    code: WarningCode
    message: str
    key: str | None = None
    page: int | None = None


class ExtractionError(_Strict):
    code: ErrorCode
    message: str


class DocumentExtractionResult(_Strict):
    contract: Literal["document-extraction-v1"] = CONTRACT
    document_id: str
    detected_doc_type: DocType
    doc_type_confidence: float = Field(ge=0, le=1)
    attributes: DocumentAttributes = DocumentAttributes()
    facts: list[ExtractedFactItem] = []  # requested_facts 각각에 대해 정확히 하나
    not_requested_but_found: list[ExtractedFactItem] = []  # catalog_subset 안에서 덤으로 찾은 것
    warnings: list[ExtractionWarning] = []
    errors: list[ExtractionError] = []


# ---- 결과 → Fact -----------------------------------------------------------------------------

ND_NOTE_PREFIX = "불검출"


def item_to_value(item: ExtractedFactItem) -> bool | int | float | str | NumRange:
    """FOUND 항목의 값.

    불검출(ND)은 '검출한계 미만' 구간 NumRange(hi=검출한계, hi_inc=False)로 표현한다.
    값을 0으로 지어내지 않으며, 조건 평가는 구간 규칙(ranges.range_satisfies)을 따른다.
    '<0.1' 같은 부등호 값도 같은 방식으로 구간이 된다.
    """
    if item.below_detection_limit:
        assert item.detection_limit is not None
        return NumRange(hi=item.detection_limit, hi_inc=False)
    value = item.value
    assert value is not None
    if item.comparator is Comparator.EQ:
        return value
    v = float(value)
    match item.comparator:
        case Comparator.LT:
            return NumRange(hi=v, hi_inc=False)
        case Comparator.LTE:
            return NumRange(hi=v, hi_inc=True)
        case Comparator.GT:
            return NumRange(lo=v, lo_inc=False)
        case _:  # GTE
            return NumRange(lo=v, lo_inc=True)
