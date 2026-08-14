from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/signalsift.yml"


def test_workflow_keeps_schedule_disabled_until_operations_enable_it() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert '  # schedule:' in text
    assert '  #   - cron: "17,47 * * * *"' in text
    assert "  workflow_dispatch:" in text


def test_workflow_dispatch_can_simulate_state_without_slack() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    dispatch = document[True]["workflow_dispatch"]
    collector = document["jobs"]["collect"]["steps"][4]

    assert dispatch["inputs"]["simulate_delivery"] == {
        "description": "Test both profiles without Slack, persisting to state-test",
        "required": True,
        "default": True,
        "type": "boolean",
    }
    assert collector["name"] == "Run collector and persist state"
    assert "state_branch=state-test" in collector["run"]
    assert "simulation_flag=(--simulate-delivery)" in collector["run"]
    assert 'git push origin "$state_branch"' in collector["run"]


def test_workflow_does_not_put_github_token_in_remote_url() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'git remote set-url origin "https://github.com/${GITHUB_REPOSITORY}.git"' in text
    assert "x-access-token:${GITHUB_TOKEN}" not in text
    assert "GIT_ASKPASS" in text


def test_workflow_distinguishes_missing_state_branch_from_git_failure() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'git ls-remote --exit-code --heads origin "$state_branch"' in text
    assert '"$state_probe" -ne 2' in text
    assert "cannot inspect origin/$state_branch" in text


def test_workflow_yaml_is_valid() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    assert document["permissions"] == {"contents": "write"}
    assert document["jobs"]["collect"]["timeout-minutes"] == 10
