"""EventStatus - request-keyed storage, overlapping evaluations and global invariants (E36-E43)."""

import copy
import json
import random

import pytest

from tests.direct.eventstatus_support import (
    A_CANCELLED, A_NONE, A_POSTPONED, A_RESCHEDULED, A_SCHEDULED, CONTRACT, EVENT_ID, PAGE_CANCELLED,
    PAGE_NO_STATUS, PAGE_POSTPONED, PAGE_RESCHEDULED, PAGE_SCHEDULED, ROLES, START, U1, U2, URLS, ans,
    assert_commitments_hold, capture_leader, hex_of, mock_world, new_event, optional, register, resolve,
    validator_accepts, world,
)
from tests.direct.test_eventstatus_policy import oracle


def cancelled(vm):
    world(vm, {s: (PAGE_CANCELLED, A_CANCELLED) for s in ("S1", "S2", "S3")})


def scheduled(vm):
    world(vm, {s: (PAGE_SCHEDULED, A_SCHEDULED) for s in ("S1", "S2", "S3")})


@pytest.fixture
def ev(direct_vm, direct_deploy, direct_alice):
    return new_event(direct_vm, direct_deploy, direct_alice)


# --------------------------------------------------------------------------- #
# E38: a request id is used once
# --------------------------------------------------------------------------- #


def test_E38_reusing_a_request_id_fails_without_overwriting(direct_vm, ev, direct_alice, direct_bob):
    cancelled(direct_vm)
    resolve(ev, direct_vm, direct_alice)
    first = ev.get_resolution("req-1")
    assert first["final_status"] == "CANCELLED"

    scheduled(direct_vm)
    optional(direct_vm)  # the duplicate is refused before any source is fetched
    for sender in (direct_alice, direct_bob):  # same caller and another caller
        with direct_vm.expect_revert("request_id already used"):
            resolve(ev, direct_vm, sender)
    assert ev.get_resolution("req-1") == first
    assert ev.get_event(EVENT_ID)["resolution_count"] == 1


def test_E38_request_ids_are_global_not_per_event(direct_vm, ev, direct_alice, direct_bob):
    register(ev, direct_vm, direct_alice, event_id="evt-other")
    cancelled(direct_vm)
    resolve(ev, direct_vm, direct_alice, "shared-id", EVENT_ID)
    first = ev.get_resolution("shared-id")
    optional(direct_vm)
    with direct_vm.expect_revert("request_id already used"):
        resolve(ev, direct_vm, direct_bob, "shared-id", "evt-other")
    assert ev.get_resolution("shared-id") == first and ev.get_event("evt-other")["resolution_count"] == 0


def test_E38_two_leaders_racing_for_one_request_id_cannot_both_be_stored(direct_vm, ev, direct_alice, direct_bob):
    """Two executions prepared against the same state: the one ordered second sees the first's
    record and is refused; the stored record is the first's, untouched."""
    cancelled(direct_vm)
    p_first = capture_leader(direct_vm, ev, direct_alice)
    scheduled(direct_vm)
    p_second = capture_leader(direct_vm, ev, direct_bob)
    assert p_first["final_status"] == "CANCELLED" and p_second["final_status"] == "SCHEDULED"
    cancelled(direct_vm)
    resolve(ev, direct_vm, direct_alice)                      # ordered first
    stored = ev.get_resolution("req-1")
    scheduled(direct_vm)
    optional(direct_vm)
    with direct_vm.expect_revert("request_id already used"):  # ordered second
        resolve(ev, direct_vm, direct_bob)
    assert ev.get_resolution("req-1") == stored and stored["final_status"] == "CANCELLED"


@pytest.mark.parametrize("bad", ["", " ", "x" * 65, "-lead", "has space", "a/b", "ev\u00e9nt", "a;b"])
def test_invalid_request_ids_are_rejected(direct_vm, ev, direct_bob, bad):
    scheduled(direct_vm)
    optional(direct_vm)
    with direct_vm.expect_revert("[EXPECTED]"):
        resolve(ev, direct_vm, direct_bob, bad)


def test_unknown_event_is_rejected_before_any_source_is_fetched(direct_vm, ev, direct_bob):
    scheduled(direct_vm)
    optional(direct_vm)
    with direct_vm.expect_revert("event not found"):
        resolve(ev, direct_vm, direct_bob, "req-1", "nope")


# --------------------------------------------------------------------------- #
# E39-E42: distinct records, exact retrieval
# --------------------------------------------------------------------------- #


