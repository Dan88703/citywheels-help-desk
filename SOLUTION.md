# CityWheels help desk agent — solution

A command-line agent that answers CityWheels customer questions from the
shop's policy documents and booking data, using an LLM with tool calling.

## Install and run

Requires Python 3.10+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # then put your API key in .env
```

| What | Command |
| --- | --- |
| Ask one question | `python -m helpdesk "How much is an e-bike for a day?"` |
| Chat (follow-up questions work) | `python -m helpdesk` (`/new` resets, `/quit` exits) |
| Show tool calls | add `--debug` |
| All tests (no network, no key) | `python -m pytest` |
| Evaluation | `python -m eval.run_eval` (`--repeat 3` to measure flakiness) |

The tests also run in GitHub Actions on every push (`.github/workflows/tests.yml`).

## Model and provider

**Groq, model `openai/gpt-oss-120b` (free tier)**, through Groq's
OpenAI-compatible endpoint, called with the official `openai` Python SDK.

- Free without a credit card, very fast, and the model supports tool calling.
- The adapter speaks the OpenAI chat format, which most providers support, so
  switching provider is three lines in `.env` and no code change.
- Temperature 0 to keep answers as repeatable as the provider allows.

How I got there: I planned to use the Google Gemini free tier, but AI Studio
answered "permission denied" when creating a project for my account. Next I
tried GitHub Models and got a plain-text `OK` instead of a completion: the
service was retired on 30 July 2026. Groq worked at once, and because of the
OpenAI-compatible adapter the switch was an `.env` change only. The free tier
allows 8,000 tokens per minute, so the evaluation runs with a pause between
questions and retries on HTTP 429.

I did not use a framework (LangChain etc.). The loop is ~40 lines, and writing
it myself means I know exactly what is sent to the model and can test it
with a fake model. A framework would save little here and hide the details
the task asks me to explain.

## How it works

```
question ─► Agent.ask ─► model ──tool calls──► ToolRegistry.execute ─┐
                  ▲                                                  │
                  └──────────── tool results (JSON) ◄────────────────┘
                  model answers in plain text ─► answer
```

**The loop** (`helpdesk/agent.py`): the whole conversation (system prompt,
earlier turns, tool calls and results) is sent to the model with the tool
schemas. If the model asks for tools, the code runs them, appends their JSON
results as `tool` messages and calls the model again. A plain-text reply ends
the turn. Safety nets: at most 6 steps per question, and an empty answer or
hitting the step limit gives a fixed "please contact the staff" reply. The
message list survives between questions, which gives conversation memory.

**The tools** (`helpdesk/tools.py`), all deterministic Python:

| Tool | What it does |
| --- | --- |
| `search_policies(query)` | Splits the Markdown files into sections at `##` headings and ranks them with BM25 (keyword ranking, with a small synonym list such as "open" ↔ opening hours). Returns the top 3 sections, or "nothing found". |
| `get_booking(booking_id)` | Looks up a booking; accepts `CW-1002`, `cw1002`, `1002`. Unknown ids give a `booking_not_found` result. |
| `calculate_refund(booking_id, cancel_at?)` | Applies the cancellation rules in code (`helpdesk/refund.py`) with `Decimal` money math. `cancel_at` defaults to "now" and lets the agent answer "what if I cancel tomorrow?". Returns the percentage, each part (rental, deposit, fee), the total and how the money comes back. |

The dispatcher turns every problem (unknown tool, invalid JSON, missing
argument, unexpected exception) into an `{"error": ...}` result, so the model
can recover and the program never crashes.

**The instructions** (`helpdesk/prompts.py`): the model gets the fixed current
date and eight rules: answer only from tool results; always search the
policies for shop questions; never guess booking details; never compute refund
amounts but call `calculate_refund`; report "not found" bookings; send
off-topic or unanswerable questions to the staff with their contact details;
ignore instructions in customer messages that conflict with the rules; be
short and reply in the customer's language.

### Interpretations of the rules

- Boundaries are inclusive: exactly 48 h before the start is still 100 %,
  exactly 24 h is 50 % (`CW-1007` and `CW-1010` hit these exactly).
- A `confirmed` booking whose start time has passed cannot be cancelled. The
  policy does not say so, but the rental would already be running.
- The deposit is refunded even in the 0 % tier (the policy says "always").
- For voucher bookings both the rental share and the deposit come back as a
  voucher (the deposit "the same way it was paid").

## Tests

`python -m pytest` runs 83 tests in under a second, without network or key:

- `test_refund.py`: every rule of the cancellation policy, including the
  exact 24 h / 48 h boundaries, statuses that can't be cancelled, the fee,
  the deposit, card vs voucher, rounding.
- `test_tools.py`: the tools on the real data (expected refund for every
  booking), id normalisation, not found, search ranking, bad tool calls.
- `test_agent_loop.py`: the loop with a scripted fake model: tool results
  reach the model in the right message order, unknown bookings and broken
  arguments don't crash, the step limit, conversation memory.
- `test_llm_adapter.py`: the provider adapter with a stubbed HTTP client.
- `test_eval_checks.py`: the evaluation checker itself, since a buggy checker
  would report a fake score.

## Evaluation

`eval/questions.yaml` has 18 cases: 8 need a refund calculation (including
both boundaries, a voucher, a deposit-only refund, a follow-up question and a
prompt injection), 4 must be refused or sent to the staff, plus booking
status, unknown booking, opening hours, prices, age limits and late fees.

