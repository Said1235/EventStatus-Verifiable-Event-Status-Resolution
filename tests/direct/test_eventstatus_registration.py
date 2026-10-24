"""EventStatus - registration, immutability and public surface (direct mode)."""

import re

import pytest

from tests.direct.eventstatus_support import (
    CONTRACT, EVENT_ID, LOCATION, ORGANIZER, ROLES, START, TITLE, U1, U2, U3, URLS, VENUE,
    hex_of, new_event, register,
)


def reg(contract, vm, sender, **overrides):
    """Register with per-field overrides (for validation tests)."""
    args = dict(
        event_id=EVENT_ID, title=TITLE, organizer=ORGANIZER, venue=VENUE, location=LOCATION,
        scheduled_start=START, source_urls=URLS, source_roles=ROLES, supersedes="",
    )
    args.update(overrides)
    vm.sender = sender
    contract.register_event(**args)


def test_register_event_stores_exact_immutable_configuration(direct_vm, direct_deploy, direct_alice):
    contract = new_event(direct_vm, direct_deploy, direct_alice)
    e = contract.get_event(EVENT_ID)
    assert e["found"] is True
    assert (e["title"], e["organizer"], e["venue"], e["location"]) == (TITLE, ORGANIZER, VENUE, LOCATION)
    assert e["scheduled_start"] == START
    assert e["registrant"] == hex_of(direct_alice)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T.*Z", e["registered_at"])  # deterministic tx datetime
    assert e["policy_version"] == "PRIORITY_V1"
    assert e["supersedes"] == "" and e["resolution_count"] == 0
    assert e["sources"] == [
        {"source_id": "S1", "priority": 1, "url": U1, "role": "ORGANIZER"},
        {"source_id": "S2", "priority": 2, "url": U2, "role": "VENUE"},
        {"source_id": "S3", "priority": 3, "url": U3, "role": "TICKETING"},
    ]


def test_two_sources_are_enough(direct_vm, direct_deploy, direct_alice):
    contract = new_event(direct_vm, direct_deploy, direct_alice, urls=[U1, U2], roles=["ORGANIZER", "VENUE"])
    assert [s["source_id"] for s in contract.get_event(EVENT_ID)["sources"]] == ["S1", "S2"]


