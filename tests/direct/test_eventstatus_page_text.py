"""EventStatus - deterministic page-text extraction and model-output normalization."""

import json
import time

import pytest

from tests.direct.eventstatus_support import (
    CONTRACT, ans, module, A_CANCELLED, Q_CANCELLED, Q_RESCHEDULED,
)

ORIGINAL = "2026-11-05T19:00:00Z"


@pytest.fixture
def mod(direct_vm, direct_deploy):
    direct_deploy(CONTRACT)  # loading the contract makes its module (pure functions) importable
    return module(direct_vm)


# --------------------------------------------------------------------------- #
# _page_text
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("<p>Hello   <b>brave</b>\n\tworld</p>", "Hello brave world"),
        ("a<!-- hidden: event cancelled -->b", "ab"),
        ("x<script>alert('cancelled')</script>y", "xy"),
        ("x<SCRIPT type=text/javascript>var s = '<p>';</SCRIPT >y", "xy"),
        ("x<style>.a{content:'cancelled'}</style>y", "xy"),
        ("5 &lt; 6 &amp; 7 &gt; 3 &eacute; &#233; &#x41;", "5 < 6 & 7 > 3 \u00e9 \u00e9 A"),
        ("a\u200bb\u200c\u200d\u2060\ufeffc", "abc"),
        ("if a < b then c", "if a < b then c"),            # '<' that does not open a tag stays text
        ("1 <2 and 3> 0", "1 <2 and 3> 0"),
        ("<!DOCTYPE html><html><body>ok</body></html>", "ok"),
        ('{"status": "cancelled", "date": "2026-11-05"}', '{"status": "cancelled", "date": "2026-11-05"}'),
        ("plain text only", "plain text only"),
        ("a<script>never closed", "a"),                     # an unterminated block removes the rest
        ("a<!-- never closed", "a"),
        ("text <unclosed tag with no end", "text <unclosed tag with no end"),
        ("<a href='x'>link</a><br/>more", "link more"),
        ("   \n\t  ", ""),
    ],
)
def test_page_text_extraction(mod, raw, expected):
    assert mod._page_text(raw) == expected


def test_comments_and_scripts_cannot_smuggle_text_into_the_evidence(mod):
    raw = "<p>Visible.</p><!-- the event is cancelled --><script>document.write('the event is cancelled')</script>"
    text = mod._page_text(raw)
    assert "cancelled" not in text and text == "Visible."
    assert not mod._quote_is_substantive("the event is cancelled", text)


@pytest.mark.parametrize(
    "name,raw",
    [
        ("many_lt", "<" * 140000),
        ("many_open_tags_no_close", "<a " * 46000),
        ("many_scripts_unclosed", "<script " * 17000),
        ("many_comments_unclosed", "<!--" * 35000),
        ("many_entities", "&amp;" * 28000),
        ("nested_tags", "<div>" * 28000),
        ("alternating", "< a" * 46000),
        ("closed_tags", "<b>x</b>" * 17000),
        ("amp_prefixes", "&#" * 70000),
    ],
)
def test_adversarial_inputs_run_in_linear_time(mod, name, raw):
    """No input within the response limit may trigger quadratic or catastrophic behavior."""
    started = time.time()
    mod._page_text(raw)
    assert time.time() - started < 3.0, name


# --------------------------------------------------------------------------- #
# Substantive quotes
# --------------------------------------------------------------------------- #


def test_substantive_quote_rules(mod):
    text = "The event is confirmed and going ahead as planned."
    assert mod._quote_is_substantive("going ahead as planned.", text)
    assert mod._quote_is_substantive(text, text)
    assert not mod._quote_is_substantive("", text)
    assert not mod._quote_is_substantive("event", text)               # literal but too short
    assert not mod._quote_is_substantive("is cancelled and over", text)  # not literal
    assert not mod._quote_is_substantive("x" * 241, "x" * 300)        # above the quote cap
    assert mod._quote_is_substantive("MIT", "MIT")                     # the whole short page
    assert not mod._quote_is_substantive("MIT", "MIT license")


# --------------------------------------------------------------------------- #
# Model-output parsing: strict schema, reject instead of coercing
# --------------------------------------------------------------------------- #


def test_valid_output_is_accepted_as_dict_or_text_or_fenced(mod, direct_vm):
    for raw in (A_CANCELLED, json.dumps(A_CANCELLED), "Sure:\n```json\n" + json.dumps(A_CANCELLED) + "\n```"):
        parsed = mod._parse_extraction(raw)
        assert parsed["status"] == "CANCELLED" and parsed["excerpt"] == Q_CANCELLED


