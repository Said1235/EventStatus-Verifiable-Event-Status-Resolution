"""EventStatus - exhaustive verification of the resolution policy.

``mod._resolve`` is checked against (1) an independently written oracle and (2) semantic
properties that hold regardless of how the policy is implemented, over EVERY combination of
per-source outcomes for two and three sources (11 states per source, 1,452 cases).
"""

import itertools

import pytest

from tests.direct.eventstatus_support import CONTRACT, module

SKIPPABLE = {"RETRIEVAL_FAILED", "IDENTITY_UNCONFIRMED", "NO_EXPLICIT_STATUS"}

# (label, outcome, claim, schedule)
STATES = [
    ("failed", "RETRIEVAL_FAILED", "", None),
    ("identity", "IDENTITY_UNCONFIRMED", "", None),
    ("nostatus", "NO_EXPLICIT_STATUS", "", None),
    ("ambiguous", "AMBIGUOUS", "", None),
    ("contradictory", "CONTRADICTORY", "", None),
    ("SCHEDULED", "VALID_CLAIM", "SCHEDULED", None),
    ("POSTPONED", "VALID_CLAIM", "POSTPONED", None),
    ("CANCELLED", "VALID_CLAIM", "CANCELLED", None),
    ("COMPLETED", "VALID_CLAIM", "COMPLETED", None),
    ("RESCHEDULED_A", "VALID_CLAIM", "RESCHEDULED", ("2026-12-12", "18:00", "+01:00")),
    ("RESCHEDULED_B", "VALID_CLAIM", "RESCHEDULED", ("2026-12-15", "18:00", "+01:00")),
]


def make(sources):
    findings = []
    for i, (_label, outcome, claim, schedule) in enumerate(sources):
        d, t, z = schedule or ("", "", "")
        findings.append({
            "source_id": f"S{i + 1}", "url": f"https://s{i + 1}.example.com/e",
            "retrieval": "UNAVAILABLE" if outcome == "RETRIEVAL_FAILED" else "OK",
            "http_status": 503 if outcome == "RETRIEVAL_FAILED" else 200,
            "outcome": outcome, "claim": claim,
            "reschedule_date": d, "reschedule_time": t, "reschedule_tz": z,
            "reschedule_precision": "FULL" if schedule else "NONE",
            "excerpt": "", "evidence_digest": "", "decision_role": "UNUSABLE",
        })
    return findings


