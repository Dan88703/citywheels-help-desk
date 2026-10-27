"""The OpenAI-compatible adapter, with the HTTP client replaced by a stub."""

from openai.types.chat import ChatCompletion

from helpdesk.llm import OpenAICompatibleModel


class StubCompletions:
    def __init__(self, payload):
        self.payload = payload
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        # Build the same typed object the real SDK returns from JSON.
        return ChatCompletion.model_validate(self.payload)


def make_model(payload) -> tuple[OpenAICompatibleModel, StubCompletions]:
    model = OpenAICompatibleModel(model="test-model", api_key="not-a-real-key")
    stub = StubCompletions(payload)
    model._client = type("Client", (), {"chat": type("Chat", (), {"completions": stub})()})()
    return model, stub


def completion(message: dict) -> dict:
    return {
        "id": "x", "object": "chat.completion", "created": 0, "model": "test-model",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
    }


def test_parses_tool_calls_and_keeps_extra_content():
    model, stub = make_model(completion({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": "call_1", "type": "function",
            "function": {"name": "get_booking", "arguments": '{"booking_id": "CW-1001"}'},
            "extra_content": {"google": {"thought_signature": "sig"}},
        }],
    }))
    response = model.complete([{"role": "user", "content": "hi"}], tools=[])
    call = response.tool_calls[0]
    assert call.name == "get_booking" and call.arguments == {"booking_id": "CW-1001"}
    assert call.extra_content == {"google": {"thought_signature": "sig"}}
    assert stub.kwargs["temperature"] == 0.0 and stub.kwargs["model"] == "test-model"


def test_invalid_json_arguments_are_kept_as_string():
    model, _ = make_model(completion({
        "role": "assistant", "content": None,
        "tool_calls": [{"id": "c", "type": "function", "function": {"name": "get_booking", "arguments": "{oops"}}],
    }))
    assert model.complete([], tools=[]).tool_calls[0].arguments == "{oops"


def test_plain_text_answer():
    model, _ = make_model(completion({"role": "assistant", "content": "Hello"}))
    response = model.complete([], tools=[])
    assert response.text == "Hello" and response.tool_calls == []


def test_non_json_response_gives_clear_error():
    model, stub = make_model(None)
    stub.create = lambda **kwargs: "<html>404 Not Found</html>"
    try:
        model.complete([], tools=[])
    except RuntimeError as exc:
        assert "404 Not Found" in str(exc) and "LLM_BASE_URL" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
