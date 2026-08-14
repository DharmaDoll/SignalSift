from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/signalsift.yml"
LOAD_STATE_SCRIPT = ROOT / ".github/scripts/load-state.sh"
PERSIST_STATE_SCRIPT = ROOT / ".github/scripts/persist-state.sh"


def test_workflow_keeps_schedule_disabled_until_operations_enable_it() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert '  # schedule:' in text
    assert '  #   - cron: "17,47 * * * *"' in text
    assert "  workflow_dispatch:" in text


def test_workflow_dispatch_can_simulate_state_without_slack() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    dispatch = document[True]["workflow_dispatch"]
    job = document["jobs"]["collect"]
    steps = {step["name"]: step for step in job["steps"]}

    assert dispatch["inputs"]["simulate_delivery"] == {
        "description": "Test both profiles without Slack, persisting to state-test",
        "required": True,
        "default": True,
        "type": "boolean",
    }
    assert "'state-test' || 'state'" in job["env"]["STATE_BRANCH"]
    assert "inputs.simulate_delivery" in job["env"]["SIMULATE_DELIVERY"]
    assert "simulation_flag=(--simulate-delivery)" in steps[
        "Run Supply Chain Vulnerability profile"
    ]["run"]
    assert "simulation_flag=(--simulate-delivery)" in steps[
        "Run AI Security profile"
    ]["run"]
    assert steps["Load notification state"]["run"] == ".github/scripts/load-state.sh"
    assert steps["Persist notification state"]["run"] == (
        ".github/scripts/persist-state.sh"
    )


def test_workflow_keeps_failure_and_state_boundaries_explicit() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = document["jobs"]["collect"]["steps"]
    names = [step["name"] for step in steps]
    by_name = {step["name"]: step for step in steps}

    assert names == [
        "Checkout",
        "Set up uv and Python",
        "Install",
        "Test",
        "Configure Git authentication",
        "Load notification state",
        "Run Supply Chain Vulnerability profile",
        "Run AI Security profile",
        "Persist notification state",
        "Remove Git credentials",
        "Report collector failure",
    ]
    assert by_name["Run Supply Chain Vulnerability profile"]["continue-on-error"] is True
    assert by_name["Run AI Security profile"]["continue-on-error"] is True
    assert set(by_name["Run Supply Chain Vulnerability profile"]["env"]) == {
        "SLACK_WEBHOOK_URL_SUPPLY_CHAIN_VULNERABILITY"
    }
    assert set(by_name["Run AI Security profile"]["env"]) == {
        "SLACK_WEBHOOK_URL_AI_SECURITY"
    }
    assert set(by_name["Load notification state"]["env"]) == {"GITHUB_TOKEN"}
    assert set(by_name["Persist notification state"]["env"]) == {
        "GITHUB_TOKEN",
        "STATE_BRANCH_EXISTS",
    }
    assert by_name["Persist notification state"]["if"] == (
        "always() && steps.load_state.outcome == 'success'"
    )
    assert by_name["Remove Git credentials"]["if"] == "always()"
    failure_condition = by_name["Report collector failure"]["if"]
    assert "steps.run_supply_chain.outcome == 'failure'" in failure_condition
    assert "steps.run_ai_security.outcome == 'failure'" in failure_condition


def test_workflow_does_not_put_github_token_in_remote_url() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (WORKFLOW, LOAD_STATE_SCRIPT, PERSIST_STATE_SCRIPT)
    )

    assert 'git remote set-url origin "https://github.com/${GITHUB_REPOSITORY}.git"' in text
    assert "x-access-token:${GITHUB_TOKEN}" not in text
    assert "GIT_ASKPASS" in text


def test_workflow_distinguishes_missing_state_branch_from_git_failure() -> None:
    text = LOAD_STATE_SCRIPT.read_text(encoding="utf-8")

    assert 'git ls-remote --exit-code --heads origin "$STATE_BRANCH"' in text
    assert '"$state_probe" -eq 2' in text
    assert "cannot inspect origin/$STATE_BRANCH" in text


def test_workflow_state_scripts_have_valid_bash_syntax() -> None:
    for script in (LOAD_STATE_SCRIPT, PERSIST_STATE_SCRIPT):
        subprocess.run(["bash", "-n", script], check=True)


def test_workflow_yaml_is_valid() -> None:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    assert document["permissions"] == {"contents": "write"}
    assert document["jobs"]["collect"]["timeout-minutes"] == 10