def oracle(findings):
    """Independent statement of the policy, written from the specification text."""
    usable = [f["outcome"] == "VALID_CLAIM" for f in findings]
    # who decides? the first source that is neither failed, identity-unconfirmed nor status-less
    decider = next((i for i, f in enumerate(findings) if f["outcome"] not in SKIPPABLE), None)
    exp = {"final_status": None, "method": "NONE", "reason": "", "controlling_source": "", "fallback_used": False,
           "new_start_date": "", "new_start_time": "", "new_start_tz": "", "new_start_precision": "NONE"}
    n = len(findings)
    roles = ["UNUSABLE"] * n
    conflicts = []
    if decider is None:
        retrieved = [f for f in findings if f["retrieval"] == "OK"]
        if retrieved and all(f["outcome"] == "IDENTITY_UNCONFIRMED" for f in retrieved):
            exp["final_status"], exp["reason"] = "EVENT_IDENTITY_UNCONFIRMED", "IDENTITY_UNCONFIRMED_ALL_RETRIEVED"
        else:
            exp["final_status"], exp["reason"] = "INSUFFICIENT_EVIDENCE", "NO_USABLE_SOURCE"
    elif not usable[decider]:
        for i in range(decider):
            roles[i] = "SKIPPED"
        roles[decider] = "BLOCKING"
        for i in range(decider + 1, n):
            roles[i] = "BLOCKED" if usable[i] else "UNUSABLE"
        if findings[decider]["outcome"] == "CONTRADICTORY":
            exp["final_status"], exp["reason"] = "CONFLICTING_SOURCES", "CONTROLLING_SOURCE_CONTRADICTORY"
        else:
            exp["final_status"], exp["reason"] = "INSUFFICIENT_EVIDENCE", "CONTROLLING_SOURCE_AMBIGUOUS"
    else:
        top = findings[decider]
        for i in range(decider):
            roles[i] = "SKIPPED"
        roles[decider] = "CONTROLLING"
        disagreement = False
        for i in range(decider + 1, n):
            if not usable[i]:
                continue
            f = findings[i]
            same_claim = f["claim"] == top["claim"]
            same_schedule = (f["reschedule_date"], f["reschedule_time"], f["reschedule_tz"]) == (
                top["reschedule_date"], top["reschedule_time"], top["reschedule_tz"])
            if same_claim and (top["claim"] != "RESCHEDULED" or same_schedule):
                roles[i] = "SUPPORTING"
            else:
                roles[i] = "OVERRIDDEN"
                disagreement = True
                kind = "STATUS_MISMATCH" if not same_claim else "RESCHEDULE_MISMATCH"
                conflicts.append((i, {"kind": kind, "source_id": f["source_id"], "claim": f["claim"]}))
        exp.update(final_status=top["claim"], method="PRIORITY_RULE" if disagreement else "AGREEMENT",
                   controlling_source=top["source_id"], fallback_used=decider > 0)
        if top["claim"] == "RESCHEDULED":
            exp.update(new_start_date=top["reschedule_date"], new_start_time=top["reschedule_time"],
                       new_start_tz=top["reschedule_tz"], new_start_precision=top["reschedule_precision"])
    # internal contradictions are always preserved, one entry per source, in priority order
    entries = {i: c for i, c in conflicts}
    for i, f in enumerate(findings):
        if f["outcome"] == "CONTRADICTORY":
            entries[i] = {"kind": "INTERNAL_CONTRADICTION", "source_id": f["source_id"], "claim": ""}
    exp["roles"] = roles
    exp["conflicts"] = [entries[i] for i in sorted(entries)]
    return exp


COMBOS = [c for k in (2, 3) for c in itertools.product(STATES, repeat=k)]


@pytest.fixture(scope="module")
def mod_holder():
    return {}


@pytest.fixture
def mod(direct_vm, direct_deploy):
    direct_deploy(CONTRACT)
    return module(direct_vm)


def test_the_state_space_is_what_the_report_says(mod):
    assert len(STATES) == 11 and len(COMBOS) == 11 ** 2 + 11 ** 3 == 1452


def test_policy_matches_the_independent_oracle_on_every_combination(mod):
    mismatches = []
    for combo in COMBOS:
        findings = make(combo)
        got = mod._resolve(findings)
        want = oracle(findings)
        if got != want:
            mismatches.append(([c[0] for c in combo], got, want))
    assert not mismatches, f"{len(mismatches)} mismatches; first: {mismatches[0]}"