BAD_OUTPUTS = {
    "not json": "I cannot help with that",
    "json array": "[]",
    "empty object": "{}",
    "missing key": {k: v for k, v in ans("NONE").items() if k != "excerpt"},
    "extra key": {**ans("NONE"), "confidence": 0.99},
    "extra source claim": {**ans("NONE"), "url": "https://evil.example.com/page"},
    "unknown identity": ans("NONE", identity="PROBABLY"),
    "lowercase identity": ans("NONE", identity="match"),
    "unknown status": ans("ON_HOLD"),
    "lowercase status": ans("cancelled", Q_CANCELLED),
    "status is a list": {**ans("NONE"), "status": ["CANCELLED"]},
    "date is a number": {**ans("RESCHEDULED", Q_RESCHEDULED), "reschedule_date": 20261212},
    "excerpt is a dict": {**ans("NONE"), "excerpt": {"text": "x"}},
    "excerpt is a number": {**ans("NONE"), "excerpt": 7},
}


@pytest.mark.parametrize("name", sorted(BAD_OUTPUTS))
def test_malformed_model_output_is_rejected(mod, name):
    with pytest.raises(Exception) as err:
        mod._parse_extraction(BAD_OUTPUTS[name])
    assert "[LLM_ERROR]" in str(err.value)


# --------------------------------------------------------------------------- #
# Normalization rules
# --------------------------------------------------------------------------- #

TEXT = ("Global DevCon 2026 has been cancelled. The event is confirmed and going ahead as planned. "
        "Global DevCon 2026 has been moved to 12 December 2026 at 18:00 CET (UTC+1).")


def norm(mod, answer, text=TEXT, start=ORIGINAL):
    return mod._normalize_extraction(answer, text, start)


def test_identity_gate(mod):
    for identity in ("MISMATCH", "UNCLEAR"):
        out = norm(mod, ans("CANCELLED", Q_CANCELLED, identity=identity))
        assert out["outcome"] == "IDENTITY_UNCONFIRMED" and out["claim"] == "" and out["excerpt"] == ""


def test_valid_claims(mod):
    out = norm(mod, ans("CANCELLED", Q_CANCELLED))
    assert (out["outcome"], out["claim"], out["reschedule_precision"]) == ("VALID_CLAIM", "CANCELLED", "NONE")
    out = norm(mod, ans("RESCHEDULED", Q_RESCHEDULED, date="2026-12-12", time="18:00", tz="+01:00"))
    assert (out["claim"], out["reschedule_precision"]) == ("RESCHEDULED", "FULL")
    assert (out["reschedule_date"], out["reschedule_time"], out["reschedule_tz"]) == ("2026-12-12", "18:00", "+01:00")


@pytest.mark.parametrize(
    "kwargs,precision",
    [(dict(date="2026-12-12", time="18:00", tz="Z"), "FULL"),
     (dict(date="2026-12-12", time="18:00"), "TZ_AMBIGUOUS"),
     (dict(date="2026-12-12"), "DATE_ONLY")],
)
def test_reschedule_precision_preserves_ambiguity_and_never_invents_a_timezone(mod, kwargs, precision):
    out = norm(mod, ans("RESCHEDULED", Q_RESCHEDULED, **kwargs))
    assert out["outcome"] == "VALID_CLAIM" and out["reschedule_precision"] == precision
    if precision != "FULL":
        assert out["reschedule_tz"] == ""  # nothing was converted to UTC or guessed


@pytest.mark.parametrize(
    "kwargs",
    [dict(date="2026-12-12", tz="+01:00"),                 # timezone without a time
     dict(),                                                # no date at all
     dict(date="2026-02-30", time="18:00", tz="Z"),         # impossible date
     dict(date="2026-13-01"), dict(date="12/12/2026"), dict(date="2026-12-12", time="25:00"),
     dict(date="2026-12-12", time="18:00", tz="+25:00"), dict(date="2026-12-12", time="18:00", tz="CET"),
     dict(date="1999-12-12"),                               # outside the supported range
     dict(date="2026-11-05")],                              # "rescheduled" to the original date
)
def test_invalid_or_hallucinated_schedules_make_the_claim_unusable(mod, kwargs):
    out = norm(mod, ans("RESCHEDULED", Q_RESCHEDULED, **kwargs))
    assert out["outcome"] == "AMBIGUOUS" and out["claim"] == "" and out["reschedule_date"] == ""


def test_rescheduling_to_a_different_time_on_the_original_day_is_a_move(mod):
    assert norm(mod, ans("RESCHEDULED", Q_RESCHEDULED, date="2026-11-05", time="21:00", tz="Z"))["outcome"] == "VALID_CLAIM"
    assert norm(mod, ans("RESCHEDULED", Q_RESCHEDULED, date="2026-11-05", time="19:00", tz="Z"))["outcome"] == "AMBIGUOUS"
    assert norm(mod, ans("RESCHEDULED", Q_RESCHEDULED, date="2026-11-05", time="19:00"))["outcome"] == "AMBIGUOUS"


@pytest.mark.parametrize("status", ["SCHEDULED", "POSTPONED", "CANCELLED", "COMPLETED"])
def test_non_reschedule_claims_cannot_carry_schedule_fields(mod, status):
    out = norm(mod, ans(status, Q_CANCELLED, date="2026-12-12"))
    assert out["outcome"] == "AMBIGUOUS" and out["claim"] == ""


