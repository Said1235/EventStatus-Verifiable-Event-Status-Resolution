# EventStatus - Adversarial audit

**Conclusion: no known blocking defects in the audited source; checks that need real consensus, real web access and real models remain unverified.** This is not a claim that the contract is secure.

Auditor note: the audit was done by the same AI coding assistant that wrote the contract. To reduce self-review bias the validator was attacked with independently written oracles and randomized forgeries, the policy was checked exhaustively, every guard was validated by mutation, and the interpreter-level behavior of the pure logic was checked in GenVM's own CPython. A fresh human review is still recommended before relying on it.

## 1. Audited source

| Item | Value |
|---|---|
| File | `contracts/eventstatus.py` (1,223 lines) |
| SHA-256 | `d083cd8aad10dd00aa9bae3bde44f1fdd8037d4a5b9ea7f3b41461e268cd0ef7` |
| Procedure | `sha256sum contracts/eventstatus.py` from the repository root (bytes as stored, UTF-8, LF) |
| Runner | `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` |
| Deployment | **None.** No deployment was made; nothing can be called deployed, verified-on-chain or matching this source. If you deploy, retrieve the deployed code (`genlayer code <address>`), hash it and compare with the value above before describing that deployment as audited. |

## 2. Findings

### F1 - The same instant written in another timezone was classified as a reschedule (Low, CONFIRMED, FIXED)
- **Where:** `_is_move` (used by `_normalize_extraction` and `_check_finding_shape`).
- **Reproduction:** with the registered start `2026-11-05T19:00:00Z`, the claim `2026-11-06 02:00 +07:00` (the identical instant) was reported as a move, as was `2026-11-05 20:00 +01:00`.
- **Impact:** a page that merely restates the original time in local zone, mislabelled `RESCHEDULED` by a model, would have produced a false `RESCHEDULED` instead of being rejected as "not a move".
- **Fix:** when the page states date, time and timezone, instants are compared with deterministic calendar arithmetic (`_epoch_minutes`); otherwise only stated parts can differ.
- **Regression tests:** `test_epoch_arithmetic_matches_python_datetime_on_thousands_of_dates` (4,000 random instants against Python's `datetime`), `test_is_move_compares_instants_when_the_timezone_is_explicit` (14 cases), `test_same_instant_restated_in_local_time_is_not_a_reschedule_end_to_end`; mutants N10, N11, N12.

### Test-suite gaps found by mutation (not contract defects, all closed)
| Gap | How it was found | Closed by |
|---|---|---|
| Validator-side comparison of `claim` was not pinned: earlier tests changed the *page* together with the judgement, so a different rule (literal quote) rejected first | mutant V03 survived | `test_same_page_different_judgement_is_rejected_for_every_source` (7 judgements x 3 sources) |
| Validator-side comparison of `outcome` was not pinned for "no claim of a different kind" (no status vs ambiguous vs contradictory vs wrong event), which changes the decision | mutant V04 survived | `test_two_nodes_that_both_find_no_claim_but_of_a_different_kind_must_not_agree` (24 cases) |
| Binding of findings to the registered `source_id`/`url` was masked by the digest check | mutant V12 survived | digest-consistent forgeries (`test_consistent_forgeries_are_rejected_by_the_semantic_checks`) |
| The pre-storage structural guard was unreachable with an honest leader | mutant V13 survived | `test_the_pre_storage_guard_refuses_an_inconsistent_accepted_result` (injects an inconsistent result into the leader path, modelling "consensus accepted something inconsistent") |

### Process notes
- A background mutation run was interrupted when the working session was recycled. Mutants are written to a temporary directory and loaded through `EVENTSTATUS_CONTRACT`, so the contract file was never touched; its hash was checked afterwards and is the one above. The runs were repeated in foreground batches on the final source.
- Several of my own first-draft tests were wrong (substring-vs-regex use of `expect_revert`, an assertion that a no-op reversal changed something, an input that was in fact a legitimate partial quote, missing declarations for strict mocks). They were corrected; none hid a contract defect.

## 3. Requirement-by-requirement review

| Requirement | Result |
|---|---|
| Registration and immutable source configuration | Implemented; no update path exists (checked from the SDK schema markers); corrections are new registrations |
| Explicit deterministic resolution rules | `PRIORITY_V1`, verified exhaustively against an independent oracle and 8 properties |
| Evidence-backed per-source findings | Every claim needs a substantive literal quote; failures are explicit retrieval facts |
| Independent substantive validator checks of the complete core result | Every material field is re-derived by every validator; derived fields are recomputed |
| Rejection of conflicting leader/validator findings | 4,050 fuzzed forgeries + targeted tests; no disagreement with the independent oracle |
| No false conclusions from missing, stale or transient failures | A retrieval failure is never a status; an unreachable-for-everyone source is recorded as such; "no usable source" is `INSUFFICIENT_EVIDENCE` |
| Exact request-keyed retrieval, no overwrites, no wallet-list logic | Global `request_id` key, duplicates rejected, per-event ordered index, 6 stateful invariants over 900 fuzzed steps |
| Supported, correctly declared storage | Only SDK types; calldata round-trip of every view result tested |
| Prompt-injection defenses and strict output validation | Per-source fixed prompts, delimiters, schema with exact keys and enums, rejection of malformed output; honest limits below |
| Linter and available integration checks | Linter passed; integration suite written, **not executed** |

## 4. Residual risks and limitations (unresolved)

1. **Identically fooled models.** If every node's model obeys the same injection (or misjudges the same page) and cites a real sentence of that page, the result is consistent and accepted. Defense is layered (isolation, delimiters, fixed schema, independent re-derivation), not immune. Pinned by `test_C19_documented_limitation_...`.
2. **Quote relevance is not machine-checked.** A quote proves presence, substance and origin, not that it supports the claim. Pinned by `test_B17_documented_limitation_...`.
3. **Raw HTML only.** JavaScript-rendered content is invisible; CSS-hidden text is not detected and can carry a quote or an injection. Prefer official, compact, machine-readable pages.
4. **Redirects and web-module behavior unobserved.** Non-200 answers (including 3xx) are recorded as `HTTP_ERROR` if surfaced; how GenVM treats redirects, content types, timeouts and oversized responses (possibly failing before contract code regains control) was not observed, and any such failure would be recorded as `UNAVAILABLE` with status 0 rather than `TOO_LARGE`.
5. **Fallback by outage.** If a higher-priority source is unreachable *for the validators*, a lower-priority one may control. It is always visible (`fallback_used`, role `SKIPPED`, `RETRIEVAL_FAILED` finding) and a leader cannot fabricate it (validators must reproduce the same failure and status code), but an attacker able to deny validators access to a source can influence the result. Consumers should treat `fallback_used` results with less confidence.
6. **Liveness cost of exact agreement.** Models that are unstable on borderline pages (identity `MATCH` vs `UNCLEAR`) cause disagreement, rotation or an undetermined transaction. This is intentional (safety over liveness) and unmeasured with real validators.
7. **First-come ids, no fees, no rate limit.** Anyone can register an unused `event_id` or `request_id` first, and anyone can request unlimited resolutions (each costs validators web and LLM calls, and appends to the event's index). Use unguessable request ids. A consumer must decide which events and registrants to trust.
8. **Registrant-controlled prompt data.** `title`, `organizer`, `venue` and `location` are placed in the prompt (JSON-encoded, ASCII-escaped, not delimiter-sanitized). A registrant can embed instructions in them, but a registrant already chooses the sources, so they control the evidence policy of their own event anyway. Third parties cannot alter them.
9. **Source provenance is declared, not proven.** Roles and priority are registration metadata.
10. **No publication-time extraction.** Page-reported update dates are not extracted (they cannot be verified deterministically); stale pages are handled by the model's "latest explicit statement" rule and by `AMBIGUOUS`/`CONTRADICTORY` outcomes.
11. **No clock logic.** `COMPLETED`, `RESCHEDULED` to a past date, etc. are not cross-checked against time.
12. **Public data.** Up to 240 characters of page text per source are stored on chain; raw pages are not.
13. **Human review (the fourth strategy in the official prompt-injection guidance) is not implemented** by the contract; a consuming application can add it.
14. **Single policy.** Only `PRIORITY_V1` exists; any other policy would be a new version and a new registration.
15. **Hash scope.** Digests commit to the stored normalized records, not to raw page bytes, by design (live pages differ between requests).
16. **Unverified against the real executor.** The full contract was never run in the GenVM executor, Studio or a live network; only the pure logic ran inside GenVM's interpreter.
