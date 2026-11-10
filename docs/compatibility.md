# Compatibility spike — HA 2026.11.1

## Result

The current interim policy uses **Home Assistant 2026.11.1's strict intent handler with a pre-execution filter**, then an existing conversation entity. It retains supported state queries and failure-aware handoff without modifying or monkey-patching core. The integration domain is `local_first_conversation`.

The original full-agent delegation spike established that released HA includes gazetteer, but a subsequent synthetic audit reproduced unsafe successful interpretations: “turn on the kitchen lights at 9 pm,” “do not turn on the kitchen lights,” and “can you explain how to turn on the kitchen lights” could execute immediately. The normal prefer-local shortcut handed these requests to the destination instead. The full agent also answered “who is the founder of Home Assistant” as a person-location query. Errors-only fallback cannot detect those false successes.

The interim policy therefore disables gazetteer. This is not a general semantic-safety guarantee or a supported public release. The setup floor is conservatively 2026.11.1, the tested release; older and future releases need separate verification.

## Pre-execution acceptance policy

The router calls exported `conversation.async_prepare_intents` and `conversation.async_handle_intents`, using the latter's `intent_filter`. It does not invoke the full built-in agent, import gazetteer internals, copy a recognizer, or add a classifier. HA's strict matcher resolves exact exposed names and supported sentence structures.

- Finite state vocabularies in HA's grammar remain valid even when no target currently has the requested state. A negative boolean answer is successful local handling.
- Wildcard `HassGetState` slots are rejected, except a person `state` equal to `home`, `not_home`, or a configured non-home zone's canonical name. The home zone's display name is not its person state. Validation is case-sensitive to match HA's state comparison; the router does not mutate cached recognition results to normalize guessed locations. Differently spelled locations go to fallback.
- Configured zone changes are checked on every request, even if HA caches the recognition result. Observed person locations are not an allowlist: an empty configured zone remains a valid query, but a removed zone no longer qualifies.
- A `conversation_command` slot is rejected before execution. HA's timer handler otherwise stores a command that can later re-enter the unguarded full agent. All delayed conversation commands go to fallback; ordinary timer intents retain HA's normal device requirements. This policy does not cancel existing timers.
- Misspelled names, gazetteer pronouns, and unsupported qualified or compound requests go to fallback without speculative gazetteer execution. Explicit user-configured sentence triggers remain enabled and trusted; custom intent handlers are not sandboxed.

This intentionally gives up local name correction and local delayed commands. Restoring them requires safer recognition and a supported validation boundary before full-agent execution, not post-response inspection.

## Pinned environment and evidence boundary