@pytest.mark.parametrize(
    "quote",
    [None, "", "Event cancelled", "The event has been cancelled for good.", "cancelled", "x" * 50],
)
def test_a_claim_without_a_substantive_literal_quote_is_unusable(mod, quote):
    out = norm(mod, ans("CANCELLED", quote))
    assert out["outcome"] == "AMBIGUOUS" and out["claim"] == "" and out["excerpt"] == ""


def test_quote_matching_ignores_whitespace_differences_and_is_stored_normalized(mod):
    out = norm(mod, ans("CANCELLED", "Global   DevCon 2026\n has been    cancelled."))
    assert out["outcome"] == "VALID_CLAIM" and out["excerpt"] == Q_CANCELLED


def test_long_quotes_are_capped_at_the_limit(mod):
    text = ("Global DevCon 2026 has been cancelled. " * 12).strip()
    out = norm(mod, ans("CANCELLED", text), text=text)
    assert out["outcome"] == "VALID_CLAIM" and len(out["excerpt"]) <= 240 and out["excerpt"] in text


@pytest.mark.parametrize(
    "status,outcome",
    [("NONE", "NO_EXPLICIT_STATUS"), ("AMBIGUOUS", "AMBIGUOUS"), ("CONTRADICTORY", "CONTRADICTORY")],
)
def test_non_claim_statuses_map_to_outcomes_and_keep_only_real_quotes(mod, status, outcome):
    assert norm(mod, ans(status, None))["outcome"] == outcome
    assert norm(mod, ans(status, Q_CANCELLED))["excerpt"] == Q_CANCELLED
    assert norm(mod, ans(status, "an invented sentence that is nowhere"))["excerpt"] == ""
    assert norm(mod, ans(status, Q_CANCELLED))["claim"] == ""


# --------------------------------------------------------------------------- #
# Audit finding F1: the same instant written in another timezone is not a reschedule
# --------------------------------------------------------------------------- #


def test_epoch_arithmetic_matches_python_datetime_on_thousands_of_dates(mod):
    import datetime
    import random

    rng = random.Random(2026)
    offsets = ["Z", "+00:00", "-00:00", "+01:00", "-05:30", "+05:45", "+14:00", "-12:00", "+09:30", "-03:15"]
    for _ in range(4000):
        year = rng.randint(2000, 2100)
        month = rng.randint(1, 12)
        day = rng.randint(1, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
        hour, minute = rng.randint(0, 23), rng.randint(0, 59)
        tz = rng.choice(offsets)
        date, clock = f"{year:04d}-{month:02d}-{day:02d}", f"{hour:02d}:{minute:02d}"
        sign = -1 if tz.startswith("-") else 1
        delta = datetime.timedelta(0) if tz == "Z" else sign * datetime.timedelta(hours=int(tz[1:3]), minutes=int(tz[4:6]))
        expected = datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.timezone(delta)).timestamp() // 60
        assert mod._epoch_minutes(date, clock, tz) == expected, (date, clock, tz)


@pytest.mark.parametrize(
    "new,is_move",
    [(("2026-11-06", "02:00", "+07:00"), False),   # the same instant written in another zone
     (("2026-11-05", "20:00", "+01:00"), False),   # 19:00Z == 20:00+01:00
     (("2026-11-05", "14:00", "-05:00"), False),
     (("2026-11-05", "19:00", "Z"), False),
     (("2026-11-05", "19:00", "+00:00"), False),
     (("2026-11-05", "19:00", "+01:00"), True),    # one hour EARLIER than the registered instant
     (("2026-11-05", "19:01", "Z"), True),
     (("2026-11-05", "21:00", "Z"), True),
     (("2026-11-06", "19:00", "Z"), True),
     (("2026-11-05", "19:00", ""), False),         # same clock, zone not stated: nothing proves a change
     (("2026-11-05", "", ""), False),              # same day, no time stated
     (("2026-11-05", "20:00", ""), True),          # a different clock time is a change
     (("2026-12-12", "", ""), True),
     (("2026-12-12", "18:00", "+01:00"), True)],
)
def test_is_move_compares_instants_when_the_timezone_is_explicit(mod, new, is_move):
    assert mod._is_move(ORIGINAL, *new) is is_move


def test_same_instant_restated_in_local_time_is_not_a_reschedule_end_to_end(mod):
    same = ans("RESCHEDULED", Q_RESCHEDULED, date="2026-11-06", time="02:00", tz="+07:00")
    out = mod._normalize_extraction(same, TEXT, ORIGINAL)
    assert out["outcome"] == "AMBIGUOUS" and out["claim"] == ""
    moved = ans("RESCHEDULED", Q_RESCHEDULED, date="2026-11-06", time="03:00", tz="+07:00")
    assert mod._normalize_extraction(moved, TEXT, ORIGINAL)["outcome"] == "VALID_CLAIM"
    # an original registered in another zone behaves the same way
    assert mod._is_move("2026-11-05T20:00+01:00", "2026-11-05", "19:00", "Z") is False
    assert mod._is_move("2026-11-05T20:00+01:00", "2026-11-05", "20:00", "Z") is True
