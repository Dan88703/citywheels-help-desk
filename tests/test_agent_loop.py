"""Agent loop tests with a fake model."""

import json

from helpdesk.agent import FALLBACK_ANSWER, Agent
from helpdesk.llm import ModelResponse, ToolCall
from tests.fake_model import ScriptedModel, final, tool_call


def last_tool_result(messages) -> dict:
    return json.loads([m for m in messages if m["role"] == "tool"][-1]["content"])


def test_loop_runs_tool_and_feeds_result_back_to_model():
    def answer_from_tool(messages):
        refund = last_tool_result(messages)
        return final(f"You will get back {refund['total_refund_eur']:.2f} EUR.")

    model = ScriptedModel([tool_call("calculate_refund", {"booking_id": "CW-1002"}), answer_from_tool])
    result = Agent(model).ask("I want to cancel CW-1002. How much will I get back?")

    assert result.answer == "You will get back 340.00 EUR."
    assert [c.name for c in result.tool_calls] == ["calculate_refund"]
    assert result.steps == 2
    # The 2nd model call must see: system, user, assistant(tool_calls), tool result.
    roles = [m["role"] for m in model.calls[1]]
    assert roles == ["system", "user", "assistant", "tool"]
    assert model.calls[1][2]["tool_calls"][0]["function"]["name"] == "calculate_refund"


def test_unknown_booking_does_not_crash_and_model_sees_not_found():
    model = ScriptedModel([
        tool_call("get_booking", {"booking_id": "CW-9999"}),
        final("Sorry, I could not find booking CW-9999."),
    ])
    result = Agent(model).ask("Details of CW-9999?")
    assert result.tool_calls[0].result["error"] == "booking_not_found"
    assert last_tool_result(model.calls[1])["error"] == "booking_not_found"
    assert "could not find" in result.answer


def test_malformed_arguments_and_unknown_tools_become_error_results():
    model = ScriptedModel([
        tool_call("get_booking", "{broken json"),
        tool_call("drop_database", {}, call_id="call_2"),
        final("Done"),
    ])
    result = Agent(model).ask("hi")
    assert [c.result["error"] for c in result.tool_calls] == ["invalid_arguments", "unknown_tool"]
    assert result.answer == "Done"


def test_loop_stops_after_max_steps():
    model = ScriptedModel([tool_call("search_policies", {"query": "x"}, call_id=f"c{i}") for i in range(10)])
    result = Agent(model, max_steps=3).ask("loop forever")
    assert result.stopped_early and result.answer == FALLBACK_ANSWER
    assert len(model.calls) == 3


def test_empty_model_answer_falls_back_to_staff_contact():
    result = Agent(ScriptedModel([final("")])).ask("?")
    assert result.answer == FALLBACK_ANSWER


def test_conversation_memory_keeps_previous_turns():
    model = ScriptedModel([
        tool_call("calculate_refund", {"booking_id": "CW-1001"}),
        final("90.00 EUR"),
        tool_call("calculate_refund", {"booking_id": "CW-1001", "cancel_at": "2026-06-12T11:00:00+02:00"}),
        final("50.00 EUR"),
    ])
    agent = Agent(model)
    agent.ask("Refund for CW-1001?")
    second = agent.ask("And if I cancel on 12 June at 11:00 instead?")

    # The follow-up request still contains the first question and answer.
    contents = [m.get("content") for m in model.calls[2]]
    assert "Refund for CW-1001?" in contents and "90.00 EUR" in contents
    assert second.tool_calls[0].result["total_refund_eur"] == 50.0

    agent.reset()
    assert len(agent.messages) == 1


def test_provider_extra_content_is_sent_back_in_history():
    # Gemini 3 returns a thought signature that must come back unchanged.
    signature = {"google": {"thought_signature": "abc123"}}
    call = ModelResponse(text=None, tool_calls=[ToolCall("c1", "get_booking", {"booking_id": "CW-1001"}, signature)])
    model = ScriptedModel([call, final("ok")])
    Agent(model).ask("CW-1001?")
    assert model.calls[1][2]["tool_calls"][0]["extra_content"] == signature
