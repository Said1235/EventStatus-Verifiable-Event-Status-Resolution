"""Map the 43 adversarial scenarios of the specification (A1-E43) to the tests that attack them.

    pytest tests/direct -p no:cacheprovider -v | grep -E " (PASSED|FAILED|ERROR)" > pytest-verbose.txt
    python tools/scenario_matrix.py pytest-verbose.txt

The table is computed from a REAL verbose run; a scenario with no matching test aborts the script.
"""
import re
import sys

res = {}
for line in open(sys.argv[1]).read().splitlines():
    m = re.match(r"^(.+?) (PASSED|FAILED|ERROR)\b", line)
    if m:
        res[m.group(1)] = m.group(2)

S = [
    ("A1", "All sources confirm the same scheduled event", ["A1_A2_A3_A5_all_sources_agree[SCHEDULED"]),
    ("A2", "All sources confirm cancellation", ["A1_A2_A3_A5_all_sources_agree[CANCELLED"]),
    ("A3", "All sources confirm postponement", ["A1_A2_A3_A5_all_sources_agree[POSTPONED"]),
    ("A4", "A source announces a new date and time", ["test_A4_"]),
    ("A5", "All sources confirm completion", ["A1_A2_A3_A5_all_sources_agree[COMPLETED"]),
    ("A6", "Primary and secondary disagree; the rule resolves it and both claims are kept", ["test_A6_"]),
    ("A7", "Highest-priority source unavailable; fallback used and recorded", ["test_A7_"]),
    ("B8", "A source is inaccessible", ["test_B8_B18", "test_A7_unavailable"]),
    ("B9", "An HTTP error occurs", ["test_B9_"]),
    ("B10", "A source contains no explicit status claim", ["test_B10_"]),
    ("B11", "An old page still shows the original date", ["test_B11_"]),
    ("B12", "A cancellation about a similarly named different event", ["test_B12_"]),
    ("B13", "Same name at a different venue / tour", ["test_B13_"]),
    ("B14", "New date visible but timezone ambiguous", ["test_B14_", "reschedule_precision_preserves"]),
    ("B15", "One source with a past announcement and a later correction", ["test_B15_"]),
    ("B16", "Valid sources contradict and no defensible controlling claim exists", ["test_B16_"]),
    ("B17", "Source says cancelled but the excerpt does not support it", ["test_B17_"]),
    ("B18", "No source gives sufficient evidence: never a false SCHEDULED", ["test_B8_B18", "B9_http_errors"]),
    ("C19", "Prompt injection in page content", ["test_C19_"]),
    ("C20", "Misleading, hidden or conflicting page text", ["test_C20_", "comments_and_scripts_cannot"]),
    ("C21", "Malformed JSON, missing fields, bad enums, extra claims", ["test_C21_", "malformed_model_output_is_rejected", "malformed_model_output_makes_the_validator"]),
    ("C22", "Evidence excerpt that cannot be found in the source", ["test_B17_C22", "test_D30_a_quote"]),
    ("C23", "Hallucinated date, timezone or URL", ["test_C23_", "invalid_or_hallucinated_schedules"]),
    ("C24", "Page exceeds a runtime content constraint", ["test_C24_"]),
    ("D25", "Leader CANCELLED, validator derives SCHEDULED", ["test_D25_"]),
    ("D26", "Same final status, different material source finding", ["test_D26_", "same_page_different_judgement"]),
    ("D27", "Same final status, different controlling source", ["test_D27_"]),
    ("D28", "Same final status, different rescheduled date/time", ["test_D28_"]),
    ("D29", "Same final status, different view on whether a conflict exists", ["test_D29_"]),
    ("D30", "Leader invents a source claim validators cannot substantiate", ["test_D30_", "consistent_forgeries"]),
    ("D31", "Valid enum and shape but evidence contradicts the decision", ["test_D31_"]),
    ("D32", "Validator receives a failed leader result", ["test_D32_"]),
    ("D33", "Temporary retrieval failure is not a positive finding", ["test_D33_"]),
    ("D34", "Source changes between leader and validator retrieval", ["test_D34_"]),
    ("D35", "Plausible but different validator result does not pass on status alone", ["test_D35_", "differential_fuzz_validator", "different_kind_must_not_agree"]),
    ("E36", "Registering an existing event id fails", ["test_registering_an_existing_event_id"]),
    ("E37", "Invalid or duplicate source URLs are rejected", ["test_invalid_source_urls", "test_duplicate_source_urls", "test_source_count_is_bounded"]),
    ("E38", "Reusing a request id fails without overwriting", ["test_E38_"]),
    ("E39", "Two request ids for one event give distinct records", ["test_E39_"]),
    ("E40", "Multiple callers never receive each other's results", ["test_E40_E42_"]),
    ("E41", "Concurrent or reordered evaluations cannot mix findings", ["test_E41_", "E38_two_leaders_racing"]),
    ("E42", "Lookup by request id returns the matching result, not the wallet's newest", ["test_E40_E42_"]),
    ("E43", "State survives later calls and stays serializable", ["test_E43_", "stateful_fuzz"]),
]
print("| # | Scenario | Tests | Passed | Failed | Result |\n|---|---|---|---|---|---|")
bad = 0
for key, title, frags in S:
    ids = [i for i in res if any(f in i for f in frags)]
    assert ids, f"scenario {key} has no matching test"
    passed = sum(res[i] == "PASSED" for i in ids)
    failed = len(ids) - passed
    bad += failed
    print(f"| {key} | {title} | {len(ids)} | {passed} | {failed} | {'PASS' if failed == 0 else 'FAIL'} |")
print(f"\nTotal tests in run: {len(res)}; passed: {sum(v == 'PASSED' for v in res.values())}; not passed: {sum(v != 'PASSED' for v in res.values())}")
sys.exit(1 if bad else 0)
