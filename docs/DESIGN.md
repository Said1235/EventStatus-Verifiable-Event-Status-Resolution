# EventStatus - Design

This document describes the contract exactly as implemented in `contracts/eventstatus.py` (policy version `PRIORITY_V1`).

## 1. Design checklist (written before implementation)

| Area | Decision |
|---|---|
| Invariant 1 | A result is stored only if every validator independently obtained the same **material finding for every registered source**. |
| Invariant 2 | Everything not compared is **derived by pure code** from compared fields and recomputed by every node (no third category). |
| Invariant 3 | A retrieval problem is a per-source *fact*, never an event-status finding; absence of evidence never becomes `SCHEDULED` or `CANCELLED`. |
| Invariant 4 | The evidence policy (URLs, order, roles, policy version) is frozen at registration and cannot be changed by anyone. |
| Invariant 5 | A stored result is immutable and retrievable by its own exact key; no wallet-list or "latest" lookup exists. |
| Model role | The model only *proposes* `(identity, status, schedule parts, quote)` for one page. The contract gates, validates and derives everything else. |
| Non-goals | Source discovery, event guarantees, legal truth, payments, tokens, betting, admin powers, frontend/backend. |

## 2. Registration and immutable configuration

`register_event(event_id, title, organizer, venue, location, scheduled_start, source_urls, source_roles, supersedes)`

- `event_id`: `[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}`, unique. Text fields: 1-120 characters, no control characters.
- `scheduled_start`: ISO-8601 `YYYY-MM-DDTHH:MM[:SS](Z|+HH:MM|-HH:MM)`, real calendar date (2000-2100, leap years), hour 00-23, minute 00-59, offset up to +/-14:xx. **An explicit timezone is mandatory.**
- Sources: 2-3 (application bound, not a protocol limit). Each URL passes the hardened public-HTTPS validator (https only, no credentials/fragment/whitespace, port 443 only, lowercase ASCII DNS name with valid labels, at least two labels, no trailing dot, alphabetic or `xn--` top-level domain that is not reserved, never an IP literal, <= 300 characters). Duplicates (case-insensitive) are rejected. Roles: `ORGANIZER, VENUE, TICKETING, AUTHORITY, MEDIA, OTHER`.
- Source ids are `S1..S3` **in priority order**; the order is the priority policy.
- Stored: all of the above plus the registrant, the deterministic transaction timestamp (`gl.message_raw["datetime"]`), `policy_version` and `supersedes`.
- No method updates an event. A correction is a new registration; `supersedes` (optional) links it to an earlier event and may only be set by that event's registrant. The old event, its sources and its results are untouched.
- **Provenance limitation:** a caller-supplied URL does not prove that the site belongs to the named organizer. Roles and priority are declared registration metadata.

## 3. Evidence retrieval (per source)

`gl.nondet.web.get(url)` is called for each registered URL only.

| Condition | `retrieval` | `http_status` |
|---|---|---|
| status 200, valid UTF-8, visible text 1..24,000 characters, body <= 150,000 bytes | `OK` | 200 |
| status 408, 429 or >= 500 | `UNAVAILABLE` | the status |
| exception while fetching | `UNAVAILABLE` | 0 |
| any other non-200 status (3xx, 204, 4xx) | `HTTP_ERROR` | the status |
| empty body, not UTF-8, or no visible text | `NOT_TEXT` | 200 |
| body > 150,000 bytes or visible text > 24,000 characters | `TOO_LARGE` | 200 |

Anything not `OK` yields outcome `RETRIEVAL_FAILED`. Content is **never truncated**: an oversized page is a retrieval failure, so a notice at its end cannot be silently dropped. The limits are application-level choices.

