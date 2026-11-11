"""Check the release-notes CLI without publishing anything."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/release_notes.py"


@pytest.mark.parametrize(
    ("version", "tag", "changelog", "error"),
    [
        (
            "0.1.0",
            "v0.1.0",
            "## [Unreleased]\n\n## [0.1.0]\n\n### Added\n- Local routing.\n\n## [0.0.0]\n- Old notes.\n",
            None,
        ),
        (
            "0.1.0-beta.2",
            "v0.1.0-beta.2",
            "## [0.1.0-beta.2] - 2026-11-11\n\n### Added\n- Local routing.\n",
            None,
        ),
        ("0.0.1", "v0.0.2", "## [0.0.1]\n- Local routing.\n", "does not match"),
        ("00.1.0", "v00.1.0", "## [00.1.0]\n- Local routing.\n", "Manifest version"),
        ("0.0.1", "v0.0.1", "## [Unreleased]\n- Local routing.\n", "one newest entry"),
        (
            "0.0.1",
            "v0.0.1",
            "## [0.0.1]\n- One.\n## [0.0.1]\n- Two.\n",
            "one newest entry",
        ),
        (
            "0.0.1",
            "v0.0.1",
            "## [0.0.2]\n- Newer.\n## [0.0.1]\n- Older.\n",
            "one newest entry",
        ),
        ("0.0.1", "v0.0.1", "## [0.0.1]\n\n### Added\n", "is empty"),
    ],
)
def test_release_notes(tmp_path, version, tag, changelog, error):
    """Only matching versions with substantive, isolated release notes succeed."""
    manifest = tmp_path / "custom_components/local_first_conversation/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"version": version}))
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), tag],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if error:
        assert result.returncode != 0
        assert error in result.stderr
        assert not result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout == "### Added\n- Local routing.\n"