def test_E39_several_evaluations_of_one_event_are_distinct_and_all_retrievable(direct_vm, ev, direct_alice, direct_bob):
    cancelled(direct_vm)
    resolve(ev, direct_vm, direct_alice, "req-a")
    scheduled(direct_vm)
    resolve(ev, direct_vm, direct_bob, "req-b")
    world(direct_vm, {"S1": (PAGE_POSTPONED, A_POSTPONED), "S2": 503, "S3": None})
    resolve(ev, direct_vm, direct_alice, "req-c")

    a, b, c = (ev.get_resolution(r) for r in ("req-a", "req-b", "req-c"))
    assert [a["final_status"], b["final_status"], c["final_status"]] == ["CANCELLED", "SCHEDULED", "POSTPONED"]
    assert len({a["result_digest"], b["result_digest"], c["result_digest"]}) == 3
    assert (a["requester"], b["requester"], c["requester"]) == (hex_of(direct_alice), hex_of(direct_bob), hex_of(direct_alice))
    assert ev.get_event(EVENT_ID)["resolution_count"] == 3
    assert [ev.get_event_resolution_id(EVENT_ID, i) for i in (1, 2, 3)] == ["req-a", "req-b", "req-c"]
    assert [ev.get_event_resolution_id(EVENT_ID, i) for i in (0, 4, -1)] == ["", "", ""]
    for r in (a, b, c):
        assert_commitments_hold(r)


def test_E40_E42_each_caller_gets_their_own_result_and_lookup_is_by_request_id_not_by_wallet(direct_vm, ev, direct_alice, direct_bob):
    cancelled(direct_vm)
    resolve(ev, direct_vm, direct_alice, "alice-1")
    scheduled(direct_vm)
    resolve(ev, direct_vm, direct_alice, "alice-2")   # same wallet, newer record
    world(direct_vm, {s: (PAGE_POSTPONED, A_POSTPONED) for s in ("S1", "S2", "S3")})
    resolve(ev, direct_vm, direct_bob, "bob-1")

    assert ev.get_resolution("alice-1")["final_status"] == "CANCELLED"   # NOT "the newest of that wallet"
    assert ev.get_resolution("alice-2")["final_status"] == "SCHEDULED"
    assert ev.get_resolution("bob-1")["final_status"] == "POSTPONED"
    assert ev.get_resolution("alice-1")["requester"] == hex_of(direct_alice) == ev.get_resolution("alice-2")["requester"]
    assert ev.get_resolution("bob-1")["requester"] == hex_of(direct_bob)
    assert ev.get_resolution("alice-3") == {"found": False, "request_id": "alice-3"}