def test_semantic_properties_hold_on_every_combination(mod):
    for combo in COMBOS:
        labels = [c[0] for c in combo]
        findings = make(combo)
        out = mod._resolve(findings)
        final, roles, conflicts = out["final_status"], out["roles"], out["conflicts"]
        n = len(findings)
        valid = [f for f in findings if f["outcome"] == "VALID_CLAIM"]
        ctx = f"{labels} -> {final}"

        assert len(roles) == n
        assert final in ("SCHEDULED", "RESCHEDULED", "POSTPONED", "CANCELLED", "COMPLETED",
                         "CONFLICTING_SOURCES", "INSUFFICIENT_EVIDENCE", "EVENT_IDENTITY_UNCONFIRMED"), ctx
        # P1: a status is only ever reported when a valid, identity-confirmed claim says so
        if final in ("SCHEDULED", "RESCHEDULED", "POSTPONED", "CANCELLED", "COMPLETED"):
            assert any(f["claim"] == final for f in valid), ctx
            ctrl = [i for i, r in enumerate(roles) if r == "CONTROLLING"]
            assert len(ctrl) == 1 and findings[ctrl[0]]["claim"] == final, ctx
            assert out["controlling_source"] == findings[ctrl[0]]["source_id"], ctx
            # only skippable sources may stand above the controlling one (documented fallback)
            assert all(findings[i]["outcome"] in SKIPPABLE for i in range(ctrl[0])), ctx
            assert out["fallback_used"] == (ctrl[0] > 0), ctx
            assert out["method"] in ("AGREEMENT", "PRIORITY_RULE"), ctx
            assert out["reason"] == "", ctx
        else:
            # P2: an inconclusive outcome has no controlling source and a stated reason
            assert "CONTROLLING" not in roles and out["controlling_source"] == "" and out["method"] == "NONE", ctx
            assert out["reason"] != "" and out["fallback_used"] is False, ctx
            assert out["new_start_precision"] == "NONE", ctx
        # P3: priority wins - when the first deciding source is a valid claim, nothing below can change the status
        first = next((f for f in findings if f["outcome"] not in SKIPPABLE), None)
        if first is not None and first["outcome"] == "VALID_CLAIM":
            assert final == first["claim"], ctx
        # P4: no valid claim anywhere => a retrieval problem or missing statement never becomes a status
        if not valid:
            assert final in ("INSUFFICIENT_EVIDENCE", "CONFLICTING_SOURCES", "EVENT_IDENTITY_UNCONFIRMED"), ctx
        if all(c[0] in ("failed", "nostatus") for c in combo):
            assert final == "INSUFFICIENT_EVIDENCE", ctx
        # P5: every disagreeing valid lower-priority claim is preserved
        if "CONTROLLING" in roles:
            c0 = roles.index("CONTROLLING")
            for i in range(c0 + 1, n):
                f = findings[i]
                if f["outcome"] == "VALID_CLAIM" and (f["claim"] != final or (final == "RESCHEDULED" and (
                        f["reschedule_date"], f["reschedule_time"]) != (findings[c0]["reschedule_date"], findings[c0]["reschedule_time"]))):
                    assert roles[i] == "OVERRIDDEN" and any(c["source_id"] == f["source_id"] for c in conflicts), ctx
            assert (out["method"] == "PRIORITY_RULE") == ("OVERRIDDEN" in roles), ctx
        # P6: every internal contradiction is preserved exactly once, wherever it is
        for f in findings:
            if f["outcome"] == "CONTRADICTORY":
                assert sum(1 for c in conflicts if c["source_id"] == f["source_id"]) == 1, ctx
        assert len({c["source_id"] for c in conflicts}) == len(conflicts), ctx
        # P7: a reschedule date is exposed only for a RESCHEDULED decision and is the controlling one
        if final == "RESCHEDULED":
            src = findings[roles.index("CONTROLLING")]
            assert (out["new_start_date"], out["new_start_time"], out["new_start_tz"]) == (
                src["reschedule_date"], src["reschedule_time"], src["reschedule_tz"]), ctx
        else:
            assert (out["new_start_date"], out["new_start_time"], out["new_start_tz"]) == ("", "", ""), ctx
        # P8: a contradictory or ambiguous top source blocks the fallback entirely
        if first is not None and first["outcome"] in ("CONTRADICTORY", "AMBIGUOUS"):
            assert final in ("CONFLICTING_SOURCES", "INSUFFICIENT_EVIDENCE") and roles.count("BLOCKING") == 1, ctx


def test_policy_is_deterministic_and_ignores_evidence_wording(mod):
    for combo in COMBOS[:300]:
        a = make(combo)
        b = make(combo)
        for f in b:
            f["excerpt"] = "different wording of the same quote"
            f["evidence_digest"] = "ffff"
        assert mod._resolve(a) == mod._resolve(a) == mod._resolve(b)


def test_skippable_outcomes_are_interchangeable_when_a_valid_source_decides(mod):
    """A retrieval failure, a wrong-identity page and a status-less page above a decider are
    all just 'skipped': swapping one for another cannot change the decision."""
    tail = [s for s in STATES if s[1] == "VALID_CLAIM"]
    skips = [s for s in STATES if s[1] in SKIPPABLE]
    for top in skips:
        for other in skips:
            for t in tail:
                a = mod._resolve(make([top, t]))
                b = mod._resolve(make([other, t]))
                assert a["final_status"] == b["final_status"] and a["controlling_source"] == b["controlling_source"]
                assert a["new_start_date"] == b["new_start_date"] and a["fallback_used"] is True
