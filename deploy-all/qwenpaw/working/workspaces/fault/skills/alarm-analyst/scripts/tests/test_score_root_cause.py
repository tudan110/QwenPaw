import importlib.util
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "score_root_cause.py"
SPEC = importlib.util.spec_from_file_location("alarm_confidence_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
scoring = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scoring)

CLAIM = "CPU采样满足配置阈值，触发告警"


def score(**overrides):
    args = {
        "claim": CLAIM,
        "object_match": 1,
        "mechanism": 1,
        "time_match": 1,
        "independent": 0,
    }
    args.update(overrides)
    return scoring.score_root_cause(**args)


def test_verified_trigger_without_independent_confirmation_is_90():
    actual = score()
    assert actual["ruleVersion"] == "root-cause-evidence-v2"
    assert actual["score"] == actual["rawScore"] == 90
    assert list(actual["components"].values()) == [20, 50, 20, 0]
    assert actual["limits"] == []
    assert actual["scoredClaim"] == CLAIM
    assert actual["isStatisticalProbability"] is False


def test_fully_supported_claim_with_independent_evidence_is_100():
    actual = score(independent=1)
    assert actual["score"] == actual["rawScore"] == 100


def test_unknown_mechanism_still_has_a_low_ceiling():
    actual = score(
        claim="阈值配置不合理（尚无规则目的或基线）",
        mechanism=0,
        independent=1,
    )
    assert actual["rawScore"] == 50
    assert actual["score"] == 40
    assert actual["limits"][0]["cap"] == 40


def test_partial_mechanism_does_not_reach_high_confidence():
    assert score(mechanism=0.5, independent=1)["score"] == 75


def test_key_conflict_is_not_masked_by_high_component_scores():
    actual = score(independent=1, key_conflict=True)
    assert actual["rawScore"] == 100
    assert actual["score"] == 30


@pytest.mark.parametrize(
    "levels,conflict",
    list(
        itertools.product(
            itertools.product((0, 0.5, 1), repeat=4), (False, True)
        )
    ),
)
def test_all_allowed_factor_combinations(levels, conflict):
    actual = score(
        object_match=levels[0],
        mechanism=levels[1],
        time_match=levels[2],
        independent=levels[3],
        key_conflict=conflict,
    )
    raw = sum(
        weight * level for weight, level in zip((20, 50, 20, 10), levels)
    )
    caps = [raw]
    if levels[1] == 0:
        caps.append(40)
    if conflict:
        caps.append(30)
    assert actual["rawScore"] == raw
    assert actual["score"] == min(caps)


@pytest.mark.parametrize("value", [-1, 0.1, 2, True, "1", None, float("nan")])
def test_invalid_levels_are_errors_not_default_scores(value):
    with pytest.raises(ValueError, match="证据等级"):
        score(mechanism=value)


@pytest.mark.parametrize("claim", ["", " ", None])
def test_scoring_without_an_explicit_claim_is_rejected(claim):
    with pytest.raises(ValueError, match="具体结论"):
        score(claim=claim)


def test_cli_returns_v2_90_without_files_or_network(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--claim",
            CLAIM,
            "--object-match",
            "1",
            "--mechanism",
            "1",
            "--time-match",
            "1",
            "--independent",
            "0",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(completed.stdout)["score"] == 90
    assert completed.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_cli_invalid_input_fails_visibly(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--claim",
            CLAIM,
            "--object-match",
            "1",
            "--mechanism",
            "0.9",
            "--time-match",
            "1",
            "--independent",
            "0",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "invalid choice" in completed.stderr


def test_contract_has_no_v1_factors_and_example_agrees_with_code():
    skill_dir = SCRIPT.parents[1]
    protocol = (skill_dir / "references/portal-card-protocol.md").read_text()
    skill = (skill_dir / "SKILL.md").read_text()
    for text in (protocol, skill):
        for old in (
            "统一五项",
            "评分五项",
            "0/10/20",
            "20+10+0+0+0",
            "无独立复现",
        ):
            assert old not in text
    assert "20O+50M+20T+10I" in protocol
    example = re.search(r"```md\n([\s\S]*?)\n```", protocol)
    assert example is not None
    summary = example.group(1).split("## 📊 总结", 1)[1]
    assert summary.splitlines()[1] == "- 置信度：90%"
    assert "非统计概率" in example.group(1).split("## 📊 总结", 1)[0]
    assert score()["score"] == 90
