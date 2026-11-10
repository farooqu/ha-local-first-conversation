# Compatibility spike — HA 2026.11.1

## Result

The proposed delegation design is feasible on released **Home Assistant 2026.11.1**. The spike uses HA's full built-in agent, then an existing conversation entity, without modifying or monkey-patching core. The integration domain is `local_first_conversation`.

This is a compatibility result, not a supported public release. The setup floor is conservatively 2026.11.1 because that is the release tested here; it does not imply gazetteer first appeared in that patch. Older releases and future releases need separate verification.

## Pinned environment and evidence boundary

- HA package: `homeassistant==2026.11.1`, Python 3.14.2, Linux x86_64.
- Released core source: [2026.11.1](https://github.com/home-assistant/core/tree/2026.11.1), commit [`d8a0dc6`](https://github.com/home-assistant/core/commit/d8a0dc698c8946b44e455d904000db563cfbf1ba). The installed `default_agent.py` was byte-compared with that tag.
- Recognition dependencies: `gazetteer-matcher==1.1.0`, `hassil==3.12.1`, `home-assistant-intents==2026.10.27`.
- Tests create a temporary HA configuration, real registries, and synthetic kitchen lights, bedroom blinds, and a registered satellite. Service handlers change only in-memory states; unavailable-device failures are simulated service exceptions. The fallback is a synthetic conversation entity using real HA prompt preparation and chat-log streaming, not a model or a mocked gazetteer.
- `pytest-socket` permits only loopback connections. HA's source-address discovery probes to multicast and an external IP are blocked and produce warnings. HA/aiohttp/backoff also emit upstream warnings. No live household, model API, or provider credentials are accessed.

## Verified contracts

The retained suite, `tests/test_compatibility.py`, passes **12 tests** through the released HA stack:

| Boundary | Decisive observation |
| --- | --- |
| Intent → gazetteer | Strict recognition returns no usable match for “turn on the kichen lights”; full-agent delegation turns on the synthetic kitchen lights without invoking fallback. An exact command also matches and executes locally. |
| State queries | Exact and misspelled-name queries return `query_answer` containing `off`, `on`, and `unavailable`, with no fallback calls. |
| Refusal → LLM | “write a poem about my kitchen lights” returns local `no_intent_match`; the synthetic destination receives the original text and the local refusal in its prepared system prompt. |
| Partial target failure | A real HA intent handler returns `action_done` with a successful ceiling light and failed strip light. The router hands off both lists despite the absence of a top-level error. |
| Multi-action failure | Gazetteer completes a light action, then the synthetic blinds service fails. The final HA error omits prior targets; this turn's local tool results preserve the successful action for handoff. |
| Nested sessions and history | No busy-session error. The outer chat log has one user message and one final assistant answer on fallback, not a local failure answer plus a duplicate user message. |
| Multi-turn | Open misheard blinds → LLM poem → “close them” closes the same blinds. A new conversation cannot reuse that reference. Handoff data on a later failed turn excludes the previous turn's execution details. |
| Device/satellite | “turn on the lights in here” uses a registered kitchen satellite's area. Fallback retains the original context object and device/satellite IDs. |
| Permissions | Another user cannot reuse the session; an unexposed target does not execute through gazetteer. No extra LLM API or tools are registered. |
| Assist pipeline | The actual intent-stage pipeline with prefer-local disabled executes a registered sentence trigger once. Fallback emits `intent-progress` deltas “Fallback ” and “answer”, no local refusal text, and returns continuation=true. |
| Shortcut comparison | With a control-capable synthetic agent and prefer-local enabled, the same misheard command and a state question both reach that destination instead of the full local path. |
| Failure/lifecycle | A missing fallback, provider exception, and injected fallback timeout return errors without retry. Self-selection is rejected; an options change reloads the router and uses a buffered destination. Local timeout is marked uncertain while a synthetic service is in flight; caller cancellation propagates without invoking fallback. |

Run from a fresh environment using the commands in the [README](../README.md). The test harness does not depend on HA's separately versioned third-party pytest fixture package.

## Session and streaming design

The router uses the normal `ConversationEntity` chat-log lifecycle. Local delegation gets a deterministic child conversation ID derived from the router entry and outer conversation ID. `async_get_chat_session` and `async_get_chat_log` own authorization, lifetime, nesting, and cleanup; the router maintains no separate session cache.

The child log lets local gazetteer references persist without leaking provisional local replies into the outer stream. A local success is returned with the outer conversation ID and its speech added to the outer history. Fallback delegates with that outer ID, so a chat-log destination reuses the existing user message and stream. Buffered destinations receive the same request and return their response normally.

The local agent does not see LLM-only history. Its references mean the last target it handled, not necessarily the last target discussed with the LLM. We verified a local reference surviving an intervening LLM turn; cross-agent anaphora, tool calls on multiple LLM turns, audio interruption, speech synthesis, and physical satellite behavior were not verified. Separate local sessions can outlive an outer session until HA's normal cleanup expires them.

## Outcome handoff and core limitations

The router uses response type and `failed_results`, never spoken keywords, to decide fallback. `QUERY_ANSWER` reporting an unavailable state stays local. A local exception or the 30-second local deadline is uncertain; fallback has a 120-second deadline and is not retried. Cancellation is not converted into a fallback request.

`extra_system_prompt` contains a JSON outcome with this turn's final local response, completed/failed target lists, and local tool arguments/results. Caller-supplied extra prompt context is retained. The original user text remains unchanged. On fallback failure, an error response includes a local speech summary and a card containing the structured local outcome, because HA's error serialization omits target lists.

Two released-core behaviors constrain the available evidence:

1. [`DefaultAgent._async_process_frames`](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/conversation/default_agent.py) returns immediately on an error, dropping earlier successful frame responses from the final result. The spike reads **only this turn's** `ToolResultContent.result.data` from its child chat log to preserve those available results. It does not reconstruct or re-execute recognition.
2. Intent handling can replace a service exception with generic `failed_to_handle` speech and omit per-target failure details. The wrapper passes the available error, tool arguments, and prior results; it cannot recover an exception reason or target list core did not expose. A slow service can also continue in the background after HA's 0.2-second intent-service wait. A reported success is not a guarantee of physical completion, and a later background failure is not observable as a failed response to this router.

For more complete failure details, core would need to retain per-frame target results and original failure reasons in its supported result contract. For hard no-replay guarantees, a separate, scoped execution/tool policy would be required. Instructions to a model are not that policy.

The integration uses exported conversation/session APIs and public chat-log content classes. The format and completeness of the built-in agent's external tool outcomes are version-sensitive dependencies, not a promise across HA releases. Re-run this suite when upgrading HA. No gazetteer internals are imported by the integration.

## Provider compatibility: what is and is not established

**Executed:** a synthetic streaming destination calls HA's real `ChatLog.async_provide_llm_data` with `user_input.extra_system_prompt`. Assertions inspect its resulting system prompt, preserved original input/context, emitted Assist deltas, history, and final continuation flag. A buffered destination also works.

**Source inspection only:** the released [OpenAI](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/openai_conversation/conversation.py), [Google Generative AI](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/google_generative_ai_conversation/conversation.py), and [Anthropic](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/anthropic/conversation.py) conversation entities pass `extra_system_prompt` into that same HA prompt-preparation method.

**Unverified:** actual provider payloads, model interpretation, tool execution, provider-specific continuation/history rules, and third-party agents. The setup selector cannot establish these properties. An agent that ignores `extra_system_prompt` is unsuitable when local-failure context is required. The router rejects routers implemented by this integration; opaque cycles through third-party agents cannot be detected in advance.

## Small synthetic measurement

A one-off five-request corpus produced **3 local answers and 2 LLM handoffs**: exact command, state query, misheard-name command, open-ended question, and gazetteer refusal. These are fixture counts, not household accuracy estimates.

A one-off warm micro-measurement alternated direct full-agent calls and router calls for “turn on the kitchen ceiling lights,” with a new session per call, one warm-up per path, and 40 retained samples per path:

| Path | Median | Min–max |
| --- | --- | --- |
| Direct built-in agent | 0.437 ms | 0.358–0.612 ms |
| Router, local success | 0.560 ms | 0.460–1.185 ms |

Difference between medians: **0.123 ms added** in this orb and fixture. This includes session/log/delegation overhead, excludes startup, network, models, audio, and hardware, and is not evidence of a user-visible speed or cost improvement. The temporary measurement test was removed after recording its results; it is not a performance threshold in the contract suite.

## Release work intentionally deferred

Real-provider contract tests, HA-version coverage, language coverage beyond the English spike, HACS/release packaging, a public-release license decision, and household acceptance testing remain outside this spike. Start with an isolated test instance, not production automation.
