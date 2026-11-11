"""Validate the manifest/changelog contract and print a release's notes."""

import argparse
import json
import re
from pathlib import Path


def main() -> None:
    """Emit release notes only when the version and optional tag agree."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", nargs="?", help="Expected release tag, such as v0.1.0")
    args = parser.parse_args()
    version = json.loads(
        Path("custom_components/local_first_conversation/manifest.json").read_text()
    )["version"]
    number = r"(?:0|[1-9][0-9]*)"
    if not re.fullmatch(
        rf"{number}\.{number}\.{number}(?:-(?:alpha|beta|rc)\.[1-9][0-9]*)?",
        version,
    ):
        parser.error("Manifest version must be X.Y.Z or X.Y.Z-{alpha,beta,rc}.N")
    if args.tag is not None and args.tag != f"v{version}":
        parser.error(f"Tag {args.tag!r} does not match manifest version v{version}")

    changelog = Path("CHANGELOG.md").read_text()
    sections = list(
        re.finditer(
            r"^## \[([^\]]+)\](?: - [0-9]{4}-[0-9]{2}-[0-9]{2})?\n(.*?)(?=^## |\Z)",
            changelog,
            flags=re.MULTILINE | re.DOTALL,
        )
    )
    versions = [section for section in sections if section[1] != "Unreleased"]
    matches = [section for section in versions if section[1] == version]
    if len(matches) != 1 or versions[0][1] != version:
        parser.error(f"Changelog must have one newest entry headed ## [{version}]")
    notes = matches[0][2].strip()
    if not any(
        line.strip() and not line.startswith("#") for line in notes.splitlines()
    ):
        parser.error(f"Changelog entry for {version} is empty")
    print(notes)


if __name__ == "__main__":
    main()
