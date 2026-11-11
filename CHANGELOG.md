# Changelog

Changes by version. See [GitHub Releases](https://github.com/farooqu/ha-local-first-conversation/releases) for publication dates and downloads.

## [Unreleased]

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
