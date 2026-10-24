# EventStatus - Official APIs and documentation used

Authority order: the **installed SDK source** and the **executed behavior** come first (the specification asks for exactly that), documentation second. Every API below was confirmed by reading the installed runner's SDK source and by calling it in direct mode and, for pure logic, inside GenVM's own CPython.

## APIs used

| API | Used for | Confirmed against |
|---|---|---|
| `class EventStatus(gl.Contract)`, `@gl.public.write`, `@gl.public.view` | contract and ABI | installed SDK; schema read through the SDK's `__gl_public__`/`__gl_readonly__`/`__gl_payable__` markers (2 write, 3 view, none payable) |
| `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)` | custom leader/validator consensus | SDK source (validator receives the leader's `Result`); equivalence-principle page |
| `gl.vm.Return` (`.calldata`), `gl.vm.UserError` (`.message`), `gl.vm.VMError` | result-type checks before reading a payload; deterministic errors | SDK source (`UserError.message` is compared for strict equality) |
| `gl.nondet.web.get(url)` -> `Response` (`.status`, `.body` bytes) | retrieval of the registered URLs | SDK source. Note: the documentation page shows `status_code`; the installed SDK exposes `status`, which is what the contract uses |
| `gl.nondet.exec_prompt(prompt, response_format="json")` | one extraction per source | SDK source |
| `gl.message.sender_address`, `gl.message_raw["datetime"]` | requester / registrant and the deterministic transaction time | SDK source; direct runner |
| `TreeMap`, `DynArray`, `@allow_storage` dataclasses, `u32`, `bool`, `Address`, `str` | persistent storage | SDK source; storage behavior exercised in direct mode and by calldata round-trips |
| `hashlib.sha256`, `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)` | canonical digests | not forbidden by the linter; identical output verified in GenVM's CPython (normal and deterministic builds) |
| `re`, `html.unescape`, `urllib.parse.urlparse` | page-text extraction and URL validation | not forbidden by the linter; identical output verified in GenVM's CPython |

## Documentation read

| Page | Read | Used for |
|---|---|---|
| Equivalence Principle - https://docs.genlayer.com/developers/intelligent-contracts/equivalence-principle | yes | custom leader/validator logic, validator errors count as disagreement |
| Error handling - .../features/error-handling | yes | `Return` / `UserError` / `VMError`, deterministic error classification |
| Web access - .../features/web-access | yes | retrieval patterns; the page recommends comparing stable derived fields rather than raw responses |
| Prompt injection - .../security-and-best-practices/prompt-injection | yes | restrict inputs (fixed prompts, frozen URLs), restrict outputs (strict enums), simple logic; human-in-the-loop is **not** implemented |
| Studio limitations - .../tools/genlayer-studio/limitations | yes | Studio web access has its own constraints; validate web reads on the target network |
| SDK reference - https://sdk.genlayer.com/main/_static/ai/api.txt | yes (earlier in the same working session) | two SDK generations; this contract targets the boilerplate generation |
| Boilerplate `CLAUDE.md` and project layout | yes (earlier in the same working session) | testing workflow, linter and `gltest` conventions |
| Persistent storage, transaction context, testing, Optimistic Democracy, "when to use GenLayer", linter page, `full-documentation.txt` | **not read page by page in this task** | the relevant behavior (storage types, `message_raw`, direct-mode testing, linter policy) was verified directly in the installed SDK, the direct runner and the linter, and by executed tests |

## Toolchain (pinned in `requirements.txt`)

`genlayer-test` 0.29.2 (`9c09578b...`), `genvm-linter` 0.11.1-rc.2 (`28450e66...`), `genlayer-py` 0.18.0 (`a3dc35e0...`); runner `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`.
