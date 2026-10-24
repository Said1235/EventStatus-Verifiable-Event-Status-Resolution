# EventStatus

A standalone [Intelligent Contract](https://docs.genlayer.com/developers/intelligent-contracts) for [GenLayer](https://www.genlayer.com) that resolves the **status of a public event** (conference, concert, match, exhibition...) from **2-3 pre-registered, prioritized web sources**, resolves disagreements with an explicit deterministic policy fixed at registration, and stores a compact result that anyone can check without trusting a narrative summary.

It is a resolution primitive, not a search engine: it never discovers sources, never guarantees an event will happen, and does not establish legal truth. It evaluates the evidence in the registered sources under written rules. No frontend, backend, token, payment, betting or admin power is part of it.

> **Status:** verified with the official linter and **433 direct-mode tests** (strict web/LLM mocks, independent oracles, fuzzing, 63-mutant mutation check). **Not verified:** real multi-validator consensus on GenLayer Studio or a live network, real LLM behavior, real web retrieval. No deployment exists. See [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) and [`docs/AUDIT.md`](docs/AUDIT.md) for exactly what was and was not tested.

## How it works

1. **Register** an event once: title, organizer, venue, location, an explicit-timezone start time, and 2-3 event-specific HTTPS source URLs with a declared role. **List order is the priority order and can never change.** A correction is a new registration (optionally marked `supersedes` the old one); old results keep the policy they were produced under.
2. **Resolve**: anyone calls `resolve_event(event_id, request_id)`. The contract fetches **only the frozen URLs**, extracts one finding per source (a separate fixed prompt per source, so one page can never influence another), applies the policy, and stores the full result under the caller's unique `request_id`.
3. **Read** the result by `request_id`.

### Status model

| Status | Meaning |
|---|---|
| `SCHEDULED` | affirmative, current evidence the event is going ahead (absence of a cancellation, or an old page showing the original date, is *not* evidence) |
| `RESCHEDULED` | explicitly moved; the new date/time is recorded **only as stated** (a missing timezone is preserved as `TZ_AMBIGUOUS`, never guessed) |
| `POSTPONED` | explicit postponement without a definitive replacement schedule |
| `CANCELLED` | explicit cancellation. A 404, an empty page or silence is **not** a cancellation |
| `COMPLETED` | explicit evidence it took place. A date in the past is not evidence |
| `CONFLICTING_SOURCES` | the controlling source contradicts itself and the policy cannot decide |
| `INSUFFICIENT_EVIDENCE` | nothing defensible can be concluded |
| `EVENT_IDENTITY_UNCONFIRMED` | every retrieved page failed to match the registered event |

These are event findings, not transaction outcomes: a transaction can succeed with `INSUFFICIENT_EVIDENCE`, and a failed or undetermined transaction means *no result yet*.

### Policy `PRIORITY_V1` (summary)

Per source the outcome is one of `RETRIEVAL_FAILED`, `IDENTITY_UNCONFIRMED`, `NO_EXPLICIT_STATUS`, `AMBIGUOUS`, `CONTRADICTORY` or `VALID_CLAIM`. The first source (in priority order) that is not *skippable* decides: a valid claim **controls** the result; an ambiguous or contradictory source **blocks** it (no fallback past it). Failed, wrong-event or status-less sources are skipped - that is the documented fallback, and it is recorded. Every disagreeing lower-priority claim and every internal contradiction is preserved in `conflicts`. Full rules and tables: [`docs/DESIGN.md`](docs/DESIGN.md).

### What makes consensus meaningful

Validators do **not** compare final statuses. Each validator independently re-fetches every source, re-extracts every finding and must obtain the **same retrieval class and HTTP status, identity decision, status claim and reschedule date/time/timezone for every source**. The final status, method, controlling source, conflicts, decision roles and digests are derived by pure code from those findings and recomputed by every node. Evidence quotes may be worded differently by different nodes but each must be a substantive literal quote of that validator's *own* copy of the page. There is no score, tolerance or free-text field that can influence the outcome.

## Public interface

| Method | Kind | Arguments | Returns |
|---|---|---|---|
| `register_event` | write | `event_id`, `title`, `organizer`, `venue`, `location`, `scheduled_start` (ISO-8601 with explicit timezone), `source_urls: list[str]`, `source_roles: list[str]`, `supersedes` (`""` for none) | - |
| `resolve_event` | write | `event_id`, `request_id` | final status string |
| `get_event` | view | `event_id` | config incl. ordered sources and `resolution_count` (`found: false` if absent) |
| `get_resolution` | view | `request_id` | the complete stored result (`found: false` if absent) |
| `get_event_resolution_id` | view | `event_id`, `index` (1-based) | `request_id` of the N-th resolution or `""` |

Ids are `[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}`. Source roles are `ORGANIZER, VENUE, TICKETING, AUTHORITY, MEDIA, OTHER` and are **declared metadata only**: the contract cannot prove a URL belongs to the named organizer. Failed calls revert with a message prefix: `[EXPECTED]` (invalid call) or `[LLM_ERROR]` (unusable model output).

A resolution contains: `request_id`, `event_id`, `requester`, `resolved_at` (deterministic transaction time), `policy_version`, `final_status`, `method` (`AGREEMENT`/`PRIORITY_RULE`/`NONE`), `reason`, `controlling_source`, `fallback_used`, `new_start_*` (+ `new_start_precision`), `findings[]` (per source: retrieval class, HTTP status, outcome, claim, reschedule parts, short verbatim excerpt, evidence digest, decision role), `conflicts[]` and `result_digest`. Digests are SHA-256 over a canonical JSON of the *normalized* evidence record - they identify what was stored, not the raw page bytes (live pages differ between requests, so a raw-byte hash cannot be consensus-checked).

`request_id` is an application key chosen by the caller (global, used once). It is **not** the blockchain transaction id, which the contract never reads.

## Getting started

Requirements: Python 3.12 and internet access (GenVM runners are downloaded on first use).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

genvm-lint check contracts/eventstatus.py     # lint + schema validation
pytest tests/direct -q                        # 433 direct-mode tests
```

### Loading and testing in GenLayer Studio

1. Open Studio, create a new contract and paste `contracts/eventstatus.py` (no constructor arguments), or use the CLI: `npm install -g genlayer`, then `genlayer network set <network>` and `genlayer deploy` (see `genlayer deploy --help`).
2. Confirm the schema (`genlayer schema <address>`): 2 write methods, 3 view methods.
3. Call `register_event` with 2-3 real, compact, event-specific HTTPS pages, then `resolve_event` with a fresh `request_id`, then `get_resolution`.
4. Automated checks: `gltest tests/integration/test_eventstatus.py -v -s` (mock validators, real consensus) and, optionally, `EVENTSTATUS_LIVE_URLS='["https://...","https://..."]' gltest tests/integration/test_eventstatus.py -k live -s` (real validators, real pages).
5. Studio's web access depends on its own browser service; GenLayer's documentation advises validating production web reads on the target network. GLSim 0.29.2 is not usable for these multi-account flows (see the test report).

## Repository layout

```
contracts/eventstatus.py      The contract
tests/direct/                 Direct-mode tests (registration, page text, resolution, policy, consensus, storage)
tests/integration/            Studio consensus tests (written, not executed here)
tools/                        Mutation check, scenario matrix, GLSim launcher
docs/DESIGN.md                Status model, policy, evidence, consensus comparison, failure handling, storage
docs/TEST_REPORT.md           Commands run and actual outcomes; what is verified how
docs/AUDIT.md                 Adversarial audit: findings, residual risks, limitations
docs/REFERENCES.md            Official APIs and documentation used
```

## Known limitations (short list)

- If every node's model is fooled the same way (for example by an injection) and cites a real sentence of the page, the result is consistent and is accepted. Defenses (per-source isolation, delimiters, fixed schema, literal-quote and independent re-derivation requirements) raise the cost; they are not immunity.
- A quote proves *presence* in the page, not that it *supports* the claim; that judgement is the models'.
- Raw HTML is evaluated: JavaScript-rendered content is invisible and CSS-hidden text is not detected. Prefer official, compact, machine-readable pages.
- If a higher-priority source is unreachable *for validators*, a lower-priority source may control. This is always flagged (`fallback_used`, role `SKIPPED`); consumers should weigh such results accordingly.
- Event and request ids are first-come, there is no fee or rate limit, and each resolution costs validators web and LLM calls.
- Up to 240 characters per source of page text are stored publicly.

The complete list is in [`docs/AUDIT.md`](docs/AUDIT.md).
