"""LLM 공급자 추상화.

- AzureOpenAIClient: Azure OpenAI chat.completions + JSON Schema 구조화 출력(strict), temperature 0
- FakeLLMClient: 테스트·--mock 모드용. 스크립트된 응답을 차례로 돌려준다.
모든 호출은 LLMCall로 기록해 Decision Trace에 남긴다.
"""

from __future__ import annotations

import json
import time
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from pydantic import BaseModel

from app.config import Settings


class LLMError(RuntimeError):
    pass


class LLMCall(BaseModel):
    name: str  # extract | respond ...
    model: str
    prompt_version: str
    system: str
    user: str
    raw: str | None = None
    parsed: dict | None = None
    error: str | None = None
    latency_ms: int = 0
    usage: dict | None = None
    # OPS-003: user에는 가린 프롬프트만 들어간다. 원문은 해시·길이로만 남긴다.
    user_sha256: str | None = None
    user_len: int | None = None
    raw_sha256: str | None = None
    raw_len: int | None = None


class LLMClient(Protocol):
    model: str

    def complete_json(
        self, *, name: str, system: str, user: str, schema: dict, prompt_version: str
    ) -> LLMCall: ...


class AzureOpenAIClient:
    def __init__(self, settings: Settings):
        from urllib.parse import urlparse

        from openai import AzureOpenAI, OpenAI  # 지연 import: 테스트에서 불필요

        if not settings.llm_enabled:
            raise LLMError("Azure OpenAI 설정이 없습니다(.env)")
        self.model = settings.azure_openai_deployment or ""
        self._temperature_ok = True
        endpoint = settings.azure_openai_endpoint or ""
        u = urlparse(endpoint)
        if "/openai/v1" in u.path:
            # Azure AI Foundry v1 호환 엔드포인트(…/openai/v1/…): OpenAI 클라이언트 + base_url
            self._client = OpenAI(
                base_url=f"{u.scheme}://{u.netloc}/openai/v1/",
                api_key=settings.azure_openai_api_key,
                timeout=settings.llm_timeout_seconds,
                # 추출기·응답기가 각 1회 재시도한다. SDK에서 다시 3배로 늘리지 않는다.
                max_retries=0,
            )
        else:
            self._client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=settings.azure_openai_api_key,
                api_version=settings.azure_openai_api_version,
                timeout=settings.llm_timeout_seconds,
                max_retries=0,
            )

    def complete_json(
        self, *, name: str, system: str, user: str, schema: dict, prompt_version: str
    ) -> LLMCall:
        call = LLMCall(
            name=name, model=self.model, prompt_version=prompt_version, system=system, user=user
        )
        t = time.perf_counter()
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
        )
        try:
            if self._temperature_ok:
                try:
                    resp = self._client.chat.completions.create(temperature=0, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    # 추론 모델은 temperature를 받지 않는다 → 빼고 다시 부른다(이후 계속 생략)
                    if "temperature" not in str(exc):
                        raise
                    self._temperature_ok = False
                    resp = self._client.chat.completions.create(**kwargs)
            else:
                resp = self._client.chat.completions.create(**kwargs)
            call.raw = resp.choices[0].message.content
            call.usage = resp.usage.model_dump() if resp.usage else None
            call.parsed = json.loads(call.raw or "{}")
        except Exception as exc:  # noqa: BLE001 — 호출 실패도 Trace에 남기고 상위에서 처리
            call.error = f"{type(exc).__name__}: {exc}"
        call.latency_ms = int((time.perf_counter() - t) * 1000)
        return call


Responder = dict | Callable[[str, str], dict]


class FakeLLMClient:
    """스크립트된 응답 큐. 항목은 dict(그대로 반환) 또는 (system, user) -> dict 함수.

    `by_name`을 주면 호출 이름(extract/respond)별 큐를 쓴다. 큐가 비면 `default(name)`를 쓴다.
    """

    model = "fake"

    def __init__(
        self,
        responses: Iterable[Responder] = (),
        *,
        by_name: dict[str, Iterable[Responder]] | None = None,
        default: Callable[[str, str, str], dict] | None = None,
    ):
        self._queue: deque = deque(responses)
        self._by_name = {k: deque(v) for k, v in (by_name or {}).items()}
        self._default = default
        self.calls: list[LLMCall] = []

    def push(self, name: str, response: Responder) -> None:
        self._by_name.setdefault(name, deque()).append(response)

    def complete_json(
        self, *, name: str, system: str, user: str, schema: dict, prompt_version: str
    ) -> LLMCall:
        q = self._by_name.get(name)
        if q:
            r = q.popleft()
        elif self._queue:
            r = self._queue.popleft()
        elif self._default is not None:
            r = lambda s, u: self._default(name, s, u)  # noqa: E731
        else:
            raise LLMError(f"FakeLLMClient: '{name}' 응답이 준비되지 않았습니다")
        parsed: Any = r(system, user) if callable(r) else r
        call = LLMCall(
            name=name,
            model=self.model,
            prompt_version=prompt_version,
            system=system,
            user=user,
            raw=json.dumps(parsed, ensure_ascii=False),
            parsed=parsed,
        )
        self.calls.append(call)
        return call


def make_client(settings: Settings) -> LLMClient | None:
    return AzureOpenAIClient(settings) if settings.llm_enabled else None
