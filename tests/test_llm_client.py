"""Azure OpenAI 클라이언트의 출력 토큰 상한 전달과, 받지 않는 인자 빼고 다시 부르기."""

from types import SimpleNamespace

from app.config import Settings
from app.llm.client import AzureOpenAIClient


def _settings(**kw):
    return Settings(
        _env_file=None,
        llm_provider="azure",
        azure_openai_endpoint="https://example.invalid/",
        azure_openai_api_key="fake",
        azure_openai_deployment="model",
        **kw,
    )


class _FakeCompletions:
    def __init__(self, reject=()):
        self.calls, self.reject = [], set(reject)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        bad = next((k for k in kwargs if k in self.reject), None)
        if bad:
            raise ValueError(f"Unsupported parameter: '{bad}'")
        message = SimpleNamespace(content='{"ok": true}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)


def _client(settings, completions):
    client = AzureOpenAIClient(settings)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client


def _call(client):
    return client.complete_json(
        name="extract", system="s", user="u", schema={"type": "object"}, prompt_version="t"
    )


def test_output_token_cap_is_sent():
    fake = _FakeCompletions()
    call = _call(_client(_settings(llm_max_output_tokens=1234), fake))
    assert call.parsed == {"ok": True}
    assert fake.calls[0]["max_completion_tokens"] == 1234


def test_model_that_rejects_the_cap_is_called_again_without_it():
    fake = _FakeCompletions(reject={"max_completion_tokens"})
    client = _client(_settings(), fake)
    assert _call(client).parsed == {"ok": True}
    assert "max_completion_tokens" not in fake.calls[-1]
    _call(client)  # 한 번 거절된 인자는 다음 호출부터 처음부터 뺀다
    assert "max_completion_tokens" not in fake.calls[-1]
