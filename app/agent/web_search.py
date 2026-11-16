"""웹 검색(보충 설명의 마지막 수단, 기본 꺼짐).

질문 안내(knowledge/question_guide.yaml)·용어집·규칙 설명에 답할 자료가 없을 때만 쓴다
(app/agent/assist.py). 판정에는 쓰지 않는다.

- 허용 도메인(공공기관·법령 사이트)의 결과만 쓴다. 결과는 "웹 검색 참고(공식 확인 필요)"로 표시한다.
- 보내기 전에 식별 정보를 가린다. 가린 뒤에도 남으면 검색하지 않는다(fail-closed).
- 제공자: naver(네이버 검색 API). WEB_SEARCH_PROVIDER=naver + NAVER_CLIENT_ID/SECRET.
  키가 없으면 꺼진다.
"""

from __future__ import annotations

import html
import re
from typing import Protocol
from urllib.parse import urlparse

from pydantic import BaseModel

from app.agent.redact import find_identifiers, redact_obj
from app.config import Settings

DEFAULT_ALLOWLIST = (
    "law.go.kr",
    "me.go.kr",
    "nier.go.kr",
    "ncis.nier.go.kr",
    "kosha.or.kr",
    "keco.or.kr",
    "allbaro.or.kr",
    "korea.kr",
    "kcc.go.kr",
    "kepco.co.kr",
)


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str = ""


class WebSearch(Protocol):
    def search(self, query: str, limit: int = 3) -> list[WebResult]: ...


def allowed(url: str, allowlist: tuple[str, ...] = DEFAULT_ALLOWLIST) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in allowlist)


def safe_query(text: str) -> str | None:
    """검색어에서 식별 정보를 가린다. 가린 뒤에도 남으면 None(검색하지 않음)."""
    q = str(redact_obj(text))[:100]
    return None if find_identifiers(q) else q


_TAG = re.compile(r"<[^>]+>")


def _clean(s: str) -> str:
    return html.unescape(_TAG.sub("", s or "")).strip()


class NaverWebSearch:
    """네이버 검색 API(웹문서). https://developers.naver.com/docs/serviceapi/search/web/web.md"""

    URL = "https://openapi.naver.com/v1/search/webkr.json"

    def __init__(self, client_id: str, client_secret: str, timeout: float = 5.0):
        self._headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
        self._timeout = timeout

    def search(self, query: str, limit: int = 3) -> list[WebResult]:
        import httpx  # 지연 import

        r = httpx.get(
            self.URL,
            params={"query": query, "display": 20},
            headers=self._headers,
            timeout=self._timeout,
        )
        r.raise_for_status()
        items = r.json().get("items") or []
        out = [
            WebResult(
                title=_clean(i.get("title", "")),
                url=i.get("link", ""),
                snippet=_clean(i.get("description", "")),
            )
            for i in items
        ]
        return [x for x in out if allowed(x.url)][:limit]


def get_web_search(settings: Settings) -> WebSearch | None:
    if (
        settings.web_search_provider == "naver"
        and settings.naver_client_id
        and settings.naver_client_secret
    ):
        return NaverWebSearch(settings.naver_client_id, settings.naver_client_secret)
    return None
