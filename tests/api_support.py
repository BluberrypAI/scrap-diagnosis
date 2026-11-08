"""API 테스트 공용: SAMPLE KB + FakeLLM + 임시 SQLite로 앱을 만든다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agent.golden import normalize_extract
from app.agent.llm_client import FakeLLMClient
from app.config import Settings
from app.main import create_app
from app.rules.model import KnowledgeBase
from tests.conftest import AS_OF, DATA

# 기업 프로필(사이트 사실). SAMPLE 카탈로그의 emission_facility만 판정에 쓰인다.
PROFILE = {"site": "제1공장", "facts": {"emission_facility": True, "not_in_catalog": 1}}


def empty_extract(name: str, system: str, user: str) -> dict:
    """스크립트가 비면 '뽑은 것 없음'을 돌려준다."""
    return normalize_extract({})


def fake_llm() -> FakeLLMClient:
    return FakeLLMClient(default=empty_extract)


def make_settings(db_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{db_path.as_posix()}",
        llm_provider="off",
        kb_dir=DATA,
        db_create_all=True,
    )


def build_app(kb: KnowledgeBase, db_path: Path, extractor: FakeLLMClient | None) -> FastAPI:
    return create_app(
        make_settings(db_path),
        kb=kb,
        kb_dir=DATA,
        extractor_llm=extractor,
        responder_llm=None,  # 응답은 결정적 템플릿
        today=lambda: AS_OF,
    )


@dataclass
class Api:
    client: TestClient
    app: FastAPI
    llm: FakeLLMClient | None
    db_path: Path
    headers: dict = field(default_factory=dict)

    def company(self, name: str = "테스트기업", profile: dict | None = None) -> dict:
        r = self.client.post(
            "/companies", json={"name": name, "profile": PROFILE if profile is None else profile}
        )
        assert r.status_code == 201, r.text
        return r.json()

    def use(self, company: dict) -> Api:
        self.headers = {"X-Company-Id": company["id"]}
        return self

    def post(self, url: str, **kw):  # noqa: ANN201
        return self.client.post(url, headers=self.headers, **kw)

    def get(self, url: str, **kw):  # noqa: ANN201
        return self.client.get(url, headers=self.headers, **kw)

    def create_case(self, memo: str | None = None, **kw) -> dict:
        r = self.post("/cases", json={"memo": memo, "quantity": 1.5, "unit": "t", **kw})
        assert r.status_code == 201, r.text
        return r.json()

    def reply(self, case_id: str, key: str, value=None, kind: str = "value") -> dict:  # noqa: ANN001
        r = self.post(
            f"/cases/{case_id}/diagnosis/messages",
            json={"quick_reply": {"key": key, "kind": kind, "value": value}},
        )
        assert r.status_code == 200, r.text
        return r.json()

    def say(self, case_id: str, text: str) -> dict:
        r = self.post(f"/cases/{case_id}/diagnosis/messages", json={"text": text})
        assert r.status_code == 200, r.text
        return r.json()

    def upload(
        self,
        case_id: str,
        content: bytes,
        filename: str = "report.txt",
        content_type: str = "text/plain",
        facts: str | None = None,
    ):  # noqa: ANN201
        data = {"facts": facts} if facts is not None else None
        return self.post(
            f"/cases/{case_id}/documents",
            files={"file": (filename, content, content_type)},
            data=data,
        )

    def container(self):  # noqa: ANN201
        return self.app.state.container


def to_film_oil_question(api: Api, case_id: str) -> dict:
    """PP 필름, 오염 없음까지 답해서 유분 질문 앞에 선다."""
    api.reply(case_id, "material", "PP")
    api.reply(case_id, "form", "FILM")
    return api.reply(case_id, "contamination_screen", kind="none_all")


def minimal_pdf(text: str) -> bytes:
    """텍스트 한 줄짜리 PDF(ASCII). pypdf 추출 테스트용."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
