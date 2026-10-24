"""Mutation check: weaken contracts/eventstatus.py in ~50 ways; the test suite must fail each time.

    python tools/mutation_check.py              # all mutants
    python tools/mutation_check.py N03 P07      # only the named ones

Mutants are written to a temporary directory (the file stem must stay "eventstatus") and loaded
through the EVENTSTATUS_CONTRACT environment variable; the real contract is never modified.
A mutant that SURVIVES is either a real gap in the tests or an equivalent mutant (a redundant
guard). Known equivalents are listed in EQUIVALENT with the reason.
"""

import os
import subprocess
import sys
import tempfile

SRC = "contracts/eventstatus.py"
MUTANT = os.path.join(tempfile.mkdtemp(prefix="eventstatus_mut_"), "eventstatus.py")
orig = open(SRC, encoding="utf-8").read()


def sub(old, new):
    assert orig.count(old) == 1, (orig.count(old), old[:80])
    return orig.replace(old, new)


# id -> (description, mutated source)
M = {
    # ---- consensus: validator and structural checks -----------------------------------------
    "V01": ("validator skips the structural/derivation check", sub('                if not _check_core(core, ctx):\n                    return False\n', '')),
    "V02": ("validator never compares material findings", sub('''                for theirs, mine in zip(core["findings"], own):
                    for key in MATERIAL_KEYS:
                        if theirs[key] != mine[key]:
                            return False
''', '                pass\n')),
    "V03": ("validator ignores the status claim", sub('                    for key in MATERIAL_KEYS:\n', '                    for key in tuple(k for k in MATERIAL_KEYS if k != "claim"):\n')),
    "V04": ("validator ignores the per-source outcome", sub('                    for key in MATERIAL_KEYS:\n', '                    for key in tuple(k for k in MATERIAL_KEYS if k != "outcome"):\n')),
    "V05": ("validator ignores retrieval class and HTTP status", sub('                    for key in MATERIAL_KEYS:\n', '                    for key in tuple(k for k in MATERIAL_KEYS if k not in ("retrieval", "http_status")):\n')),
    "V06": ("validator ignores reschedule date/time/timezone", sub('                    for key in MATERIAL_KEYS:\n', '                    for key in tuple(k for k in MATERIAL_KEYS if not k.startswith("reschedule")):\n')),
    "V07": ("validator does not verify quotes against its own page", sub('''                for theirs, text in zip(core["findings"], own_texts):
                    if theirs["excerpt"] != "" and not _quote_is_substantive(theirs["excerpt"], text):
                        return False
''', '')),
    "V08": ("validator always accepts", sub('            try:\n                core = leader_result.calldata\n', '            return True\n            try:\n                core = leader_result.calldata\n')),
    "V09": ("_check_core does not re-derive the result", sub('    return core == expected\n', '    return True\n')),
    "V10": ("_check_core does not bind event/request id", sub('    if core["event_id"] != ctx["event_id"] or core["request_id"] != ctx["request_id"]:\n        return False\n', '')),
    "V11": ("_check_core does not require one finding per source", sub('    if not isinstance(findings, list) or len(findings) != len(sources):\n        return False\n', '    if not isinstance(findings, list):\n        return False\n')),
    "V12": ("finding is not bound to the registered source id/url", sub('    if f["source_id"] != source["id"] or f["url"] != source["url"]:\n        return False\n', '')),
    "V13": ("post-consensus structural guard removed", sub('        if not _check_core(verdict, ctx):\n            _fail(ERR_EXPECTED, "consensus result failed structural verification")\n', '')),
    "V14": ("leader errors are trusted", sub('        return e.message.startswith(ERR_EXPECTED) and e.message == leader_message\n', '        return True\n')),
    "V15": ("policy version not bound", sub('    if core["policy_version"] != POLICY_VERSION or core["policy_version"] != ctx["policy_version"]:\n        return False\n', '')),
    "V16": ("retrieval class / status code consistency not checked", sub('        if ret == RET_UNAVAILABLE and not (status == 0 or status in (408, 429) or status >= 500):\n            return False\n', '')),
    "V17": ("a valid claim may have an empty quote", sub('        if f["claim"] not in CLAIMS or len(f["excerpt"]) < 1:\n            return False\n', '        if f["claim"] not in CLAIMS:\n            return False\n')),
    # ---- model-output normalization -----------------------------------------------------------
    "N01": ("claims need no quote", sub('    if not quote_ok:\n        return res\n', '')),
    "N02": ("quotes may be 1 character", sub('MIN_EXCERPT_LEN = 12\n', 'MIN_EXCERPT_LEN = 1\n')),
    "N03": ("identity gate removed", sub('    if parsed["identity"] != "MATCH":\n        return res\n', '')),
    "N04": ("a 'reschedule' to the original date is accepted", sub('        if not _reschedule_fields_ok(date, clock, tz) or not _is_move(scheduled_start, date, clock, tz):\n            return res\n', '        if not _reschedule_fields_ok(date, clock, tz):\n            return res\n')),
    "N05": ("impossible dates are accepted", sub('    if not _valid_date(date):\n        return False\n', '')),
    "N06": ("a missing timezone is invented", sub('    res["reschedule_date"], res["reschedule_time"], res["reschedule_tz"] = date, clock, tz\n', '    res["reschedule_date"], res["reschedule_time"], res["reschedule_tz"] = date, clock, tz or ("Z" if clock else "")\n')),
    "N07": ("non-reschedule claims may carry schedule fields", sub('    elif date != "" or clock != "" or tz != "":\n        return res\n', '')),
    "N08": ("unsupported model fields are tolerated", sub('    if set(parsed.keys()) != set(RAW_EXTRACTION_KEYS):\n        _fail(ERR_LLM, "model output has missing or unsupported fields")\n', '')),
    "N10": ("the same instant in another timezone counts as a reschedule", sub('    if clock != "" and tz != "":\n        return _epoch_minutes(date, clock, tz) != _epoch_minutes(o_date, o_clock, o_tz)\n', '')),
    "N11": ("UTC offset sign inverted", sub('        offset = (1 if tz[0] == "+" else -1) * (int(tz[1:3]) * 60 + int(tz[4:6]))\n', '        offset = (-1 if tz[0] == "+" else 1) * (int(tz[1:3]) * 60 + int(tz[4:6]))\n')),
    "N12": ("leap-year/century handling of the calendar arithmetic broken", sub('    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy\n', '    doe = yoe * 365 + yoe // 4 + doy\n')),
    "N09": ("a timezone without a time is accepted", sub('    if tz != "" and (clock == "" or not _valid_tz(tz)):\n        return False\n', '    if tz != "" and not _valid_tz(tz):\n        return False\n')),
    # ---- retrieval and page text ---------------------------------------------------------------
    "R01": ("5xx/408/429 are reported as definitive HTTP errors", sub('        if status == 408 or status == 429 or status >= 500:\n            return RET_UNAVAILABLE, status, ""\n        return RET_HTTP_ERROR, status, ""\n', '        return RET_HTTP_ERROR, status, ""\n')),
    "R02": ("long pages are silently truncated", sub('    if len(text) > MAX_TEXT_CHARS:\n        return RET_TOO_LARGE, status, ""\n    return RET_OK, status, text\n', '    return RET_OK, status, text[:MAX_TEXT_CHARS]\n')),
    "R03": ("<script> content is kept as evidence", sub('    text = _remove_blocks(text, _SCRIPT_START, _SCRIPT_END)\n', '')),
    "R04": ("HTML comments are kept as evidence", sub('    text = _remove_blocks(raw, _COMMENT_START, _COMMENT_END)\n', '    text = raw\n')),
    "R05": ("response size limit off by one", sub('MAX_RESPONSE_BYTES = 150000\n', 'MAX_RESPONSE_BYTES = 150001\n')),
    "R06": ("response size limit not enforced", sub('    if len(body) > MAX_RESPONSE_BYTES:\n        return RET_TOO_LARGE, status, ""\n', '')),
    "R07": ("zero-width characters are kept", sub('    for ch in ZERO_WIDTH:\n        text = text.replace(ch, "")\n', '')),
    "R08": ("HTML entities are not decoded", sub('    text = html.unescape(text)\n', '')),
    "R09": ("a non-200 answer is read as a page", sub('    if status != 200:\n        if status == 408', '    if status >= 400:\n        if status == 408')),
    # ---- resolution policy -------------------------------------------------------------------
    "P01": ("fallback allowed past an AMBIGUOUS source", sub('SKIPPABLE = (OUT_RETRIEVAL_FAILED, OUT_IDENTITY_UNCONFIRMED, OUT_NO_EXPLICIT_STATUS)\n', 'SKIPPABLE = (OUT_RETRIEVAL_FAILED, OUT_IDENTITY_UNCONFIRMED, OUT_NO_EXPLICIT_STATUS, OUT_AMBIGUOUS)\n')),
    "P02": ("fallback allowed past a CONTRADICTORY source", sub('SKIPPABLE = (OUT_RETRIEVAL_FAILED, OUT_IDENTITY_UNCONFIRMED, OUT_NO_EXPLICIT_STATUS)\n', 'SKIPPABLE = (OUT_RETRIEVAL_FAILED, OUT_IDENTITY_UNCONFIRMED, OUT_NO_EXPLICIT_STATUS, OUT_CONTRADICTORY)\n')),
    "P03": ("the LOWEST priority source decides", sub('    for i in range(n):\n        if findings[i]["outcome"] not in SKIPPABLE:\n', '    for i in range(n - 1, -1, -1):\n        if findings[i]["outcome"] not in SKIPPABLE:\n')),
    "P04": ("disagreement is not reported as PRIORITY_RULE", sub('        out["method"] = METHOD_PRIORITY_RULE if overridden else METHOD_AGREEMENT\n', '        out["method"] = METHOD_AGREEMENT\n')),
    "P05": ("status disagreements are not preserved", sub('                conflicts.append({"kind": CONFLICT_STATUS, "source_id": f["source_id"], "claim": f["claim"]})\n', '                pass\n')),
    "P06": ("internal contradictions are not preserved", sub('        if f["outcome"] == OUT_CONTRADICTORY and f["source_id"] not in by_source:\n', '        if False:\n')),
    "P07": ("ANY identity failure means EVENT_IDENTITY_UNCONFIRMED", sub('all(f["outcome"] == OUT_IDENTITY_UNCONFIRMED for f in retrieved)', 'any(f["outcome"] == OUT_IDENTITY_UNCONFIRMED for f in retrieved)')),
    "P08": ("no usable source defaults to SCHEDULED", sub('            out["final_status"] = "INSUFFICIENT_EVIDENCE"\n            out["reason"] = REASON_NO_USABLE\n', '            out["final_status"] = "SCHEDULED"\n            out["reason"] = REASON_NO_USABLE\n')),
    "P09": ("fallback is not reported", sub('        out["fallback_used"] = first > 0\n', '        out["fallback_used"] = False\n')),
    "P10": ("the new schedule is not exposed", sub('        if ctrl["claim"] == "RESCHEDULED":\n            out["new_start_date"] = ctrl["reschedule_date"]\n', '        if False:\n            out["new_start_date"] = ctrl["reschedule_date"]\n')),
    "P11": ("reschedule disagreements are treated as agreement", sub('            elif f["claim"] == "RESCHEDULED" and not _same_schedule(f, ctrl):\n', '            elif False:\n')),
    "P12": ("AMBIGUOUS and CONTRADICTORY blocking results swapped", sub('        if blocking["outcome"] == OUT_CONTRADICTORY:\n', '        if blocking["outcome"] == OUT_AMBIGUOUS:\n')),
    # ---- registration and storage ------------------------------------------------------------
    "S01": ("request ids can be reused", sub('        if clean_request in self.resolutions:\n            _fail(ERR_EXPECTED, "request_id already used")\n', '')),
    "S02": ("event ids can be re-registered", sub('        if clean_id in self.events:\n            _fail(ERR_EXPECTED, "event_id already registered")\n', '')),
    "S03": ("the per-event resolution index is not maintained", sub('        event.resolution_ids.append(clean_request)\n', '')),
    "S04": ("anyone can supersede an event", sub('            if self.events[clean_supersedes].registrant != gl.message.sender_address:\n                _fail(ERR_EXPECTED, "only the original registrant can supersede an event")\n', '')),
    "S05": ("source count not bounded", sub('        if len(source_urls) < MIN_SOURCES or len(source_urls) > MAX_SOURCES:\n', '        if False:\n')),
    "S06": ("duplicate source urls accepted", sub('            if url.lower() in [u.lower() for u in clean_urls]:\n                _fail(ERR_EXPECTED, "duplicate source url")\n', '')),
    "S07": ("results are keyed by event id (overwrites)", sub('        res = self.resolutions.get_or_insert_default(clean_request)\n', '        res = self.resolutions.get_or_insert_default(clean_event)\n')),
    "S08": ("scheduled_start format not validated", sub('    if _split_start(text) is None:\n        _fail(\n', '    if False:\n        _fail(\n')),
    "S09": ("requester recorded wrongly", sub('        res.requester = gl.message.sender_address\n', '        res.requester = event.registrant\n')),
    "S10": ("conflicts are not stored", sub('        for c in verdict["conflicts"]:\n            res.conflicts.append(Conflict(kind=c["kind"], source_id=c["source_id"], claim=c["claim"]))\n', '')),
    "S11": ("source roles not validated", sub('            if not isinstance(raw_role, str) or raw_role.strip() not in SOURCE_ROLES:\n', '            if False:\n')),
    "S12": ("registration timestamp not recorded", sub('        event.registered_at = gl.message_raw["datetime"]\n', '')),
    "S13": ("request id not validated", sub('        clean_request = _clean_identifier(request_id, "request_id")\n', '        clean_request = request_id\n')),
}

# Redundant guards: removing them cannot change behavior because another check already covers it.
EQUIVALENT = {
    "V10": "the final `core == expected` already includes event_id and request_id (built from ctx)",
    "V15": "the final `core == expected` already includes policy_version (built from ctx)",
}

if __name__ == "__main__":
    wanted = sys.argv[1:] or list(M)
    survivors = []
    for key in wanted:
        desc, src = M[key]
        open(MUTANT, "w", encoding="utf-8").write(src)
        r = subprocess.run(
            ["pytest", "tests/direct", "-q", "-x", "-p", "no:cacheprovider"],
            capture_output=True, text=True, env={**os.environ, "EVENTSTATUS_CONTRACT": MUTANT},
        )
        failed = [line for line in r.stdout.splitlines() if line.startswith(("FAILED", "ERROR"))][:1]
        killed = r.returncode != 0
        print(("KILLED  " if killed else "SURVIVED"), key, desc, "->", (failed[0].split("::", 1)[-1][:70] if failed else ""), flush=True)
        if not killed:
            survivors.append(key)
    unexplained = [k for k in survivors if k not in EQUIVALENT]
    print("\nmutants:", len(wanted), "survivors:", survivors, "| unexplained:", unexplained)
    sys.exit(1 if unexplained else 0)
