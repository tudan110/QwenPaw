import copy
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "summarize_metric_result.py"
SPEC = importlib.util.spec_from_file_location("alarm_metric_summary", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


def records(samples, **overrides):
    item = {
        "resId": "8493",
        "subResName": None,
        "originalDatas": samples,
        "processData": {
            "cpu_usage_activeMin": "8.53",
            "cpu_usage_activeMax": "35.95",
            "cpu_usage_activeAvg": "15.54",
            "cpu_usage_active_unit": "%",
        },
    }
    item.update(overrides)
    return [
        {"kind": "model_turn", "name": summary.TOOL_NAME, "content": "ignore"},
        {
            "kind": "tool_result",
            "name": summary.TOOL_NAME,
            "content": json.dumps({"code": 200, "data": [item]}),
        },
    ]


def result(rows):
    return summary.summarize_records(rows, res_id="8493")["resources"][0]


def sample(time, value="12.3"):
    return {"formatTime": time, "cpu_usage_active": value}


def test_sorts_full_coverage_and_preserves_original_statistics():
    rows = records(
        [
            sample("2026-10-28 15:27:45"),
            sample("2026-10-28 14:18:00"),
            sample("2026-10-28 14:25:30", "35.95"),
        ]
    )
    before = copy.deepcopy(rows)
    actual = result(rows)
    assert actual["actualStart"] == "2026-10-28 14:18:00"
    assert actual["actualEnd"] == "2026-10-28 15:27:45"
    assert actual["sampleCount"] == actual["timestampCount"] == 3
    assert actual["apiStatistics"]["cpu_usage_activeAvg"] == "15.54"
    assert actual["statisticsSource"] == "原接口统计，未筛选重算"
    assert "未提供时区" in actual["timeBasis"]
    assert rows == before


def test_duplicate_times_do_not_deduplicate_samples():
    actual = result(records([sample("2026-10-28 14:18:00")] * 2))
    assert actual["sampleCount"] == actual["timestampCount"] == 2
    assert actual["uniqueTimestampCount"] == 1
    assert any("重复时间" in text for text in actual["limitations"])


@pytest.mark.parametrize("time", [None, ""])
def test_missing_time_keeps_counts_and_reports_partial_coverage(time):
    actual = result(records([sample(time), sample("2026-10-28 14:18:00")]))
    assert actual["sampleCount"] == 2
    assert actual["timestampCount"] == 1
    assert any("部分样本缺少时间" in text for text in actual["limitations"])


def test_empty_samples_are_not_a_healthy_resource_or_zero_statistics():
    actual = result(records([], processData=None))
    assert actual["sampleCount"] == 0
    assert actual["actualStart"] is actual["actualEnd"] is None
    assert actual["apiStatistics"] == {}
    assert any("不代表资源正常" in text for text in actual["limitations"])


def test_all_missing_times_leave_boundaries_unknown():
    actual = result(records([sample(None)]))
    assert actual["timestampCount"] == 0
    assert actual["actualStart"] is actual["actualEnd"] is None
    assert any("起止未知" in text for text in actual["limitations"])


def test_aware_times_are_sorted_by_instant_not_lexically():
    actual = result(
        records(
            [
                sample("2026-10-28 08:00:00+00:00"),
                sample("2026-10-28 15:30:00+08:00"),
            ]
        )
    )
    assert actual["actualStart"] == "2026-10-28 15:30:00+08:00"
    assert actual["actualEnd"] == "2026-10-28 08:00:00+00:00"


@pytest.mark.parametrize("time", ["invalid", "2026-10-28", 1793168280])
def test_invalid_times_are_not_sorted_or_guessed(time):
    with pytest.raises(ValueError, match="formatTime"):
        result(records([sample(time)]))


def test_mixed_timezone_basis_is_an_explicit_error():
    with pytest.raises(ValueError, match="时区"):
        result(
            records(
                [
                    sample("2026-10-28 14:18:00"),
                    sample("2026-10-28 15:27:45+08:00"),
                ]
            )
        )


@pytest.mark.parametrize(
    "rows", [[], [{"kind": "tool_result", "name": "other"}]]
)
def test_no_matching_tool_result_is_not_success(rows):
    with pytest.raises(ValueError, match="唯一"):
        result(rows)


def test_ambiguous_results_are_not_resolved_by_latest_or_first():
    rows = records([sample("2026-10-28 14:18:00")])
    with pytest.raises(ValueError, match="唯一"):
        result(rows + rows)


@pytest.mark.parametrize("content", ['{"code":200,"data":[', "[]", None])
def test_invalid_or_truncated_response_is_explicit(content):
    rows = records([])
    rows[-1]["content"] = content
    with pytest.raises(ValueError):
        result(rows)


@pytest.mark.parametrize("code", [400, 403, 500, None, False, "error"])
def test_failed_response_does_not_become_empty_data(code):
    rows = records([])
    rows[-1]["content"] = json.dumps({"code": code, "data": []})
    with pytest.raises(ValueError, match="未成功"):
        result(rows)


@pytest.mark.parametrize(
    "overrides",
    [
        {"originalDatas": None},
        {"originalDatas": ["not a sample"]},
        {"processData": []},
        {"resId": "another-resource"},
        {"resId": True},
    ],
)
def test_invalid_resource_or_structure_does_not_fall_back(overrides):
    with pytest.raises(ValueError):
        result(records([sample("2026-10-28 14:18:00")], **overrides))


def test_subresources_are_kept_separate_and_other_resources_are_excluded():
    rows = records([sample("2026-10-28 14:18:00")], subResName="cpu-0")
    payload = json.loads(rows[-1]["content"])
    second = copy.deepcopy(payload["data"][0])
    second["subResName"] = "cpu-1"
    other = copy.deepcopy(second)
    other["resId"] = "other"
    payload["data"].extend([second, other])
    rows[-1]["content"] = json.dumps(payload)
    actual = summary.summarize_records(rows, res_id=8493)["resources"]
    assert [item["subResName"] for item in actual] == ["cpu-0", "cpu-1"]


def test_summary_uses_only_supplied_records_without_io(monkeypatch):
    rows = records([sample("2026-10-28 14:18:00")])

    def forbidden(*args, **kwargs):
        raise AssertionError("Summary must not perform I/O")

    monkeypatch.setattr("sqlite3.connect", forbidden)
    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    actual = result(rows)
    assert actual["sampleCount"] == 1


def test_first_read_contains_executable_summary_and_complete_template(capsys):
    skill_dir = SCRIPT.parents[1]
    protocol = (skill_dir / "references/portal-card-protocol.md").read_text(
        encoding="utf-8"
    )
    example = re.search(r"```md\n([\s\S]*?)\n```", protocol)
    assert example is not None
    assert len(protocol[: example.end()].splitlines()) <= 132
    report = example.group(1)
    assert len(report) <= 4500
    assert report.rstrip().endswith("- 通知状态：未执行")
    for heading in (
        "告警基础信息",
        "数据查询与整理",
        "异常关联分析",
        "根因判断",
        "影响范围",
        "知识匹配与适用性",
        "处置建议",
        "异常指标",
        "自动化执行结果",
        "恢复验证与状态回写",
        "分析依据与待确认事项",
        "📊 总结",
    ):
        assert "## " + heading in report
    code = re.search(r"```python\n([\s\S]*?)\n```", protocol)
    assert code is not None
    source = (
        code.group(1)
        .replace("<实际技能目录>", str(skill_dir))
        .replace("<本轮真实工具ID>", "actual-tool-id")
        .replace("<本轮CI>", "8493")
    )
    recall = Mock(
        return_value=records(
            [
                sample("2026-10-28 15:27:45"),
                sample("2026-10-28 14:18:00"),
            ]
        )
    )
    exec(
        compile(source, "protocol-summary-example", "exec"),
        {
            "ms": SimpleNamespace(recall_tool=recall),
        },
    )
    recall.assert_called_once_with("actual-tool-id")
    actual = json.loads(capsys.readouterr().out)["resources"][0]
    assert actual["sampleCount"] == 2
    assert actual["actualStart"] == "2026-10-28 14:18:00"
    assert actual["actualEnd"] == "2026-10-28 15:27:45"
