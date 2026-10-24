"""Shared helpers for the EventStatus direct-mode tests.

Mock world
----------
Every test builds a "world": for each registered source a web page (or an HTTP failure) and
the answer the extraction model gives for that page. Strict mocks are always enabled, so a
call the contract makes that the test did not declare raises instead of being silently
answered (an undeclared web request therefore surfaces as a retrieval failure, an undeclared
model call as an LLM error).

Consensus model
---------------
Direct mode executes only the LEADER path and captures the validator. To model the protocol:
the leader proposes (``capture_leader``), the state is reverted (a result is applied only if
validators accept it), a possibly forged result is submitted to the captured validator under
a possibly DIFFERENT world (what the validator would see), and the stored state is checked.
This models consensus; it is not real multi-validator consensus.
"""

import copy
import hashlib
import json
import os
import sys

CONTRACT = os.environ.get("EVENTSTATUS_CONTRACT", "contracts/eventstatus.py")

EVENT_ID = "evt-devcon-2026"
TITLE = "Global DevCon 2026"
ORGANIZER = "DevCon Foundation"
VENUE = "Grand Hall"
LOCATION = "Lisbon, Portugal"
START = "2026-11-05T19:00:00Z"

U1 = "https://organizer.example.com/devcon-2026"
U2 = "https://venue.example.net/events/devcon"
U3 = "https://tickets.example.org/devcon-2026"
URLS = [U1, U2, U3]
ROLES = ["ORGANIZER", "VENUE", "TICKETING"]
HOSTS = {"S1": r"organizer\.example\.com", "S2": r"venue\.example\.net", "S3": r"tickets\.example\.org"}

# Page bodies. The quoted sentences are what the model "cites".
Q_SCHEDULED = "The event is confirmed and going ahead as planned."
Q_CANCELLED = "Global DevCon 2026 has been cancelled."
Q_POSTPONED = "Global DevCon 2026 has been postponed until further notice."
Q_RESCHEDULED = "Global DevCon 2026 has been moved to 12 December 2026 at 18:00 CET (UTC+1)."
Q_COMPLETED = "Global DevCon 2026 took place on 5 November 2026 and has now concluded."


def page(sentence: str, extra: str = "") -> str:
    return (
        "<html><head><title>Global DevCon 2026</title><style>p{color:red}</style></head><body>"
        "<h1>Global DevCon 2026</h1><p>Hosted by DevCon Foundation at Grand Hall, Lisbon.</p>"
        f"<p>{sentence}</p>{extra}<script>var x = 'ignored';</script></body></html>"
    )


PAGE_SCHEDULED = page(Q_SCHEDULED)
PAGE_CANCELLED = page(Q_CANCELLED)
PAGE_POSTPONED = page(Q_POSTPONED)
PAGE_RESCHEDULED = page(Q_RESCHEDULED)
PAGE_COMPLETED = page(Q_COMPLETED)
PAGE_NO_STATUS = "<html><body><h1>DevCon Foundation</h1><p>Welcome. Latest news, sponsors and press kit.</p></body></html>"


def ans(status="SCHEDULED", quote=None, identity="MATCH", date=None, time=None, tz=None):
    """The answer the extraction model gives for one page."""
    return {
        "identity": identity,
        "status": status,
        "reschedule_date": date,
        "reschedule_time": time,
        "reschedule_tz": tz,
        "excerpt": quote,
    }


A_SCHEDULED = ans("SCHEDULED", Q_SCHEDULED)
A_CANCELLED = ans("CANCELLED", Q_CANCELLED)
A_POSTPONED = ans("POSTPONED", Q_POSTPONED)
A_RESCHEDULED = ans("RESCHEDULED", Q_RESCHEDULED, date="2026-12-12", time="18:00", tz="+01:00")
A_COMPLETED = ans("COMPLETED", Q_COMPLETED)
A_NONE = ans("NONE", None)


def mock_world(vm, pages=None, answers=None, strict=True):
    """``pages``: source id -> html str | int (HTTP status) | bytes. A missing source id has no
    web mock at all (a network failure). ``answers``: source id -> dict | str (raw model text)."""
    vm.clear_mocks()
    vm.strict_mocks = strict
    pages = pages or {}
    answers = answers or {}
    for sid, spec in pages.items():
        if isinstance(spec, int):
            vm.mock_web(HOSTS[sid], {"status": spec, "body": ""})
        else:
            body = spec.encode("utf-8") if isinstance(spec, str) else spec
            vm.mock_web(HOSTS[sid], {"status": 200, "body": body})
    for sid, spec in answers.items():
        vm.mock_llm(rf"SOURCE_ID: {sid}\n", spec if isinstance(spec, str) else json.dumps(spec))


