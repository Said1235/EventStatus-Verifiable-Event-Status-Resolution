"""EventStatus - integration tests (leader + validators consensus).

Run against a GenLayer network that provides consensus:

    gltest tests/integration/test_eventstatus.py -v -s

Targets:
  * GenLayer Studio - the reference environment (NOT executed in the environment where this
    suite was written: no Docker and no network access to Studio).
  * GLSim - a local simulator. GLSim 0.29.2 breaks every deployment after the first one of the
    same file and assigns one fixed sender to every transaction, so it cannot be used for the
    multi-account flows below; ``python tools/run_glsim_nocache.py`` only works around the first
    problem.

Validators here are MOCK validators: the web pages and the model answers are fixed so outcomes
are deterministic, while consensus itself (leader proposal, every validator independently
re-fetching and re-extracting every source, majority vote, state applied only after acceptance)
is real. An opt-in live test uses real LLM validators and real pages:

    EVENTSTATUS_LIVE_URLS='["https://...","https://..."]' gltest tests/integration/test_eventstatus.py -k live -s

API note: with genlayer-test 0.29.x a contract method is invoked as
``contract.method(args=[...]).call()`` (reads) or ``.transact(...)`` (writes).
The mock-validator keys (``nondet_exec_prompt`` substring, ``nondet_web_request`` by URL) follow
the gltest documentation and are unproven on Studio until this suite is run there.
"""

import json
import os

import pytest
from gltest import create_accounts, get_contract_factory, get_validator_factory
from gltest.assertions import tx_execution_succeeded
from gltest.exceptions import DeploymentError

EVENT_ID = "evt-devcon-2026"
U1 = "https://organizer.example.com/devcon-2026"
U2 = "https://venue.example.net/events/devcon"
U3 = "https://tickets.example.org/devcon-2026"
URLS = [U1, U2, U3]
ROLES = ["ORGANIZER", "VENUE", "TICKETING"]
START = "2026-11-05T19:00:00Z"
VALIDATORS = 5
WAIT = {"wait_interval": 10000, "wait_retries": 30}

Q_CANCELLED = "Global DevCon 2026 has been cancelled."
Q_SCHEDULED = "The event is confirmed and going ahead as planned."


def html(sentence):
    return f"<html><body><h1>Global DevCon 2026</h1><p>Hosted by DevCon Foundation at Grand Hall, Lisbon.</p><p>{sentence}</p></body></html>"


def answer(status, quote=None, identity="MATCH"):
    return json.dumps({"identity": identity, "status": status, "reschedule_date": None,
                       "reschedule_time": None, "reschedule_tz": None, "excerpt": quote})


CANCELLED = answer("CANCELLED", Q_CANCELLED)
SCHEDULED = answer("SCHEDULED", Q_SCHEDULED)


def _context(pages, answers):
    """``pages``: url -> (status, body); ``answers``: source id -> model answer (JSON text)."""
    validators = get_validator_factory().batch_create_mock_validators(
        count=VALIDATORS,
        mock_llm_response={"nondet_exec_prompt": {f"SOURCE_ID: {sid}\n": text for sid, text in answers.items()}},
        mock_web_response={"nondet_web_request": {
            url: {"method": "GET", "status": status, "body": body} for url, (status, body) in pages.items()}},
    )
    return {"validators": [v.to_dict() for v in validators]}


def _tx(contract, account, method, args, context=None, **wait):
    bound = contract.connect(account)
    return getattr(bound, method)(args=args).transact(transaction_context=context, **(wait or WAIT))


def _read(contract, method, args):
    return getattr(contract, method)(args=args).call()


@pytest.fixture
def parties():
    accounts = create_accounts(n_accounts=3)
    return {"registrant": accounts[0], "caller": accounts[1], "other": accounts[2]}