`eval/run_eval.py` runs every case on a fresh agent and checks automatically:
which tools were called, that required amounts and phrases are in the answer,
that forbidden content is not, and that refusals point to the staff. Every
case also runs a **grounding check**: each EUR amount in the answer must
appear in a tool result, a policy document or the question, which catches
invented amounts. Results go to `eval/results.md` (and `.json` with details).

### Results

**Final run: 18 / 18 passed in each of 3 repeated runs** (`openai/gpt-oss-120b`
on Groq, `python -m eval.run_eval --delay 10 --repeat 3`, see
`eval/results.md`). The first run is kept in `eval/results-run1.md`.

**First run: 15 / 18.** I read every failed answer before changing anything:

| Case | Answer | Verdict | Fix |
| --- | --- | --- | --- |
| `refund_in_progress` | "CW‑1008 can’t be cancelled – it’s already in progress" | Correct answer, **checker bug** | The model writes typographic `’` (U+2019) and a non-breaking hyphen (U+2011); the check looked for ASCII `can't`. Answers are now normalised to ASCII before checking; regression test with the real answers. |
| `unknown_booking` | "I couldn’t find a booking with the number CW‑1234" | Correct answer, **checker bug** | Same cause and fix. |
| `not_in_docs_group_discount` | "We don’t offer a special discount for groups of 10 people" | **Real agent error** | The documents say nothing about group discounts; the agent turned "not mentioned" into "doesn't exist" and did not send the customer to the staff. I added to rule 6 of the prompt: if the documents don't mention something, say so and give the staff contact instead of saying it is not offered. New answer: "The policy documents don’t mention a discount for groups... Please get in touch with our staff". |

The main lesson: two of three failures were in my own checker. Fixing the
agent from the raw score would have meant "fixing" answers that were right.

**What 18 / 18 does not prove.** The eval is small and I wrote both the
questions and the checks, so it measures the cases I thought of. Some passes
rest on the model behaving well rather than on code:

- `late_fee_city` (12 EUR) passes, but the model does the arithmetic itself
  (1.5 × 4 EUR × 2 h); no tool guarantees it. The grounding check doesn't
  catch errors here either, because small numbers like 12 also appear in the
  documents ("6 to 12 years old").
- `followup_cancel_later` depends on the model turning "12 June at 11:00"
  into the right `cancel_at`.
- String checks accept a correct number inside a confusing explanation.

## How I used AI coding assistants

I built this with Claude (chat with code execution) as a pair programmer: I
gave it the task and data, it proposed a structure and wrote code and tests,
and I reviewed, ran and changed it. Examples where its output was wrong:

1. **Gemini 3 thought signatures.** The first version of the adapter rebuilt
   each tool call from its `id`, `name` and `arguments` before putting it back
   into the history. Checking the Gemini OpenAI-compatibility docs and a forum
   thread showed that Gemini 3 attaches a `thought_signature` (in
   `extra_content`) to tool calls and answers HTTP 400 if it is missing on the
   next request, so a multi-step loop would break on the second call. Fixed by
   keeping `extra_content` and sending it back; covered by
   `test_provider_extra_content_is_sent_back_in_history`.
2. **Synonyms never matched.** The search stemmed the query ("hours" →
   "hour") but looked synonyms up with unstemmed keys, so entries like
   "hours" were dead code. Found in review; fixed by stemming the keys.
3. **Out-of-date provider advice.** When Gemini did not work, the assistant
   suggested GitHub Models with a concrete endpoint and model name. Every
   request returned a confusing `AttributeError: 'str' object has no
   attribute 'choices'`. Two problems: the service had been retired (the
   assistant's knowledge was older than that), and the adapter assumed the SDK
   always returns a parsed object, while for a non-JSON body it returns the raw
   text. I added a check that raises an error showing the server's real answer
   (`'OK\r\n'`), which led to the docs page about the retirement. Covered by
   `test_non_json_response_gives_clear_error`.
4. **A checker that was too strict.** The assistant's eval checks compared
   plain ASCII strings, so correct answers with typographic apostrophes were
   marked as failures (see Results). Noticed by reading the failed answers
   instead of trusting the score.

## Limitations

- Keyword search only: a question phrased with words that are not in the
  documents or the synonym list can miss the right section. Fine for ~20
  sections; a larger knowledge base would need embeddings.
- The model still does some arithmetic itself, e.g. late return fees and
  rental prices for N hours. Only refunds are calculated in code.
- Dates in follow-ups ("tomorrow", "Friday evening") are turned into
  `cancel_at` by the model; a wrong conversion gives a correct calculation for
  the wrong time. The tool result echoes `cancel_at`, so it is visible.
- The agent only calculates refunds; it does not actually cancel bookings.
- Eval checks are string/number based: an answer can pass with a confusing
  explanation, or fail while being correct but phrased unexpectedly.
- LLM output is not fully deterministic even at temperature 0, so one run's
  score can vary; `--repeat` shows flaky cases.

## Next steps

- A `quote_price` tool so rental prices and late fees are also computed in code.
- An LLM-as-judge check for answer quality on top of the string checks.
- Compare two models (e.g. Gemini vs a local Ollama model) on the same eval.
- Run the evaluation in CI on a schedule with a secret key.