def world(vm, spec):
    """Compact form: ``{"S1": (PAGE_CANCELLED, A_CANCELLED), "S2": 404, "S3": None}``.
    A tuple is (page, answer); an int is an HTTP status; None means no web mock (network failure)."""
    pages, answers = {}, {}
    for sid, item in spec.items():
        if item is None:
            continue
        if isinstance(item, int):
            pages[sid] = item
        else:
            pages[sid] = item[0]
            if item[1] is not None:
                answers[sid] = item[1]
    mock_world(vm, pages, answers)


def optional(vm):
    """Declare the mocks registered so far as optional: a validator that rejects a forged result
    on structure alone (fail fast) legitimately never fetches the sources."""
    vm._web_mocks_hit.update(range(len(vm._web_mocks)))
    vm._llm_mocks_hit.update(range(len(vm._llm_mocks)))


def hex_of(address) -> str:
    if hasattr(address, "as_hex"):
        return address.as_hex
    from genlayer.py.types import Address  # importable once a contract was deployed

    return Address(address).as_hex


def module(vm):
    """Python module of the contract loaded in direct mode (for the pure functions)."""
    return sys.modules["_contract_eventstatus"]


def register(contract, vm, sender, event_id=EVENT_ID, urls=None, roles=None, start=START, supersedes=""):
    vm.sender = sender
    contract.register_event(
        event_id, TITLE, ORGANIZER, VENUE, LOCATION, start,
        urls if urls is not None else URLS, roles if roles is not None else ROLES, supersedes,
    )


def new_event(vm, deploy, sender, **kwargs):
    contract = deploy(CONTRACT)
    register(contract, vm, sender, **kwargs)
    return contract


def resolve(contract, vm, sender, request_id="req-1", event_id=EVENT_ID):
    vm.sender = sender
    return contract.resolve_event(event_id, request_id)


def capture_leader(vm, contract, sender, request_id="req-1", event_id=EVENT_ID):
    """The leader proposes; the state is reverted until a validator accepts."""
    snap = vm.snapshot()
    vm.sender = sender
    contract.resolve_event(event_id, request_id)
    captured = vm._captured_validators[-1]
    proposal = copy.deepcopy(captured[0])
    # revert() also rolls back the strict-mock "was used" bookkeeping; the leader really did use
    # those mocks, so carry the bookkeeping across (otherwise they would be reported as stale).
    web_hit, llm_hit = set(vm._web_mocks_hit), set(vm._llm_mocks_hit)
    vm.revert(snap)
    vm._web_mocks_hit |= web_hit
    vm._llm_mocks_hit |= llm_hit
    vm._captured_validators.append(captured)
    return proposal


def validator_accepts(vm, proposal) -> bool:
    return vm.run_validator(leader_result=proposal) is True


def assert_not_stored(contract, request_id="req-1", event_id=EVENT_ID):
    assert contract.get_resolution(request_id) == {"found": False, "request_id": request_id}
    assert contract.get_event(event_id)["resolution_count"] == 0


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


# --------------------------------------------------------------------------- #
# Independent recomputation of the stored commitments (spec of the digests, not contract code)
# --------------------------------------------------------------------------- #

EVIDENCE_KEYS = (
    "source_id", "url", "retrieval", "http_status", "outcome", "claim", "reschedule_date",
    "reschedule_time", "reschedule_tz", "reschedule_precision", "excerpt",
)


def evidence_digest_of(finding: dict) -> str:
    """sha256 over the canonical JSON of the NORMALIZED evidence record of one source."""
    return sha256_hex(canonical({k: finding[k] for k in EVIDENCE_KEYS}))


def result_digest_of(res: dict) -> str:
    """sha256 over the canonical JSON of the complete result without its own digest field."""
    core = {k: res[k] for k in (
        "policy_version", "final_status", "method", "reason", "controlling_source", "fallback_used",
        "new_start_date", "new_start_time", "new_start_tz", "new_start_precision", "conflicts")}
    core["event_id"], core["request_id"] = res["event_id"], res["request_id"]
    core["findings"] = [
        {**{k: f[k] for k in EVIDENCE_KEYS}, "evidence_digest": f["evidence_digest"], "decision_role": f["decision_role"]}
        for f in res["findings"]
    ]
    return sha256_hex(canonical(core))


def assert_commitments_hold(res: dict):
    for f in res["findings"]:
        assert f["evidence_digest"] == evidence_digest_of(f), f["source_id"]
    assert res["result_digest"] == result_digest_of(res)


def roles_of(res: dict):
    return [f["decision_role"] for f in res["findings"]]


def spy(vm):
    """Record every web URL and model prompt the contract asks for (strict mocks still apply)."""
    log = {"web": [], "llm": []}
    real_web, real_llm = vm._match_web_mock, vm._match_llm_mock

    def web(*a, **k):
        log["web"].append(a[0])
        return real_web(*a, **k)

    def llm(*a, **k):
        log["llm"].append(a[0])
        return real_llm(*a, **k)

    vm._match_web_mock, vm._match_llm_mock = web, llm
    return log
