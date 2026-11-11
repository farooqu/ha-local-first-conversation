# Compatibility and troubleshooting

## Supported environment

Requires **Home Assistant 2026.11.1 or newer**; only 2026.11.1 has been verified. Older versions are rejected. Test newer HA versions before upgrading an installation you rely on.

Automated coverage uses English requests, synthetic devices, and synthetic streaming and buffered fallback agents. Real model requests, household operation, other languages, audio/TTS, and physical satellites have not been verified. The configuration screenshots use HA's Ollama integration; they do not demonstrate model responses.

## Fallback agents

Configure the LLM agent in its own integration first. The router accepts available conversation entities, except HA's built-in agent and other Local First Conversation routers.

The fallback must honor `ConversationInput.extra_system_prompt` to receive local results and instructions about unfinished actions. Setup cannot check this. HA 2026.11.1's [OpenAI](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/openai_conversation/conversation.py), [Google Generative AI](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/google_generative_ai_conversation/conversation.py), and [Anthropic](https://github.com/home-assistant/core/blob/2026.11.1/homeassistant/components/anthropic/conversation.py) implementations pass this context to HA's prompt preparation; that is source-level compatibility, not an end-to-end provider test. Check third-party agents individually. Routing loops through third-party agents cannot be detected in advance.

## Local matching limits

The router uses HA's strict sentence matcher with filtering before execution, not its full conversation agent or gazetteer name correction.

- State questions use HA's defined state vocabulary. Open-ended query values go to fallback, except person locations matching `home`, `not_home`, or a configured non-home zone's name. These names are case-sensitive; the home zone uses `home`, not its display name.
- Configured zones are checked on each request. An empty zone is valid; a removed zone is not.
- Misspelled names, pronoun follow-ups, and unsupported qualified or compound requests go to fallback. Each turn starts locally, regardless of which agent answered previously.
- Delayed device commands go to fallback before HA creates a timer. Existing timers are unaffected. Ordinary timer requests still have HA's device requirements.

Strict filtering avoids unsafe interpretations observed with HA's full agent, including immediate execution of negated or future-time commands. It does not validate arbitrary custom intent handlers or guarantee how an LLM interprets a request.

## Routing diagnostics

Find `intent → intent_output → local_first` in Assist's full-run **Raw** debug panel or downloaded debug JSON.

| Field | Meaning |
| --- | --- |
| `route` | `local` or `fallback`. |
| `agent_id` | `conversation.home_assistant` for local handling, or the configured fallback entity. |
| `local_outcome: not_handled` | No accepted local response, including a rejected interpretation. |
| `local_outcome: reported_failure` | Local handling returned an error or failed targets. |
| `local_outcome: uncertain` | Local handling raised or timed out; actions may have executed. |

When a local response exists, `local_response_type`, `local_error_code`, and `local_failed_targets` give more detail. A fallback route does not imply a successful LLM response; check the final `response_type`.

If the smaller NLP Raw panel is blank in HA 2026.11.1, use the full-run panel at the bottom of the timeline. The timeline's **Engine** names the router, while **Processed locally** refers to HA's pipeline shortcut. Requests that bypass the router, including pipeline sentence triggers, have no `local_first` metadata; old runs are not updated.

## Failures and conversation history

Local handling has a **30-second** deadline; fallback has a **120-second** deadline and is not retried automatically. Caller cancellation does not start a fallback request. If fallback fails, the error includes the available local summary and a card with the local outcome.

HA may omit matching errors or replace service failures with generic responses. Services can also continue after HA returns. Neither `not_handled` nor an error guarantees that nothing executed, and a successful response does not prove physical completion.

The router passes this turn's available responses, completed/failed targets, and tool outcomes to fallback. It cannot recover missing HA details or prevent an LLM from repeating actions. Provisional local replies stay out of the fallback's user/assistant history and Assist stream; successful local replies enter shared history. HA manages session authorization and cleanup. Cross-agent pronoun resolution is not supported locally.

## Run compatibility tests

Use `uv`, Python 3.14.2, and a C/C++ build toolchain. From the repository root, create a fresh environment:

```sh copy Copy Test Commands
uv venv --python 3.14.2
uv pip install -r requirements-test.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check custom_components tests scripts
.venv/bin/ruff format --check custom_components tests scripts
```

The pinned dependencies target HA 2026.11.1. Tests cover local matching, rejected requests without local actions or timers, partial failures, history, permissions, satellite context, streaming, configuration changes, timeouts, and release validation. They use the released HA stack with in-memory device services and loopback-only network access; no household or model credentials are required. Upstream deprecation warnings and blocked address-discovery probes are expected.

For the latest stable HA in an Amp orb, run `.agents/setup` before the checks above. It installs Python 3.14, HA, and test dependencies and prints their versions. Rerun it to refresh a reused environment. Successful installation alone does not establish compatibility.
