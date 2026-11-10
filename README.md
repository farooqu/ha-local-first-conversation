# ha-local-first-conversation

A standalone Home Assistant custom integration that routes requests through **local intent matching → gazetteer → an existing LLM conversation agent**.

**Compatibility spike, not a public-release package.** Tested on Home Assistant **2026.11.1**, with synthetic devices and a synthetic fallback agent. No live household or external model was used. See the [compatibility findings](docs/compatibility.md) for evidence and limits.

## Why this exists

An LLM can answer open-ended questions, but it does not need to handle every supported household command or state question. This integration gives HA's full built-in conversation agent the first opportunity to answer. Successful local answers return directly—even “off,” “no,” or a query reporting an unavailable state. The configured LLM handles requests the local agent cannot complete.

This differs from HA's **Prefer handling commands locally** shortcut in the tested version:

- **Supported state queries stay local.** In HA 2026.11.1, the pipeline shortcut excludes `HassGetState` when the selected agent advertises device-control support. This router delegates to the full local agent without that filter.
- **Gazetteer comes before the LLM.** The full local agent tries its gazetteer when strict sentence matching cannot resolve a request. The pipeline shortcut does not use that fallback. In the synthetic test home, “turn on the kichen lights” failed strict recognition but succeeded through HA's real gazetteer. This is HA's gazetteer, not an ASR correction wrapper or a copied recognizer. Its vocabulary is English-only in this release.
- **Reported handling failures reach the LLM.** Routing checks top-level errors and failed targets, not just `NO_INTENT_MATCH`. An unavailable device preventing a command, or a response with both completed and failed targets, causes a handoff with the available local results. A successful query *reporting* an unavailable state is not a failed command.

These are routing differences, not measured claims about household latency, model quality, or cost. HA's shortcut remains useful when its behavior matches your needs. This integration adds no classifier, model credentials, companion service, or core patches.

## Try the spike in a test instance

1. Use HA 2026.11.1. The integration rejects older versions; newer versions have not been verified.
2. Copy `custom_components/local_first_conversation` from the [public repository](https://github.com/farooqu/ha-local-first-conversation) into your HA configuration's `custom_components` directory, then restart HA.
3. Configure an LLM integration normally, including its allowed tools and exposed entities.
4. Add **Local First Conversation** under **Settings → Devices & services → Add integration**. Give it a name and select the existing fallback conversation entity.
5. Select the new router as the conversation agent in your Assist pipeline. **Disable Prefer handling commands locally** in that pipeline; the router owns that decision. HA's sentence triggers still run normally.
6. Test with synthetic devices before considering household use. Change the fallback through the integration's options. Router-to-router fallbacks, including self-selection, are rejected.

Setup accepts existing non-router conversation entities; it cannot prove an arbitrary agent is an LLM or honors the handoff prompt. Select one that consumes `ConversationInput.extra_system_prompt`. The spike does not yet include HACS distribution, release automation, a compatibility matrix across HA releases, or a license decision for public release.

### Integration-specific settings

The setup form needs only a **name** and an existing **fallback conversation agent**. Select your configured LLM agent—for example, **Ollama**, as shown below—not Home Assistant's built-in local agent. The router always uses the built-in agent first; you do not configure its gazetteer separately.

![Local First Conversation setup form](docs/images/setup.png)

In **Settings → Voice assistants**, open your assistant and select **Local First Conversation** under **Conversation agent**. Turn **Prefer handling commands locally** off, then save. The router already handles local matching and gazetteer before falling back to the LLM; leave the pipeline shortcut disabled.

![Assist pipeline with Local First Conversation selected and prefer-local disabled](docs/images/assist-pipeline.png)

The gear beside the conversation agent is **Agent settings**. It opens the router's **Options** dialog shown below, where you choose the fallback—not the pipeline's conversation agent. You can also reach this dialog through **Settings → Devices & services → Local First Conversation → Configure**. To change the fallback, select the replacement and submit. Existing model credentials and tool permissions remain in the selected agent's integration.

![Local First Conversation fallback options](docs/images/options.png)

These are captures of the real HA 2026.11.1 frontend with HA's Ollama integration in an isolated test instance. The router setup accepted the Ollama conversation entity, and its options show the saved selection. The pipeline was saved and reopened to verify the router selection and disabled shortcut; its Agent settings button opened the same Options dialog. Ollama's model-list endpoint was stubbed locally; no model inference was run. These screenshots demonstrate configuration, not provider behavior. No marketplace setup or live-household configuration is shown.

## Safety and conversation limits

- The original utterance, language, user context, device ID, and satellite ID are passed through. HA still controls exposure, authorization, and session ownership; the router grants no extra tools or permissions.
- The local branch has a separate HA-managed chat session. This preserves its local references while keeping local failure replies out of the fallback's user/assistant history and Assist stream. Every turn starts locally; routing is not sticky.
- Fallback receives the original request plus this turn's available local response, target lists, and local tool outcomes in `extra_system_prompt`. Those details can contain household names and go to the selected provider. Earlier successful local replies can also be included in later LLM conversation history. There is no router-specific transcript logging; normal HA traces and provider logging policies still apply.
- Partial completion is not atomic. Prompt guidance asks the LLM not to repeat completed actions, but **does not guarantee exactly-once execution**. Unknown completion, late background service failures, and provider behavior remain limits. Do not use this spike where hard no-replay enforcement is required.
- Streaming fallback text and the continuation flag passed the synthetic Assist intent-stage test. Local answers and non-streaming destinations are buffered. Real provider requests, audio/TTS playback, and pronouns referring only to LLM actions remain unverified.

## Run the compatibility tests

### Latest stable HA in an Amp orb

Run the repository's setup script to prepare this integration's isolated test environment:

```sh copy Copy Latest Test Commands
.agents/setup
.venv/bin/python -m pytest -q
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
```

Setup installs the latest Python 3.14 patch release, the latest stable HA release reported by PyPI, HA's declared conversation/Assist dependencies, and the test tools. It prints the resolved versions. It does not start HA, connect to a household, or configure a marketplace. Amp runs it when preparing a new project snapshot; reused snapshots may retain an earlier release until setup runs again.

Verified on 2026-11-10: setup into an empty virtual environment took 3 seconds with the orb's package cache populated; a repeat took 1 second. HA resolved to **2026.11.1**, Python to **3.14.7**, and all **12 tests passed**. Dependency consistency and Ruff checks also passed. These are cached-install timings, not fresh-orb download estimates. A future latest release is not verified merely because setup installs it: run the contract tests and investigate failures before using it.

### Reproduce the original spike versions

Python 3.14.2, `uv`, and a C/C++ build toolchain are needed for the pinned HA and Assist dependencies. Use a fresh virtual environment when switching from the latest-release workflow:

```sh copy Copy Pinned Test Commands
uv venv --python 3.14.2
uv pip install -r requirements-test.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
```

Tests boot the released HA package with real registries, sentence matching, gazetteer, intent handlers, conversation sessions, config/options flows, and Assist intent-stage processing. Devices and the model destination are synthetic. Network connections are restricted to loopback; no household credentials are required.

[Source](https://github.com/farooqu/ha-local-first-conversation) · [Issues](https://github.com/farooqu/ha-local-first-conversation/issues)