def test_E41_interleaved_and_reordered_evaluations_across_events_never_mix_findings(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = new_event(direct_vm, direct_deploy, direct_alice, event_id="evt-a")
    register(contract, direct_vm, direct_alice, event_id="evt-b")
    plan = [("evt-a", "r1", cancelled), ("evt-b", "r2", scheduled), ("evt-a", "r3", scheduled),
            ("evt-b", "r4", cancelled), ("evt-b", "r0", scheduled), ("evt-a", "r5", cancelled)]
    expected = {}
    for event_id, request_id, set_world in plan:
        set_world(direct_vm)
        resolve(contract, direct_vm, direct_bob if request_id in ("r2", "r4") else direct_alice, request_id, event_id)
        expected[request_id] = (event_id, contract.get_resolution(request_id)["final_status"])
    for request_id, (event_id, status) in expected.items():
        r = contract.get_resolution(request_id)
        assert (r["event_id"], r["final_status"], r["request_id"]) == (event_id, status, request_id)
        assert_commitments_hold(r)
    assert contract.get_event("evt-a")["resolution_count"] == 3 and contract.get_event("evt-b")["resolution_count"] == 3
    assert [contract.get_event_resolution_id("evt-a", i) for i in (1, 2, 3)] == ["r1", "r3", "r5"]
    assert [contract.get_event_resolution_id("evt-b", i) for i in (1, 2, 3)] == ["r2", "r4", "r0"]  # acceptance order


def test_a_failed_attempt_leaves_no_trace_and_the_request_id_stays_usable(direct_vm, ev, direct_bob):
    world(direct_vm, {"S1": (PAGE_SCHEDULED, "not json at all")})
    with direct_vm.expect_revert("[LLM_ERROR]"):
        resolve(ev, direct_vm, direct_bob, "retry-me")
    assert ev.get_resolution("retry-me")["found"] is False and ev.get_event(EVENT_ID)["resolution_count"] == 0
    assert ev.get_event_resolution_id(EVENT_ID, 1) == ""
    scheduled(direct_vm)
    resolve(ev, direct_vm, direct_bob, "retry-me")
    assert ev.get_resolution("retry-me")["final_status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# E43: persisted state is serializable and survives later calls
# --------------------------------------------------------------------------- #


def test_E43_persisted_records_are_calldata_serializable_and_stable_across_later_calls(direct_vm, ev, direct_alice, direct_bob):
    cancelled(direct_vm)
    resolve(ev, direct_vm, direct_alice, "req-1")
    from genlayer.py import calldata  # importable once a contract has been deployed

    snapshots = {"event": ev.get_event(EVENT_ID), "res": ev.get_resolution("req-1")}
    for value in (*snapshots.values(), ev.get_event("nope"), ev.get_resolution("nope"), ev.get_event_resolution_id(EVENT_ID, 1)):
        assert calldata.decode(calldata.encode(value)) == value
        json.dumps(value)
    for i in range(4):  # unrelated activity afterwards
        register(ev, direct_vm, direct_bob, event_id=f"evt-extra-{i}")
        scheduled(direct_vm)
        resolve(ev, direct_vm, direct_bob, f"extra-{i}", f"evt-extra-{i}")
    assert ev.get_resolution("req-1") == snapshots["res"]
    after = ev.get_event(EVENT_ID)
    assert {k: v for k, v in after.items() if k != "resolution_count"} == {k: v for k, v in snapshots["event"].items() if k != "resolution_count"}


def test_the_stored_result_is_exactly_what_the_validated_leader_proposed(direct_vm, ev, direct_alice, direct_bob):
    world(direct_vm, {"S1": (PAGE_CANCELLED, A_CANCELLED), "S2": (PAGE_SCHEDULED, A_SCHEDULED), "S3": 503})
    proposal = capture_leader(direct_vm, ev, direct_bob)
    assert validator_accepts(direct_vm, proposal) is True
    resolve(ev, direct_vm, direct_bob)
    stored = ev.get_resolution("req-1")
    for key in ("final_status", "method", "reason", "controlling_source", "fallback_used", "result_digest", "conflicts"):
        assert stored[key] == proposal[key]
    assert stored["findings"] == proposal["findings"]  # no second, different version of the result exists


# --------------------------------------------------------------------------- #
# Stateful fuzz with global invariants
# --------------------------------------------------------------------------- #

WORLDS = {
    "cancelled": lambda: {s: (PAGE_CANCELLED, A_CANCELLED) for s in ("S1", "S2", "S3")},
    "scheduled": lambda: {s: (PAGE_SCHEDULED, A_SCHEDULED) for s in ("S1", "S2", "S3")},
    "mixed": lambda: {"S1": (PAGE_CANCELLED, A_CANCELLED), "S2": (PAGE_SCHEDULED, A_SCHEDULED), "S3": (PAGE_RESCHEDULED, A_RESCHEDULED)},
    "fallback": lambda: {"S1": 503, "S2": (PAGE_POSTPONED, A_POSTPONED), "S3": None},
    "all_down": lambda: {"S1": 500, "S2": 404, "S3": None},
    "nostatus": lambda: {s: (PAGE_NO_STATUS, A_NONE) for s in ("S1", "S2", "S3")},
    "contradiction": lambda: {"S1": (PAGE_CANCELLED, ans("CONTRADICTORY", "Global DevCon 2026 has been cancelled.")), "S2": (PAGE_SCHEDULED, A_SCHEDULED), "S3": 404},
    "identity": lambda: {s: (PAGE_SCHEDULED, ans("SCHEDULED", "The event is confirmed and going ahead as planned.", identity="MISMATCH")) for s in ("S1", "S2", "S3")},
    "malformed": lambda: {"S1": (PAGE_SCHEDULED, "definitely not json")},
}
COVERAGE = set()  # (final_status, method, fallback_used) combinations reached by the fuzz
EVENT_IDS = ["e1", "e2", "e3"]
REQUEST_IDS = [f"q{i}" for i in range(1, 9)]


def check_invariants(contract, ledger, actors):
    events = {}
    for eid in EVENT_IDS:
        e = contract.get_event(eid)
        if not e["found"]:
            assert contract.get_event_resolution_id(eid, 1) == ""
            continue
        # I1: configuration is immutable
        frozen = (e["title"], e["organizer"], e["venue"], e["location"], e["scheduled_start"], e["registrant"],
                  e["registered_at"], e["supersedes"], e["policy_version"], json.dumps(e["sources"]))
        assert ledger.setdefault(("event", eid), frozen) == frozen, f"{eid}: configuration changed"
        assert [s["source_id"] for s in e["sources"]] == ["S1", "S2", "S3"][: len(e["sources"])]
        assert [s["priority"] for s in e["sources"]] == list(range(1, len(e["sources"]) + 1))
        events[eid] = e
    stored = {}
    for rid in REQUEST_IDS:
        r = contract.get_resolution(rid)
        if not r["found"]:
            continue
        stored[rid] = r
        # I2: stored results are immutable (append-only history)
        assert ledger.setdefault(("res", rid), copy.deepcopy(r)) == r, f"{rid}: record changed"
        assert r["request_id"] == rid and r["event_id"] in events
        e = events[r["event_id"]]
        # I3: findings follow the event's registered sources, in order
        assert [f["url"] for f in r["findings"]] == [s["url"] for s in e["sources"]]
        assert [f["source_id"] for f in r["findings"]] == [s["source_id"] for s in e["sources"]]
        assert r["requester"] in actors and r["resolved_at"] != "" and r["policy_version"] == "PRIORITY_V1"
        # I4: commitments recompute independently; derived fields equal the independent policy oracle
        assert_commitments_hold(r)
        want = oracle(r["findings"])
        for key in ("final_status", "method", "reason", "controlling_source", "fallback_used", "new_start_date",
                    "new_start_time", "new_start_tz", "new_start_precision"):
            assert r[key] == want[key], f"{rid}: {key}"
        assert [f["decision_role"] for f in r["findings"]] == want["roles"] and r["conflicts"] == want["conflicts"]
        # I5: no stored status without evidence, and failures never become findings
        for f in r["findings"]:
            if f["retrieval"] != "OK":
                assert f["outcome"] == "RETRIEVAL_FAILED" and f["claim"] == "" and f["excerpt"] == ""
            if f["outcome"] == "VALID_CLAIM":
                assert f["excerpt"] != ""
    # I6: the per-event index lists exactly the stored resolutions of that event, in unique order
    total = 0
    for eid, e in events.items():
        ids = [contract.get_event_resolution_id(eid, i) for i in range(1, e["resolution_count"] + 1)]
        assert len(set(ids)) == len(ids) and all(i in stored and stored[i]["event_id"] == eid for i in ids)
        assert contract.get_event_resolution_id(eid, e["resolution_count"] + 1) == ""
        assert {rid for rid, r in stored.items() if r["event_id"] == eid} == set(ids)
        total += len(ids)
    assert total == len(stored)


@pytest.mark.parametrize("seed", range(10))
def test_stateful_fuzz_invariants_hold_after_every_step_including_reverted_ones(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie, seed
):
    rng = random.Random(7000 + seed)
    contract = direct_deploy(CONTRACT)
    actors = {hex_of(a) for a in (direct_alice, direct_bob, direct_charlie)}
    people = [direct_alice, direct_bob, direct_charlie]
    ledger, stats = {}, {"ok": 0, "reverted": 0}
    for _ in range(90):
        direct_vm.sender = rng.choice(people)
        op = rng.choice(["register", "register", "resolve", "resolve", "resolve", "resolve", "read"])
        try:
            if op == "register":
                eid = rng.choice(EVENT_IDS + ["", "bad id"])
                two = rng.random() < 0.3
                register(contract, direct_vm, direct_vm.sender, event_id=eid,
                         urls=[U1, U2] if two else URLS, roles=ROLES[:2] if two else ROLES,
                         start=rng.choice([START, "2026-11-05T19:00:00"]))
            elif op == "resolve":
                world(direct_vm, WORLDS[rng.choice(sorted(WORLDS))]())
                optional(direct_vm)  # many random worlds legitimately use only part of what they declare
                contract.resolve_event(rng.choice(EVENT_IDS + ["missing"]), rng.choice(REQUEST_IDS + ["", "bad id"]))
            else:
                contract.get_resolution(rng.choice(REQUEST_IDS))
            stats["ok"] += 1
        except Exception:
            stats["reverted"] += 1
        check_invariants(contract, ledger, actors)
    assert stats["ok"] >= 15 and stats["reverted"] >= 10, stats
    final = [contract.get_resolution(r) for r in REQUEST_IDS]
    stored = [r for r in final if r["found"]]
    assert len(stored) >= 3, "the fuzz must actually store resolutions"
    assert len({r["final_status"] for r in stored}) >= 2, "and reach different outcomes"
    COVERAGE.update((r["final_status"], r["method"], r["fallback_used"]) for r in stored)


def test_the_fuzz_reached_a_broad_set_of_outcomes():
    """Runs after the fuzz (file order): a coverage floor, so a silently narrowed fuzz fails loudly."""
    finals = {c[0] for c in COVERAGE}
    assert len(finals) >= 4, sorted(COVERAGE)
    assert any(c[2] for c in COVERAGE) and any(c[1] == "PRIORITY_RULE" for c in COVERAGE), sorted(COVERAGE)
    print("FUZZ COVERAGE", sorted(COVERAGE))
