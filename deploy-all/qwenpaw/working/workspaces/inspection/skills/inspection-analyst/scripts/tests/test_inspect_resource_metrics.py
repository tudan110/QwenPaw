import importlib.util
from pathlib import Path
from unittest.mock import patch


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载模块: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCRIPT_DIR = Path(__file__).resolve().parents[1]
INSPECTION_MODULE = _load_module(
    "inspection_metric_test_module",
    SCRIPT_DIR / "inspect_resource_metrics.py",
)


def test_fetch_all_metric_definitions_paginates_and_dedupes():
    responses = [
        {
            "source": "live",
            "url": "http://example/api",
            "request": {"pageNum": 1},
            "fallbackReason": None,
            "metrics": [
                {"code": "m1", "name": "指标1", "unit": ""},
                {"code": "m2", "name": "指标2", "unit": "%"},
            ],
        },
        {
            "source": "live",
            "url": "http://example/api",
            "request": {"pageNum": 2},
            "fallbackReason": None,
            "metrics": [
                {"code": "m2", "name": "指标2", "unit": "%"},
                {"code": "m3", "name": "指标3", "unit": "ms"},
            ],
        },
        {
            "source": "live",
            "url": "http://example/api",
            "request": {"pageNum": 3},
            "fallbackReason": None,
            "metrics": [],
        },
    ]

    with patch.object(
        INSPECTION_MODULE._ALARM_METRIC_HELPERS,
        "fetch_metric_definitions",
        side_effect=responses,
    ) as mocked_fetch:
        result = INSPECTION_MODULE.fetch_all_metric_definitions(
            metric_type="mysql",
            page_size=2,
        )

    assert mocked_fetch.call_count == 3
    assert result["metricsTotal"] == 3
    assert [item["code"] for item in result["metrics"]] == ["m1", "m2", "m3"]


def test_fetch_metric_data_batch_uses_all_metric_codes_in_one_request():
    recorded_payloads = []

    def _fake_post_json_with_fallback(*, url, headers, json_payload, timeout_seconds):
        recorded_payloads.append(
            {
                "url": url,
                "headers": headers,
                "json_payload": json_payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return (
            {
                "code": 200,
                "msg": "ok",
                "data": [
                    {
                        "resId": "3094",
                        "processData": {
                            "m1Min": "1",
                            "m1Avg": "2",
                            "m1Max": "3",
                            "m2Min": "4",
                            "m2Avg": "5",
                            "m2Max": "6",
                        },
                        "originalDatas": [
                            {"formatTime": "2026-04-24 10:00:00", "m1": "2", "m2": "5"}
                        ],
                    }
                ],
            },
            "requests",
        )

    with patch.object(
        INSPECTION_MODULE._ALARM_METRIC_HELPERS,
        "_normalize_base_url",
        return_value="http://example.test",
    ), patch.object(
        INSPECTION_MODULE._ALARM_METRIC_HELPERS,
        "_get_token",
        return_value="token",
    ), patch.object(
        INSPECTION_MODULE._ALARM_METRIC_HELPERS,
        "_post_json_with_fallback",
        side_effect=_fake_post_json_with_fallback,
    ):
        result = INSPECTION_MODULE.fetch_metric_data_batch(
            res_id="3094",
            metric_definitions=[
                {"code": "m1", "name": "指标1", "unit": ""},
                {"code": "m2", "name": "指标2", "unit": "%"},
            ],
        )

    assert recorded_payloads[0]["json_payload"]["queryKeys"] == ["m1", "m2"]
    assert result["metricResults"][0]["latestValue"] == "2"
    assert result["metricResults"][1]["latestValue"] == "5"


def test_render_markdown_contains_metric_table():
    markdown = INSPECTION_MODULE.render_markdown(
        {
            "inspectionObject": "数据库",
            "resourceName": "db_mysql_001",
            "resId": "3094",
            "metricType": "mysql",
            "definitions": {
                "metricsTotal": 2,
                "source": "live",
                "fallbackReason": None,
            },
            "metricDataBatch": {
                "source": "live",
                "fallbackReason": None,
                "metricResults": [
                    {
                        "metricName": "活跃线程数",
                        "metricCode": "threads_running",
                        "latestValue": "12",
                        "sampleTime": "2026-04-24 10:00:00",
                        "minValue": "10",
                        "avgValue": "11",
                        "maxValue": "12",
                        "unit": "",
                        "source": "live",
                    }
                ],
            },
        }
    )

    assert "## 巡检结果" in markdown
    assert "db_mysql_001" in markdown
    assert "threads_running" in markdown
