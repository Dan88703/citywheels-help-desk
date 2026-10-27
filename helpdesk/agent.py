"""The tool-calling agent loop."""

import json
from dataclasses import dataclass, field

from helpdesk.config import STAFF_CONTACT
from helpdesk.llm import ChatModel, ToolCall
from helpdesk.prompts import SYSTEM_PROMPT
from helpdesk.tools import ToolRegistry

FALLBACK_ANSWER = (
    "Sorry, I could not find an answer to that. "
    f"Please contact the CityWheels staff: {STAFF_CONTACT}."
)


def _tool_call_message(call: ToolCall) -> dict:
    """Write a tool call back into history in OpenAI format."""
    message = {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.name,
            "arguments": call.arguments if isinstance(call.arguments, str) else json.dumps(call.arguments),
        },
    }
    if call.extra_content:
        message["extra_content"] = call.extra_content
    return message


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict | str
    result: dict


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    steps: int = 0
    stopped_early: bool = False


class Agent:
    """Keeps the conversation and runs the model <-> tools loop.

    The message list is kept between `ask()` calls, which is what makes
    follow-up questions ("and if I cancel tomorrow?") work. `reset()` starts
    a new conversation.
    """

    def __init__(self, model: ChatModel, tools: ToolRegistry | None = None, max_steps: int = 6):
        self.model = model
        self.tools = tools or ToolRegistry()
        self.max_steps = max_steps
        self.reset()

    def reset(self) -> None:
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    def ask(self, question: str) -> AgentResult:
        """Answer one customer message.

        Each step sends the whole conversation to the model. If the model
        asks for tools, we run them, append their JSON results as `tool`
        messages and loop again; when it answers with plain text, we stop.
        `max_steps` guards against a model that keeps calling tools forever.
        """
        self.messages.append({"role": "user", "content": question})
        records: list[ToolCallRecord] = []

        for step in range(1, self.max_steps + 1):
            response = self.model.complete(self.messages, self.tools.schemas)

            if not response.tool_calls:
                answer = (response.text or "").strip() or FALLBACK_ANSWER
                self.messages.append({"role": "assistant", "content": answer})
                return AgentResult(answer=answer, tool_calls=records, steps=step)

            # The assistant message with tool_calls must come before the tool
            # results, in OpenAI's format, or the API rejects the next request.
            self.messages.append({
                "role": "assistant",
                "content": response.text or "",
                "tool_calls": [_tool_call_message(call) for call in response.tool_calls],
            })
            for call in response.tool_calls:
                result = self.tools.execute(call.name, call.arguments)
                records.append(ToolCallRecord(call.name, call.arguments, result))
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

        self.messages.append({"role": "assistant", "content": FALLBACK_ANSWER})
        return AgentResult(answer=FALLBACK_ANSWER, tool_calls=records, steps=self.max_steps, stopped_early=True)
