# Changelog

Changes by version. See [GitHub Releases](https://github.com/farooqu/ha-local-first-conversation/releases) for publication dates and downloads.

## [Unreleased]

## [0.2.0]

### Added

- Optional `listen_for_follow_up` tool for requesting another user turn without a spoken follow-up question. Enable **Local First Conversation follow-up** alongside **Assist** in the fallback OpenAI agent's existing tool/API options; no main-prompt changes are needed.
- Successful tool requests set Home Assistant's native continuation flag. Existing speech is preserved; an otherwise empty assistant turn gets a listening indicator in the response and history.
- Configurable **Listening indicator** in each router's existing options. It accepts a nonempty string and defaults to `👂`. Custom TTS providers must recognize the same marker to return a listening sound or phrase.

### Compatibility

- The listening indicator requires a compatible TTS provider. A custom provider can map a complete marker-only request to playable audio, such as a chime, a short phrase, or another sound, while captions and history retain the marker. The integration does not bundle audio or implement that mapping. Continuation is controlled separately through Home Assistant's native flag; the marker is not a general silent-listening API. Without the tool API selected, existing behavior is unchanged.
- Requires Home Assistant 2026.11.1 or newer; verified against 2026.11.1. Physical satellite reopening and model tool selection still need device testing. See [setup and limitations](https://github.com/farooqu/ha-local-first-conversation/blob/v0.2.0/README.md).

## [0.1.1]

### Fixed

- Package the integration icon so it appears in Home Assistant and Marketplace after installation.

## [0.1.0]

### Added

- Local handling of supported commands and state questions, with an existing LLM agent as fallback.
- Handoff of unmatched requests and handling failures, including available local results.
- Streaming fallback responses and fallback selection through setup and options.
- Routing details in Assist debug output.
- Marketplace installation guide and project icon.

### Compatibility

- Requires Home Assistant 2026.11.1 or newer; only 2026.11.1 has been verified. See [compatibility and limitations](https://github.com/farooqu/ha-local-first-conversation/blob/v0.1.0/docs/compatibility.md).