@pytest.fixture
def eventstatus():
    """A freshly deployed EventStatus (retried: GLSim 0.29.2 fails every other deployment)."""
    last = None
    for _ in range(4):
        try:
            return get_contract_factory("EventStatus").deploy(args=[])
        except DeploymentError as error:
            last = error
    raise last


def _register(contract, parties, event_id=EVENT_ID):
    result = _tx(contract, parties["registrant"], "register_event",
                 [event_id, "Global DevCon 2026", "DevCon Foundation", "Grand Hall", "Lisbon, Portugal", START, URLS, ROLES, ""])
    assert tx_execution_succeeded(result)


MIXED_PAGES = {U1: (200, html(Q_CANCELLED)), U2: (200, html(Q_SCHEDULED)), U3: (503, "")}
MIXED_ANSWERS = {"S1": CANCELLED, "S2": SCHEDULED}


@pytest.mark.integration
def test_register_resolve_and_read_back_by_request_id(eventstatus, parties):
    _register(eventstatus, parties)
    event = _read(eventstatus, "get_event", [EVENT_ID])
    assert event["found"] and [s["url"] for s in event["sources"]] == URLS and event["resolution_count"] == 0

    result = _tx(eventstatus, parties["caller"], "resolve_event", [EVENT_ID, "req-1"], _context(MIXED_PAGES, MIXED_ANSWERS))
    assert tx_execution_succeeded(result)

    res = _read(eventstatus, "get_resolution", ["req-1"])
    assert res["found"] and res["request_id"] == "req-1" and res["event_id"] == EVENT_ID
    assert res["final_status"] == "CANCELLED" and res["method"] == "PRIORITY_RULE" and res["controlling_source"] == "S1"
    assert [f["decision_role"] for f in res["findings"]] == ["CONTROLLING", "OVERRIDDEN", "UNUSABLE"]
    assert [(c["kind"], c["source_id"]) for c in res["conflicts"]] == [("STATUS_MISMATCH", "S2")]
    s3 = res["findings"][2]
    assert (s3["retrieval"], s3["http_status"], s3["outcome"]) == ("UNAVAILABLE", 503, "RETRIEVAL_FAILED")
    assert res["findings"][0]["excerpt"] == Q_CANCELLED and len(res["result_digest"]) == 64
    assert _read(eventstatus, "get_event_resolution_id", [EVENT_ID, 1]) == "req-1"


@pytest.mark.integration
def test_fallback_is_recorded_when_the_top_source_is_down(eventstatus, parties):
    _register(eventstatus, parties)
    pages = {U1: (404, ""), U2: (200, html(Q_SCHEDULED)), U3: (200, html(Q_SCHEDULED))}
    assert tx_execution_succeeded(_tx(eventstatus, parties["caller"], "resolve_event", [EVENT_ID, "req-fb"],
                                      _context(pages, {"S2": SCHEDULED, "S3": SCHEDULED})))
    res = _read(eventstatus, "get_resolution", ["req-fb"])
    assert res["final_status"] == "SCHEDULED" and res["fallback_used"] is True and res["controlling_source"] == "S2"
    assert res["findings"][0]["retrieval"] == "HTTP_ERROR" and res["findings"][0]["decision_role"] == "SKIPPED"


@pytest.mark.integration
def test_no_usable_evidence_never_becomes_a_status(eventstatus, parties):
    _register(eventstatus, parties)
    pages = {U1: (500, ""), U2: (404, ""), U3: (503, "")}
    assert tx_execution_succeeded(_tx(eventstatus, parties["caller"], "resolve_event", [EVENT_ID, "req-down"], _context(pages, {})))
    res = _read(eventstatus, "get_resolution", ["req-down"])
    assert res["final_status"] == "INSUFFICIENT_EVIDENCE" and res["reason"] == "NO_USABLE_SOURCE" and res["controlling_source"] == ""


