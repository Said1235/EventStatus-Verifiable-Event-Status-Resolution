# EventStatus - Test report

Everything below was executed; nothing is claimed that was not. Environment: Python 3.12, `genlayer-test` 0.29.2, `genvm-linter` 0.11.1-rc.2, `genlayer-py` 0.18.0 (pinned by commit in `requirements.txt`), contract runner `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` (CPython 3.13.1 WASI). Audited source SHA-256: see `docs/AUDIT.md`.

## 1. What is verified, and how

| Level | What | Evidence |
|---|---|---|
| **Verified working (executed)** | Lint and schema validation with the official linter | `genvm-lint check contracts/eventstatus.py` -> lint passed (3 checks), validation passed, 5 methods (3 view, 2 write) |
| **Verified working (executed, real GenVM interpreter)** | The pure logic (page-text extraction incl. hostile inputs, model-output normalization, calendar/instant arithmetic, the full resolution policy over 1,452 combinations, canonical JSON, SHA-256 digests, result checks, URL validation) | Run inside GenVM's own CPython 3.13.1 WASI (`cpython.wasm` and the deterministic `cpython.det.wasm`, both runner generations, deterministic build linked with the real `softfloat.wasm`): outputs **byte-identical to native in 4/4 environments**. This is a one-off harness (`wasmtime`), not part of the repository |
| **Verified only with mocks** | Everything involving web pages, the extraction model and the leader/validator exchange | 433 direct-mode tests with **strict** web/LLM mocks (an undeclared call raises; a declared-but-unused mock fails the test). The consensus *model*: leader proposes, state reverts, a possibly forged result is judged by the captured validator under a possibly different world |
| **Verified in Studio with real validators** | - | **Nothing.** No Docker and no network path to Studio in this environment; the 7 integration tests were written and collected, never executed |
| **Not tested** | Real LLM behavior (including prompt-injection resistance of real models), real web retrieval (redirects, content types, timeouts, GenVM's own handling of oversized responses), appeals/finality, true concurrency on a network, fees and gas, GLSim | see section 6 |

## 2. Commands and actual outcomes

| Command | Outcome |
|---|---|
| `genvm-lint check contracts/eventstatus.py` | passed; 5 methods |
| `pytest tests/direct -q` | **433 passed** (about 25 s) |
| `pytest tests/integration --collect-only -q` | 7 tests collected (not executed) |
| `python tools/mutation_check.py` (in 4 batches) | **63 mutants: 61 killed, 2 equivalent** (section 4) |
| `pytest tests/direct -v \| grep ... \| python tools/scenario_matrix.py` | 43/43 scenarios mapped to passing tests (section 3) |
| clean-room: fresh venv, `pip install -r requirements.txt`, lint, `pytest tests/direct` | see section 5 |

Direct-mode suites: registration 70, page text and normalization 90, resolution scenarios 81, policy 5, consensus 158, storage 29. `pyproject.toml` runs pytest with `filterwarnings = error::RuntimeWarning`, which turns a stale strict-mock fixture into a failure.

Property and fuzz coverage inside those suites:

- **Policy, exhaustive:** all 1,452 per-source outcome combinations (11 states, 2 and 3 sources) compared with an independently written oracle, plus 8 semantic properties (a status is only reported when a valid claim says so; priority wins; ambiguous/contradictory sources block fallback; no disagreement or contradiction is dropped; the reschedule date is only exposed for a `RESCHEDULED` decision, ...).
- **Differential fuzz of the validator:** 3 base scenarios x 3 seeds x 450 random forgeries = 4,050 forged leader results; the real validator and an independent acceptance oracle agreed on every one (and both accepted real near-misses, so the check is not vacuous).
- **Stateful fuzz:** 10 seeds x 90 random operations (valid and invalid registrations and resolutions, several callers, nine web/model worlds including failures and malformed output) with 6 global invariants re-checked after every step, **including steps that reverted** (direct mode does not roll back, so any partial write would violate an invariant). It reached six different final statuses, both methods and the fallback path.
- **Calendar arithmetic:** 4,000 random instants checked against Python's `datetime`.
- **Page-text extraction:** nine adversarial inputs designed to trigger quadratic behavior (140,000 `<`, 46,000 unclosed tags, 17,000 unterminated `<script`, ...) all run in milliseconds.

## 3. Scenario matrix (specification section 12, A1-E43)

Computed from a real verbose run by `tools/scenario_matrix.py` (a scenario without a matching test aborts it). Every row is a direct-mode result with mocks.

| # | Scenario | Tests | Passed | Failed | Result |
|---|---|---|---|---|---|
| A1 | All sources confirm the same scheduled event | 1 | 1 | 0 | PASS |
| A2 | All sources confirm cancellation | 1 | 1 | 0 | PASS |
| A3 | All sources confirm postponement | 1 | 1 | 0 | PASS |
| A4 | A source announces a new date and time | 2 | 2 | 0 | PASS |
| A5 | All sources confirm completion | 1 | 1 | 0 | PASS |
| A6 | Primary and secondary disagree; the rule resolves it and both claims are kept | 2 | 2 | 0 | PASS |
| A7 | Highest-priority source unavailable; fallback used and recorded | 6 | 6 | 0 | PASS |
| B8 | A source is inaccessible | 4 | 4 | 0 | PASS |
| B9 | An HTTP error occurs | 11 | 11 | 0 | PASS |
| B10 | A source contains no explicit status claim | 1 | 1 | 0 | PASS |
| B11 | An old page still shows the original date | 2 | 2 | 0 | PASS |
| B12 | A cancellation about a similarly named different event | 1 | 1 | 0 | PASS |
| B13 | Same name at a different venue / tour | 3 | 3 | 0 | PASS |
| B14 | New date visible but timezone ambiguous | 6 | 6 | 0 | PASS |
| B15 | One source with a past announcement and a later correction | 2 | 2 | 0 | PASS |
| B16 | Valid sources contradict and no defensible controlling claim exists | 3 | 3 | 0 | PASS |
| B17 | Source says cancelled but the excerpt does not support it | 7 | 7 | 0 | PASS |
| B18 | No source gives sufficient evidence: never a false SCHEDULED | 12 | 12 | 0 | PASS |
| C19 | Prompt injection in page content | 4 | 4 | 0 | PASS |
| C20 | Misleading, hidden or conflicting page text | 3 | 3 | 0 | PASS |
| C21 | Malformed JSON, missing fields, bad enums, extra claims | 30 | 30 | 0 | PASS |
| C22 | Evidence excerpt that cannot be found in the source | 7 | 7 | 0 | PASS |
| C23 | Hallucinated date, timezone or URL | 16 | 16 | 0 | PASS |
| C24 | Page exceeds a runtime content constraint | 7 | 7 | 0 | PASS |
| D25 | Leader CANCELLED, validator derives SCHEDULED | 1 | 1 | 0 | PASS |
| D26 | Same final status, different material source finding | 22 | 22 | 0 | PASS |
| D27 | Same final status, different controlling source | 1 | 1 | 0 | PASS |
| D28 | Same final status, different rescheduled date/time | 5 | 5 | 0 | PASS |
| D29 | Same final status, different view on whether a conflict exists | 1 | 1 | 0 | PASS |
| D30 | Leader invents a source claim validators cannot substantiate | 13 | 13 | 0 | PASS |
| D31 | Valid enum and shape but evidence contradicts the decision | 48 | 48 | 0 | PASS |
| D32 | Validator receives a failed leader result | 2 | 2 | 0 | PASS |
| D33 | Temporary retrieval failure is not a positive finding | 3 | 3 | 0 | PASS |
| D34 | Source changes between leader and validator retrieval | 2 | 2 | 0 | PASS |
| D35 | Plausible but different validator result does not pass on status alone | 34 | 34 | 0 | PASS |
| E36 | Registering an existing event id fails | 1 | 1 | 0 | PASS |
| E37 | Invalid or duplicate source URLs are rejected | 22 | 22 | 0 | PASS |
| E38 | Reusing a request id fails without overwriting | 3 | 3 | 0 | PASS |
| E39 | Two request ids for one event give distinct records | 1 | 1 | 0 | PASS |
| E40 | Multiple callers never receive each other's results | 1 | 1 | 0 | PASS |
| E41 | Concurrent or reordered evaluations cannot mix findings | 2 | 2 | 0 | PASS |
| E42 | Lookup by request id returns the matching result, not the wallet's newest | 1 | 1 | 0 | PASS |
| E43 | State survives later calls and stays serializable | 11 | 11 | 0 | PASS |

Notes on how the specification's cases are realized:

- **B16** ("two valid sources contradict and the policy cannot identify a controlling claim"): with a strict total priority order two *valid* claims are always reconcilable, by design. The unreconcilable case that exists is a controlling source that contradicts itself (and its ambiguous counterpart); those are tested, together with the rule that no fallback passes them.
- **B17 / C19** have a documented-limitation test each (`test_B17_documented_limitation_...`, `test_C19_documented_limitation_...`) that pins what the contract cannot do: it cannot judge whether a real quote *supports* a claim, and models fooled identically on every node are not caught.
- **C24:** size handling is tested at the exact boundaries (150,000 / 150,001 bytes; 24,000 / 24,001 visible characters). GenVM's own handling of oversized responses was **not** observable here (see section 6).

## 4. Mutation check

`tools/mutation_check.py` weakens the contract in 63 ways (consensus and validator checks, model-output normalization, retrieval and page-text rules, the resolution policy, registration and storage) and requires the suite to fail each time. Mutants are written to a temporary directory and loaded through the `EVENTSTATUS_CONTRACT` variable; the real contract is never modified.

- **61 killed.**
- **2 equivalent mutants, understood:** `V10` (event/request id binding in `_check_core`) and `V15` (policy-version binding) are redundant because `_check_core` ends with `core == expected`, where `expected` is rebuilt from the stored event and already contains those fields. A dedicated test (`test_a_result_built_for_another_request_event_or_policy_is_not_valid_here`) pins the behavior; the guards are kept as defense in depth.

The first mutation round **found gaps in the tests, not in the contract** (see `docs/AUDIT.md`): validator-side comparison of `claim` and `outcome` survived because the earlier tests changed the *page* as well as the judgement (which a different rule rejected first), so tests for "same page, different judgement", digest-consistent forgeries and a pre-storage-guard injection were added.

## 5. Clean-room verification

A fresh virtual environment, `pip install -r requirements.txt`, then lint and `pytest tests/direct`. Result recorded in the section "Clean-room result" below.

## 6. Known gaps in what was tested

1. **Studio / real consensus:** not executed (no Docker; Studio unreachable). Command: `gltest tests/integration/test_eventstatus.py -v -s`. The mock-validator keys used by the integration suite follow the gltest documentation and are unproven.
2. **GLSim:** not used for this contract. For the same GLSim version (0.29.2), earlier work on a sibling contract found that every other deployment of a file fails inside GLSim (reproduced with the boilerplate's own example contract) and that it assigns one fixed sender to every transaction, so multi-account flows cannot be exercised. `tools/run_glsim_nocache.py` only works around the first problem.
3. **Real web behavior:** direct mode returns whatever the test mocks. How GenVM treats redirects, content types, timeouts and *oversized* responses (it may fail before contract code regains control, in which case the contract would not see a clean status) was not observed. GenLayer's documentation says Studio's web access depends on its own browser service and that production web reads should be validated on the target network.
4. **Real model behavior:** models were simulated. Prompt quality, borderline identity decisions and the exact-agreement requirement (which trades liveness for safety) need measurement with real validators.
5. **Concurrency:** GenLayer serializes transactions per contract; direct mode cannot reproduce network-level ordering. Interleaved and racing evaluations are tested at the level of what a second execution sees.
6. **Fees and gas:** not evaluated.

## Clean-room result

Fresh virtual environment, `pip install -r requirements.txt`, on the final tree:

- `genvm-lint check contracts/eventstatus.py` -> Lint passed (3 checks), Validation passed, 5 methods (3 view, 2 write).
- `pytest tests/direct -q` -> **433 passed**.
- `pytest tests/integration --collect-only -q` -> 7 tests collected.
- `sha256sum contracts/eventstatus.py` -> `d083cd8aad10dd00aa9bae3bde44f1fdd8037d4a5b9ea7f3b41461e268cd0ef7` (identical to the audited source).