def test_registering_an_existing_event_id_fails_and_changes_nothing(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = new_event(direct_vm, direct_deploy, direct_alice)
    before = contract.get_event(EVENT_ID)
    for sender in (direct_alice, direct_bob):
        with direct_vm.expect_revert("event_id already registered"):
            reg(contract, direct_vm, sender, title="Other title", source_urls=[U3, U2], source_roles=["MEDIA", "OTHER"])
    assert contract.get_event(EVENT_ID) == before


@pytest.mark.parametrize(
    "event_id,message",
    [("", "event_id length"), ("x" * 65, "event_id length"), ("-lead", "start with"), ("_lead", "start with"),
     ("has space", "may only contain"), ("ev/ent", "may only contain"), ("ev\u00e9nt", "[EXPECTED]"),
     ("a;b", "may only contain"), ("   ", "event_id length")],
)
def test_invalid_event_ids(direct_vm, direct_deploy, direct_alice, event_id, message):
    contract = direct_deploy(CONTRACT)
    with direct_vm.expect_revert(message):
        reg(contract, direct_vm, direct_alice, event_id=event_id)


@pytest.mark.parametrize("event_id", ["a", "A1", "evt_1.2:3-4", "9" * 64])
def test_valid_event_ids(direct_vm, direct_deploy, direct_alice, event_id):
    contract = direct_deploy(CONTRACT)
    reg(contract, direct_vm, direct_alice, event_id=event_id)
    assert contract.get_event(event_id)["found"] is True


@pytest.mark.parametrize(
    "field,value,message",
    [("title", "", "must not be empty"), ("title", "   ", "must not be empty"), ("title", "T" * 121, "too long"),
     ("title", "bad\x00title", "control characters"), ("title", "two\nlines", "control characters"),
     ("organizer", "", "must not be empty"), ("venue", "V" * 121, "too long"), ("location", "L\x07", "control characters")],
)
def test_invalid_text_fields(direct_vm, direct_deploy, direct_alice, field, value, message):
    contract = direct_deploy(CONTRACT)
    with direct_vm.expect_revert(message):
        reg(contract, direct_vm, direct_alice, **{field: value})
    assert contract.get_event(EVENT_ID)["found"] is False


@pytest.mark.parametrize(
    "start",
    ["2026-11-05T19:00:00", "2026-11-05", "2026-11-05 19:00:00Z", "2026-13-05T19:00Z", "2026-02-30T19:00Z",
     "2026-11-05T24:00Z", "2026-11-05T19:60Z", "2026-11-05T19:00+15:00", "2026-11-05T19:00+0100",
     "1999-01-01T00:00Z", "2101-01-01T00:00Z", "tomorrow", "", "2026-11-05T19:00:61Z", "2023-02-29T10:00Z"],
)
def test_scheduled_start_needs_an_explicit_unambiguous_timezone(direct_vm, direct_deploy, direct_alice, start):
    contract = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("scheduled_start must be ISO-8601"):
        reg(contract, direct_vm, direct_alice, scheduled_start=start)


@pytest.mark.parametrize("start", ["2026-11-05T19:00Z", "2026-11-05T19:00:00Z", "2026-11-05T19:00:00+01:00", "2028-02-29T10:00-05:30"])
def test_valid_scheduled_starts_are_stored_verbatim(direct_vm, direct_deploy, direct_alice, start):
    contract = direct_deploy(CONTRACT)
    reg(contract, direct_vm, direct_alice, scheduled_start=start)
    assert contract.get_event(EVENT_ID)["scheduled_start"] == start


@pytest.mark.parametrize("count", [0, 1, 4, 5])
def test_source_count_is_bounded(direct_vm, direct_deploy, direct_alice, count):
    contract = direct_deploy(CONTRACT)
    urls = [f"https://source{i}.example.com/e" for i in range(count)]
    with direct_vm.expect_revert("sources are required"):
        reg(contract, direct_vm, direct_alice, source_urls=urls, source_roles=["OTHER"] * count)


def test_roles_must_match_sources_and_be_known(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("one role per source"):
        reg(contract, direct_vm, direct_alice, source_roles=["ORGANIZER", "VENUE"])
    with direct_vm.expect_revert("source role must be one of"):
        reg(contract, direct_vm, direct_alice, source_roles=["ORGANIZER", "VENUE", "OFFICIAL_TRUTH"])
    with direct_vm.expect_revert("source role must be one of"):
        reg(contract, direct_vm, direct_alice, source_roles=["ORGANIZER", "VENUE", ""])
    assert contract.get_event(EVENT_ID)["found"] is False


@pytest.mark.parametrize(
    "bad_url",
    ["http://organizer.example.com/x", "ftp://organizer.example.com/x", "organizer.example.com/x", "", "   ",
     "https://", "https://user:pw@organizer.example.com/x", "https://organizer.example.com/x#frag",
     "https://localhost/x", "https://127.0.0.1/x", "https://0x7f.0.0.1/x", "https://router.lan/x",
     "https://organizer.example.com:8443/x", "https://organizer.example.com./x", "https://foo.localhost/x",
     "https://organizer.example.com/" + "a" * 300, "https://exa mple.com/x"],
)
def test_invalid_source_urls_are_rejected(direct_vm, direct_deploy, direct_alice, bad_url):
    contract = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("[EXPECTED]"):
        reg(contract, direct_vm, direct_alice, source_urls=[U1, bad_url, U3])
    assert contract.get_event(EVENT_ID)["found"] is False


def test_duplicate_source_urls_are_rejected_even_with_different_case(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("duplicate source url"):
        reg(contract, direct_vm, direct_alice, source_urls=[U1, U2, U1])
    with direct_vm.expect_revert("duplicate source url"):
        reg(contract, direct_vm, direct_alice, source_urls=[U1, U1.upper().replace("HTTPS", "https")],
            source_roles=["ORGANIZER", "VENUE"])


def test_non_list_sources_are_rejected(direct_vm, direct_deploy, direct_alice):
    contract = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("[EXPECTED]"):
        reg(contract, direct_vm, direct_alice, source_urls=[U1, 7], source_roles=["ORGANIZER", "VENUE"])
    assert contract.get_event(EVENT_ID)["found"] is False


def test_correction_is_a_new_transparent_registration(direct_vm, direct_deploy, direct_alice, direct_bob):
    contract = new_event(direct_vm, direct_deploy, direct_alice)
    before = contract.get_event(EVENT_ID)
    # Only the original registrant can supersede; unknown targets are rejected.
    with direct_vm.expect_revert("only the original registrant"):
        reg(contract, direct_vm, direct_bob, event_id="evt-devcon-2026-v2", supersedes=EVENT_ID)
    with direct_vm.expect_revert("superseded event not found"):
        reg(contract, direct_vm, direct_alice, event_id="evt-devcon-2026-v2", supersedes="nope")
    reg(contract, direct_vm, direct_alice, event_id="evt-devcon-2026-v2", supersedes=EVENT_ID,
        source_urls=[U2, U1], source_roles=["VENUE", "ORGANIZER"])
    v2 = contract.get_event("evt-devcon-2026-v2")
    assert v2["supersedes"] == EVENT_ID
    assert [s["url"] for s in v2["sources"]] == [U2, U1]  # new policy, new identity
    assert contract.get_event(EVENT_ID) == before  # the old evidence policy is untouched


def test_absent_records_have_a_defined_result(direct_vm, direct_deploy):
    contract = direct_deploy(CONTRACT)
    assert contract.get_event("nope") == {"found": False, "event_id": "nope"}
    assert contract.get_resolution("nope") == {"found": False, "request_id": "nope"}
    assert contract.get_event_resolution_id("nope", 1) == ""


def test_public_surface_is_two_writes_three_views_and_nothing_payable(direct_vm, direct_deploy):
    """Reads the SDK markers the schema generator uses (not names or comments)."""
    contract = direct_deploy(CONTRACT)
    cls = type(contract._instance)
    members = {n: getattr(cls, n) for n in dir(cls) if callable(getattr(cls, n, None)) and not n.startswith("__")}
    public = {n for n, m in members.items() if getattr(m, "__gl_public__", False)}
    readonly = {n for n in public if getattr(members[n], "__gl_readonly__", False)}
    payable = {n for n in public if getattr(members[n], "__gl_payable__", False)}
    assert public - readonly == {"register_event", "resolve_event"}
    assert readonly == {"get_event", "get_resolution", "get_event_resolution_id"}
    assert payable == set(), "EventStatus has no monetary path; no method may be payable"
    # No entry point can edit the evidence policy or rewrite old results.
    assert not {n for n in public if re.search(r"update|edit|set_|change|delete|withdraw|transfer|pay|admin|owner", n)}
