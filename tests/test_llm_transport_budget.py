"""통신 실패의 재시도는 오케스트레이터가 담당하며 SDK 안에서 증폭하지 않는다."""

import httpx
import openai
import pytest

from app.agent.llm_client import AzureOpenAIClient
from app.config import Settings


@pytest.mark.parametrize("v1", [True, False])
@pytest.mark.parametrize("failure", ["timeout", "server_error"])
def test_one_transport_attempt_per_recorded_llm_call(monkeypatch, v1, failure):
    requests = []

    def fail(request):
        requests.append(request.method)
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(500, json={"error": {"message": "synthetic failure"}})

    name = "OpenAI" if v1 else "AzureOpenAI"
    real_client = getattr(openai, name)
    monkeypatch.setattr(
        openai,
        name,
        lambda **kwargs: real_client(
            http_client=httpx.Client(transport=httpx.MockTransport(fail)), **kwargs
        ),
    )
    client = AzureOpenAIClient(
        Settings(
            _env_file=None,
            llm_provider="azure",
            azure_openai_endpoint="https://example.invalid/openai/v1/"
            if v1
            else "https://example.invalid/",
            azure_openai_api_key="synthetic-test-only",
            azure_openai_deployment="test-model",
        )
    )
    try:
        call = client.complete_json(
            name="extract",
            system="synthetic",
            user="synthetic",
            schema={"type": "object", "properties": {}, "additionalProperties": False},
            prompt_version="test",
        )
        assert call.error
        assert call.parsed is None
        assert requests == ["POST"]
    finally:
        client._client.close()