@pytest.mark.integration
def test_unusable_model_output_leaves_no_record(eventstatus, parties):
    """An LLM format error is an execution error, not a business decision: nothing is stored."""
    _register(eventstatus, parties)
    pages = {U1: (200, html(Q_CANCELLED)), U2: (200, html(Q_SCHEDULED)), U3: (200, html(Q_SCHEDULED))}
    result = _tx(eventstatus, parties["caller"], "resolve_event", [EVENT_ID, "req-bad"],
                 _context(pages, {"S1": "this is not json", "S2": SCHEDULED, "S3": SCHEDULED}))
    assert not tx_execution_succeeded(result)
    assert _read(eventstatus, "get_resolution", ["req-bad"])["found"] is False
    assert _read(eventstatus, "get_event", [EVENT_ID])["resolution_count"] == 0


@pytest.mark.integration
def test_duplicate_request_ids_and_overlapping_requests_keep_records_apart(eventstatus, parties):
    _register(eventstatus, parties)
    ctx_cancelled = _context({U: (200, html(Q_CANCELLED)) for U in URLS}, {s: CANCELLED for s in ("S1", "S2", "S3")})
    ctx_scheduled = _context({U: (200, html(Q_SCHEDULED)) for U in URLS}, {s: SCHEDULED for s in ("S1", "S2", "S3")})
    assert tx_execution_succeeded(_tx(eventstatus, parties["caller"], "resolve_event", [EVENT_ID, "req-a"], ctx_cancelled))
    assert tx_execution_succeeded(_tx(eventstatus, parties["other"], "resolve_event", [EVENT_ID, "req-b"], ctx_scheduled))
    first = _read(eventstatus, "get_resolution", ["req-a"])

    # reusing a request id fails and never overwrites
    assert not tx_execution_succeeded(_tx(eventstatus, parties["other"], "resolve_event", [EVENT_ID, "req-a"], ctx_scheduled))
    assert _read(eventstatus, "get_resolution", ["req-a"]) == first

    a, b = _read(eventstatus, "get_resolution", ["req-a"]), _read(eventstatus, "get_resolution", ["req-b"])
    assert (a["final_status"], b["final_status"]) == ("CANCELLED", "SCHEDULED") and a["result_digest"] != b["result_digest"]
    assert a["requester"].lower() == parties["caller"].address.lower() and b["requester"].lower() == parties["other"].address.lower()
    assert [_read(eventstatus, "get_event_resolution_id", [EVENT_ID, i]) for i in (1, 2)] == ["req-a", "req-b"]


@pytest.mark.integration
def test_registration_is_immutable_and_unique(eventstatus, parties):
    _register(eventstatus, parties)
    before = _read(eventstatus, "get_event", [EVENT_ID])
    again = _tx(eventstatus, parties["other"], "register_event",
                [EVENT_ID, "Hijack", "Someone", "Elsewhere", "Nowhere", START, [U3, U2], ["OTHER", "OTHER"], ""])
    assert not tx_execution_succeeded(again)
    assert _read(eventstatus, "get_event", [EVENT_ID]) == before


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("EVENTSTATUS_LIVE_URLS"),
                    reason='set EVENTSTATUS_LIVE_URLS (JSON list of 2-3 public https pages) to run with real LLM validators')
def test_live_validators_reach_consensus_on_real_pages(eventstatus, parties):
    """Opt-in: real web fetch and real LLM validators (no mocks)."""
    urls = json.loads(os.environ["EVENTSTATUS_LIVE_URLS"])
    roles = ["OTHER"] * len(urls)
    assert tx_execution_succeeded(_tx(eventstatus, parties["registrant"], "register_event",
                                      ["evt-live", "Live check", "Live organizer", "Live venue", "Live city", START, urls, roles, ""]))
    result = _tx(eventstatus, parties["caller"], "resolve_event", ["evt-live", "req-live"], None, wait_interval=15000, wait_retries=60)
    assert tx_execution_succeeded(result)
    res = _read(eventstatus, "get_resolution", ["req-live"])
    assert res["found"] and len(res["findings"]) == len(urls) and len(res["result_digest"]) == 64