**Visible text** (deterministic, linear-time, verified identical in GenVM's CPython): remove HTML comments, `<script>` and `<style>` blocks (an unterminated block removes the rest), replace tags by spaces (`<` opens a tag only before a letter, `/`, `!` or `?`), decode HTML entities, delete zero-width characters, collapse whitespace. Hidden-by-CSS text cannot be detected; JavaScript-rendered content is not seen.

## 4. Extraction and normalization (per source, one prompt each)

The prompt is fixed in code; the page is delimited and declared untrusted data; `<<<` / `>>>` inside the page are neutralized; the registered event comes from storage; the model must answer a strict JSON object:

`{"identity": MATCH|MISMATCH|UNCLEAR, "status": SCHEDULED|RESCHEDULED|POSTPONED|CANCELLED|COMPLETED|NONE|AMBIGUOUS|CONTRADICTORY, "reschedule_date", "reschedule_time", "reschedule_tz", "excerpt"}`

Missing, extra or mistyped fields, unknown enum values or non-JSON output abort the transaction (`[LLM_ERROR]`); nothing is coerced. Then the contract applies, in order:

1. `identity != MATCH` -> outcome `IDENTITY_UNCONFIRMED`; everything else cleared.
2. `status` in `NONE / AMBIGUOUS / CONTRADICTORY` -> `NO_EXPLICIT_STATUS / AMBIGUOUS / CONTRADICTORY`; an optional quote is kept only if substantive and literal.
3. An explicit claim needs a **substantive literal quote**: it occurs verbatim in the visible text (whitespace-normalized) and is 12-240 characters (or is the whole, shorter page). Otherwise the outcome is `AMBIGUOUS` and the claim is dropped.
4. `RESCHEDULED` needs a real `reschedule_date`; an optional time must be real; a timezone is only valid together with a time; and it must be a **real move**: when the page states date, time and timezone, the *instants* are compared (the same moment written in another zone is not a reschedule); otherwise only what is stated can differ. Any other claim must carry no schedule fields. Violations -> `AMBIGUOUS`.
5. `reschedule_precision` is derived: `NONE`, `DATE_ONLY`, `TZ_AMBIGUOUS` (date and time explicit, timezone not) or `FULL`. A missing timezone is never guessed or converted.

## 5. Resolution policy `PRIORITY_V1`

Sources are in registered order. *Skippable* outcomes: `RETRIEVAL_FAILED`, `IDENTITY_UNCONFIRMED`, `NO_EXPLICIT_STATUS`. The **first non-skippable source** decides:

| First non-skippable source | Final status | `method` | `reason` |
|---|---|---|---|
| `VALID_CLAIM` | its claim (`controlling_source` = it; `fallback_used` = it is not S1) | `AGREEMENT`, or `PRIORITY_RULE` if any lower valid claim disagrees | - |
| `AMBIGUOUS` | `INSUFFICIENT_EVIDENCE` | `NONE` | `CONTROLLING_SOURCE_AMBIGUOUS` |
| `CONTRADICTORY` | `CONFLICTING_SOURCES` | `NONE` | `CONTROLLING_SOURCE_CONTRADICTORY` |
| none (all skippable) and every retrieved page failed identity | `EVENT_IDENTITY_UNCONFIRMED` | `NONE` | `IDENTITY_UNCONFIRMED_ALL_RETRIEVED` |
| none (all skippable) otherwise | `INSUFFICIENT_EVIDENCE` | `NONE` | `NO_USABLE_SOURCE` |

- There is **no fallback past an ambiguous or contradictory source**: such a source addresses the event but does not settle it.
- Lower-priority claims never override a controlling one, but nothing is discarded: each disagreeing valid source gets role `OVERRIDDEN` and a `conflicts` entry (`STATUS_MISMATCH`, or `RESCHEDULE_MISMATCH` when both say `RESCHEDULED` with different schedules); every `CONTRADICTORY` source gets an `INTERNAL_CONTRADICTION` entry. Conflicts are listed in source order, at most one per source.
- Decision roles: `CONTROLLING`, `SUPPORTING`, `OVERRIDDEN`, `SKIPPED` (above the controlling source), `BLOCKING`, `BLOCKED` (valid but below a blocking source), `UNUSABLE`.
- With a strict total order, "two valid claims the policy cannot reconcile" cannot occur; `CONFLICTING_SOURCES` arises when the controlling source contradicts itself.
- The policy is verified exhaustively: all 1,452 combinations of per-source outcomes (11 states, 2 and 3 sources) against an independently written oracle and 8 semantic properties.

## 6. Stored result and commitments

A resolution stores (see README for the field list) the derived decision plus one finding per source. Two commitments, both SHA-256 over canonical JSON (sorted keys, no spaces, ASCII escapes, UTF-8):

- `evidence_digest` (per source): the **normalized evidence record** - `source_id, url, retrieval, http_status, outcome, claim, reschedule_date, reschedule_time, reschedule_tz, reschedule_precision, excerpt`.
- `result_digest`: the complete result without itself (event id, request id, policy version, decision fields, `new_start_*`, every finding including its digest and role, all conflicts).

These are hashes of what the contract *stored*, not of the raw page: live pages differ between requests (ads, timestamps), so a raw-response hash cannot be verified by independent nodes and the contract does not claim one. Evidence integrity rests on independent re-retrieval and re-extraction by every validator plus the literal-quote check.

## 7. Consensus (`gl.vm.run_nondet_unsafe`)

The leader fetches and extracts every source and builds the complete result; each validator runs `validator_fn`:

| Check | Where |
|---|---|
| leader result is a `Return` with exactly the expected keys/types; ids and policy version equal the stored event/request | `_check_core` |
| one finding per registered source, with the registered id and URL, in order; per-finding invariants (retrieval class <-> status code <-> outcome, claim <-> schedule parts <-> precision, quote rules) | `_check_core` |
| `evidence_digest` of each finding and `result_digest` recomputed; **the whole result equals what the policy derives from the leader's own findings** (final status, method, reason, controlling source, fallback flag, new schedule, roles, conflicts) | `_check_core` |
| the validator **independently fetches and extracts every source** and obtains identical `source_id, url, retrieval, http_status, outcome, claim, reschedule_date/time/tz, reschedule_precision` | `validator_fn` |
| every leader excerpt is a substantive literal quote of the validator's **own** visible text | `validator_fn` |

The only field allowed to differ between nodes is the *wording* of an excerpt. There is no tolerance, score or "same bucket" rule. If the leader's execution failed, the validator redoes the work: only a reproduced deterministic input error (`[EXPECTED]` with an identical message) agrees; `[LLM_ERROR]` and VM-level errors never agree. Any exception inside the validator is a disagreement.

After consensus `_check_core` runs again on the accepted result (defense in depth) and only then is anything written. Each source is evaluated with its **own prompt**, so one page cannot influence another source's extraction.

## 8. Failure handling

| Situation | Behavior |
|---|---|
| unknown event, used/invalid `request_id`, bad registration input | `[EXPECTED]` revert before any fetch; nothing stored |
| source unreachable, 4xx/5xx, empty, not text, too large | recorded as `RETRIEVAL_FAILED` for that source (consensus verifies the same retrieval class and status code on every node); never a status |
| model output malformed / missing / extra field / bad enum / not JSON | `[LLM_ERROR]` revert; nothing stored; a new leader is tried by the protocol |
| validators disagree, or no majority | the protocol's own retry/rotation/undetermined path; nothing stored by the contract |
| accepted result inconsistent (should be unreachable) | `[EXPECTED] consensus result failed structural verification` revert; nothing stored |

An `INSUFFICIENT_EVIDENCE` or `CONFLICTING_SOURCES` result is a completed business outcome that *is* stored. A transaction that errors, is cancelled or stays undetermined has **no** stored result.

## 9. Storage

```
events:      TreeMap[str, Event]        key = event_id
resolutions: TreeMap[str, Resolution]   key = request_id (global)
Event:       event_id, title, organizer, venue, location, scheduled_start, registrant, registered_at,
             supersedes, policy_version, sources: DynArray[Source], resolution_ids: DynArray[str]
Source:      source_id, url, role
Resolution:  request_id, event_id, requester, resolved_at, policy_version, final_status, method, reason,
             controlling_source, fallback_used: bool, new_start_{date,time,tz,precision},
             findings: DynArray[Finding], conflicts: DynArray[Conflict], result_digest
Finding:     source_id, url, retrieval, http_status: u32, outcome, claim, reschedule_{date,time,tz,precision},
             excerpt, evidence_digest, decision_role
Conflict:    kind, source_id, claim
```

Only SDK storage types are used (`TreeMap`, `DynArray`, `@allow_storage` dataclasses, `u32`, `bool`, `Address`, `str`). Each resolution is stored under its own `request_id`, which is rejected if already used, so a record is never overwritten; multiple resolutions of one event coexist and are listed in acceptance order through `get_event_resolution_id`. The raw page is never stored; stored text is bounded (excerpt <= 240 characters, URL <= 300).

## 10. Application-level limits (not GenLayer protocol limits)

2-3 sources; ids <= 64; text fields <= 120; URL <= 300; response <= 150,000 bytes; visible text <= 24,000 characters; excerpt 12-240 characters.
