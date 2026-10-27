"""A scripted stand-in for the LLM: no network, no API key."""

from helpdesk.llm import ModelResponse, ToolCall


class ScriptedModel:
    """Returns pre-written responses in order and records what it was sent.

    A response can be a ModelResponse, or a function that receives the
    messages and builds one; the latter lets a test answer from the tool
    result the agent passed back, like a real model would.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[list[dict]] = []

    def complete(self, messages, tools):
        self.calls.append([dict(m) for m in messages])
        step = self.script.pop(0)
        return step(messages) if callable(step) else step


def tool_call(name: str, arguments, call_id: str = "call_1") -> ModelResponse:
    return ModelResponse(text=None, tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)])


def final(text: str) -> ModelResponse:
    return ModelResponse(text=text)
