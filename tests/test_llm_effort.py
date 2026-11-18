"""호출별 추론 강도: 응답(respond)만 낮추고, 모델이 거절하는 인자는 빼고 다시 부른다."""

import json

import httpx
import openai

from app.agent.llm_client import AzureOpenAIClient
from app.config import Settings

SCHEMA = {"type": "object", "properties": {}, "additionalProperties": False}
OK = {
    "id": "x",
    "object": "chat.completion",
    "created": 0,
    "model": "test-model",
    "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}
    ],
}


def _client(monkeypatch, bodies, reject=()):
    def handle(request):
        body = json.loads(request.content)
        bodies.append(body)
        bad = [k for k in reject if k in body]
        if bad:
            msg = f"Unsupported parameter: '{bad[0]}' is not supported with this model."
            return httpx.Response(400, json={"error": {"message": msg}})
        return httpx.Response(200, json=OK)

    real = openai.OpenAI
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kw: real(http_client=httpx.Client(transport=httpx.MockTransport(handle)), **kw),
    )
    return AzureOpenAIClient(
        Settings(
            _env_file=None,
            llm_provider="azure",
            azure_openai_endpoint="https://example.invalid/openai/v1/",
            azure_openai_api_key="synthetic-test-only",
            azure_openai_deployment="test-model",
            respond_reasoning_effort="low",
        )
    )


def _call(client, name):
    return client.complete_json(
        name=name, system="s", user="u", schema=SCHEMA, prompt_version="test"
    )


def test_effort_per_call(monkeypatch):
    bodies = []
    c = _client(monkeypatch, bodies)
    assert not _call(c, "respond").error
    assert not _call(c, "extract").error
    assert bodies[0]["reasoning_effort"] == "low"
    assert bodies[1]["reasoning_effort"] == "medium"  # 추출 기본값
    assert bodies[0]["model"] == bodies[1]["model"]  # 같은 배포: 프롬프트 캐시 유지


def test_empty_effort_means_model_default(monkeypatch):
    monkeypatch.setenv("EXTRACT_REASONING_EFFORT", "")
    assert Settings(_env_file=None).extract_reasoning_effort is None
    assert Settings(_env_file=None).respond_reasoning_effort is None


def test_rejected_parameters_are_dropped_and_remembered(monkeypatch):
    bodies = []
    c = _client(monkeypatch, bodies, reject=("temperature", "reasoning_effort"))
    assert not _call(c, "respond").error
    assert not _call(c, "respond").error
    last = bodies[-1]
    assert "temperature" not in last and "reasoning_effort" not in last
    # 첫 호출에서 두 인자를 한 번씩 거절당한 뒤로는 바로 성공한다
    assert len(bodies) == 4