- Current policy tests: `homeassistant==2026.11.1`, Python 3.14.7, Linux x86_64. The original delegation spike used Python 3.14.2.
- Released core source: [2026.11.1](https://github.com/home-assistant/core/tree/2026.11.1), commit [`d8a0dc6`](https://github.com/home-assistant/core/commit/d8a0dc698c8946b44e455d904000db563cfbf1ba). The installed `default_agent.py` was byte-compared with that tag.
- Recognition dependencies: `gazetteer-matcher==1.1.0`, `hassil==3.12.1`, `home-assistant-intents==2026.10.27`.
- Tests create a temporary HA configuration, real registries, and synthetic lights, blinds, people, zones, a door, and a registered satellite. Service handlers change only in-memory states; unavailable-device failures are simulated service exceptions. The fallback is a synthetic conversation entity using real HA prompt preparation and chat-log streaming, not a model. Gazetteer is installed as an HA dependency but is not used by the router.
- `pytest-socket` permits only loopback connections. HA's source-address discovery probes to multicast and an external IP are blocked and produce warnings. HA/aiohttp/backoff also emit upstream warnings. No live household, model API, or provider credentials are accessed.

## Verified contracts

The retained suite, `tests/test_compatibility.py`, passes **23 tests** through the released HA stack. Before changing the implementation, the first ten safety cases produced **9 failures / 1 pass**, confirming that they detect the old behavior rather than merely exercising input rejection.

| Boundary | Decisive observation |
| --- | --- |
| Rejected requests | Clock-time, negated, explanatory, conditional, misspelled, and delayed requests reach fallback with the unchanged original text; no synthetic service calls or timers occur. |
| Strict commands and state queries | Exact commands change the intended light state. Queries return `query_answer` for open, closed, unavailable, and unknown states; a light's negative on/off answer stays local. |
| Validated person and door queries | “Who is home?” and “Where is Alice?” answer locally. The founder/creator questions and an unknown location fall back. Configured empty and occupied zones answer correctly; removing the zone causes the cached utterance to fall back. An open door answers both open and closed queries correctly. |
| No match → LLM | “write a poem about my kitchen lights” reaches the synthetic destination with the original text and `not_handled` context in its real HA-prepared prompt. |
| Partial target failure | A real HA intent handler returns `action_done` with a successful ceiling light and failed strip light. The router hands off both lists despite the absence of a top-level error. |
| Unavailable command | An exact blinds command fails through the real handler; available `failed_to_handle` response and tool outcome reach fallback. |
| Nested sessions and history | No busy-session error. The outer chat log has one user message and one final assistant answer on fallback, not a local failure answer plus a duplicate user message. |
| Multi-turn | An exact local command, LLM turn, pronoun handoff, and later exact local command share the outer conversation without guessing a local pronoun target. A later handoff excludes prior-turn execution outcomes. |
| Device/satellite | “turn on the lights in here” uses a registered kitchen satellite's area. Fallback retains the original context object and device/satellite IDs. |
| Permissions | Another user cannot reuse the session; an exact unexposed target does not execute locally. No extra LLM API or tools are registered. |
| Assist pipeline | The actual intent-stage pipeline with prefer-local disabled executes a registered sentence trigger once. Fallback emits `intent-progress` deltas “Fallback ” and “answer”, no local refusal text, and returns continuation=true. |
| Shortcut comparison | With a control-capable synthetic agent and prefer-local enabled, a misspelled command and a state question reach that destination. Our router keeps the supported exact state question local. |
| Failure/lifecycle | A missing fallback, provider exception, and injected fallback timeout return errors without retry. Self-selection is rejected; an options change reloads the router and uses a buffered destination. Local timeout is marked uncertain while a synthetic service is in flight; caller cancellation propagates without invoking fallback. |

Run from a fresh environment using the commands in the [README](../README.md). The test harness does not depend on HA's separately versioned third-party pytest fixture package.

## Routing in Assist debug output

The router returns a `ConversationResult` subclass whose `as_dict()` preserves HA's response, conversation ID, and continuation flag and adds `local_first`. HA 2026.11.1 carries that field into `intent-end.data.intent_output`, retained pipeline debug runs, and downloaded debug JSON. It is result metadata, not assistant text, a fabricated tool call, or an addition to the model prompt. No HA pipeline or frontend code is patched.

`route: local` identifies `conversation.home_assistant`, the owner of the strict handler. `route: fallback` identifies the configured fallback entity. `local_outcome` is `not_handled` when strict handling returned no accepted response, `reported_failure` for a returned error or failed targets, or `uncertain` for an exception/timeout. Response type, error code, and failed-target count are included only when a local response exists. The selected destination is named even if it is unavailable or fails; a fallback route alone is not evidence of successful inference. Counts are not physical-completion evidence.

The real Assist test checks strict local commands and state answers, unsafe-request handoff without service calls, no-match streaming, and an `action_done` partial failure with one failed target. Timeout and provider-error tests also check metadata. HA's own `processed_locally` stays false when it delegates to this router, including on router-local answers; that core-owned flag describes the pipeline shortcut.

Before the strict-policy update, the unmodified frontend **20261028.5** shipped with HA 2026.11.1 was exercised through its text debug runner: the bottom **full-run Raw panel** rendered `intent.intent_output.local_first`, and downloaded JSON contained it. The smaller NLP Raw panel was blank because its `readOnly autoUpdate` attributes did not match the YAML editor's `read-only auto-update` attributes. The strict-policy change does not alter that frontend or metadata location; existing screenshots show the earlier fallback error fields, not the new `not_handled` outcome. Current pipeline tests verify the updated retained event payloads.

Old runs cannot gain metadata retroactively. Pipeline sentence triggers and other paths that bypass the router do not produce it. Normal HA debug retention applies; the extension adds no new transcript store. An exported `agent_detail` conversation trace would not solve the timeline requirement: nested `async_converse` calls create separate traces, and that three-entry trace buffer is not the pipeline debug API the frontend displays.

## Session and streaming design

The router uses the normal `ConversationEntity` chat-log lifecycle. Local delegation gets a deterministic child conversation ID derived from the router entry and outer conversation ID. `async_get_chat_session` and `async_get_chat_log` own authorization, lifetime, nesting, and cleanup; the router maintains no separate session cache.

The child log keeps provisional local replies out of the outer stream. A local success is returned with the outer conversation ID and its speech added to the outer history. Fallback delegates with that outer ID, so a chat-log destination reuses the existing user message and stream. Buffered destinations receive the same request and return their response normally.

The strict handler has no gazetteer reference resolution. Pronouns go to fallback; exact local commands still work across turns. Cross-agent anaphora, real-model tool calls on multiple turns, audio interruption, speech synthesis, and physical satellites remain unverified. Separate local sessions can outlive an outer session until HA's normal cleanup expires them.

## Outcome handoff and core limitations

The router uses response type and `failed_results`, never spoken keywords, to decide fallback. `QUERY_ANSWER` reporting an unavailable state stays local. A local exception or the 30-second local deadline is uncertain; fallback has a 120-second deadline and is not retried. Cancellation is not converted into a fallback request.

`extra_system_prompt` contains a JSON outcome with this turn's final local response, completed/failed target lists, and local tool arguments/results. Caller-supplied extra prompt context is retained. The original user text remains unchanged. On fallback failure, an error response includes a local speech summary and a card containing the structured local outcome, because HA's error serialization omits target lists.

Intent handling can replace a service exception with generic `failed_to_handle` speech and omit per-target failure details. The wrapper passes the available response plus **this turn's** `ToolResultContent.result.data` and tool arguments; it cannot recover detail core did not expose. The exported strict handler also discards some matching-error responses. Therefore `not_handled` means no accepted response, not an unconditional assertion that an arbitrary custom handler had no side effects. The built-in rejection regression cases explicitly verify zero service calls and zero timers.

A slow service can continue in the background after HA's 0.2-second intent-service wait. Reported success is not a guarantee of physical completion, and a later background failure is not observable as a failed response to this router.

For more complete failure details, core would need to retain matching results and original failure reasons in its supported result contract. For hard no-replay guarantees, a separate, scoped execution/tool policy would be required. Instructions to a model are not that policy. An LLM handoff is not itself a safety guarantee.

The integration uses exported conversation/session APIs and public chat-log content classes. The format and completeness of the built-in agent's external tool outcomes are version-sensitive dependencies, not a promise across HA releases. Re-run this suite when upgrading HA. No gazetteer internals are imported by the integration.

## Provider compatibility: what is and is not established

**Executed:** a synthetic streaming destination calls HA's real `ChatLog.async_provide_llm_data` with `user_input.extra_system_prompt`. Assertions inspect its resulting system prompt, preserved original input/context, emitted Assist deltas, history, and final continuation flag. A buffered destination also works.

**Source inspection only:** the released [OpenAI](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/openai_conversation/conversation.py), [Google Generative AI](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/google_generative_ai_conversation/conversation.py), and [Anthropic](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/anthropic/conversation.py) conversation entities pass `extra_system_prompt` into that same HA prompt-preparation method.

**Unverified:** actual provider payloads, model interpretation, tool execution, provider-specific continuation/history rules, and third-party agents. The setup selector cannot establish these properties. An agent that ignores `extra_system_prompt` is unsuitable when local-failure context is required. The router rejects routers implemented by this integration; opaque cycles through third-party agents cannot be detected in advance.

## Historical measurement — superseded full-agent path

A one-off corpus on the original full-agent implementation produced **3 local answers and 2 LLM handoffs**, including a gazetteer-resolved misspelled command. Those counts do not describe the strict policy and are not a household accuracy estimate.

A one-off warm micro-measurement alternated direct full-agent calls and router calls for “turn on the kitchen ceiling lights,” with a new session per call, one warm-up per path, and 40 retained samples per path:

| Path | Median | Min–max |
| --- | --- | --- |
| Direct built-in agent | 0.437 ms | 0.358–0.612 ms |
| Router, local success | 0.560 ms | 0.460–1.185 ms |

Difference between medians: **0.123 ms added** in that orb and fixture. This includes session/log/delegation overhead, excludes startup, network, models, audio, and hardware, and is not evidence of a user-visible speed or cost improvement. The temporary measurement test was removed. This is historical evidence, not a benchmark or performance threshold for the strict policy.

## Release work intentionally deferred

Real-provider contract tests, HA-version coverage, language coverage beyond the English spike, default-catalog publication, release automation, a public-release license decision, and household acceptance testing remain outside this spike. The repository includes minimal `hacs.json` metadata and README buttons for custom-repository installation and integration setup; these do not imply catalog acceptance or release readiness. Start with an isolated test instance, not production automation.
