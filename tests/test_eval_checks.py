"""Tests for the evaluation checker itself (a broken checker gives a fake score)."""

from eval.checks import check_case, money_amounts_in, policy_numbers
from eval.run_eval import run_case, write_report
from tests.fake_model import ScriptedModel, final, tool_call

KNOWN = policy_numbers()


def check(case, answer, tools=(), results=(), questions=("q",)):
    return check_case(case, answer, list(tools), list(results), list(questions), KNOWN)


def test_amount_formats_are_recognised():
    case = {"amounts": [340]}
    for answer in ["340 EUR", "340.00 EUR", "€340", "340,00 €", "a total of 340"]:
        assert check(case, answer, results=[{"total": 340.0}]).passed, answer
    assert not check(case, "1340 EUR", results=[{"total": 1340}]).passed


def test_required_tool_missing_fails():
    outcome = check({"tools": ["calculate_refund"]}, "ok", tools=["search_policies"])
    assert outcome.failures == ["tool `calculate_refund` not called"]


def test_any_of_alternatives_and_forbidden_text():
    case = {"must_contain": [["not found", "could not find"]], "must_not_contain": ["Canberra"]}
    assert check(case, "I could not find that booking.").passed
    assert not check(case, "Canberra. Also not found.").passed


def test_refusal_needs_staff_pointer():
    assert check({"refusal": True}, "Please contact help@citywheels.example").passed
    assert not check({"refusal": True}, "I don't know.").passed


def test_invented_amount_is_flagged_as_ungrounded():
    outcome = check({}, "You get 377.50 EUR back.", results=[{"total_refund_eur": 340.0}])
    assert outcome.failures == ["ungrounded amounts [377.5]"]


def test_amount_from_tool_or_question_is_grounded():
    assert check({}, "You get 340 EUR.", results=[{"total_refund_eur": 340.0}]).passed
    assert check({}, "Not 999 EUR.", questions=["Is it 999 EUR?"]).passed


def test_money_regex():
    assert money_amounts_in("EUR 20 and 40 € and 7 days and 3 euros") == {20.0, 40.0, 3.0}


def test_runner_end_to_end_with_fake_model(tmp_path):
    def answer(messages):
        import json
        refund = json.loads(messages[-1]["content"])
        return final(f"You get {refund['total_refund_eur']:.2f} EUR back.")

    model = ScriptedModel([tool_call("calculate_refund", {"booking_id": "CW-1002"}), answer])
    model.model = "fake"
    case = {"id": "refund_cw1002_half", "question": "Cancel CW-1002?", "tools": ["calculate_refund"], "amounts": [340]}
    result = run_case(model, case, KNOWN, delay=0)
    assert result["passed"], result

    out = tmp_path / "results.md"
    write_report([[result]], [case], "fake", out)
    text = out.read_text(encoding="utf-8")
    assert "Passed: 1 of 1" in text and "`refund_cw1002_half` | PASS" in text


def test_runner_records_model_errors_as_failures():
    class Broken:
        def complete(self, messages, tools):
            raise ConnectionError("offline")

    result = run_case(Broken(), {"id": "x", "question": "hi"}, KNOWN, delay=0)
    assert not result["passed"] and "ConnectionError" in result["failures"][0]


def test_typographic_apostrophes_and_hyphens_are_normalised():
    # Real answers from the first eval run that were wrongly marked as FAIL.
    case = {"must_contain": [["can't", "cannot"]]}
    assert check(case, "CW‑1008 can’t be cancelled – it’s in progress.").passed
    case = {"must_contain": [["couldn't find"]]}
    assert check(case, "I couldn’t find a booking with the number CW‑1234.").passed
