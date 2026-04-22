import unittest
from unittest.mock import patch

import analyze_alarm_context as alarm_context_module

from analyze_alarm_context import (
    _build_alarm_comparison_summary,
    _build_alarm_query_windows,
    _extract_resource_dicts,
    _build_topology_summary,
    _collect_related_resource_ids,
    _infer_correlation_findings,
)


class AnalyzeAlarmContextTests(unittest.TestCase):
    def test_build_alarm_query_windows_defaults_to_plus_minus_ten_minutes(self):
        windows = _build_alarm_query_windows(
            event_time="2026-04-20 18:39:19",
            window_minutes=10,
        )

        self.assertEqual(windows["recentBeginTime"], "2026-04-20 18:29:19")
        self.assertEqual(windows["recentEndTime"], "2026-04-20 18:49:19")
        self.assertEqual(windows["previousBeginTime"], "2026-04-20 18:09:19")
        self.assertEqual(windows["previousEndTime"], "2026-04-20 18:29:19")

    def test_build_alarm_query_windows_accepts_ai_defined_compare_window(self):
        windows = _build_alarm_query_windows(
            event_time="2026-04-20 18:39:19",
            window_minutes=10,
            compare_begin_time="2026-04-08 15:39:35",
            compare_end_time="2026-04-15 15:39:35",
        )

        self.assertEqual(windows["previousBeginTime"], "2026-04-08 15:39:35")
        self.assertEqual(windows["previousEndTime"], "2026-04-15 15:39:35")

    def test_collect_related_resource_ids_deduplicates_and_keeps_root_first(self):
        resource_rows = [
            {"_id": 4001, "ci_type": "mysql", "name": "mysql-main"},
            {"_id": 5002, "ci_type": "docker", "name": "mysql-pod"},
            {"id": "5002", "ci_type": "docker", "name": "mysql-pod-dup"},
            {"_id": 6003, "ci_type": "vserver", "name": "node-1"},
        ]

        result = _collect_related_resource_ids(root_res_id="4001", resource_rows=resource_rows)

        self.assertEqual(result, ["4001", "5002", "6003"])

    def test_collect_related_resource_ids_extracts_nested_relation_endpoints(self):
        resource_rows = [
            {
                "src_ci_id": "4001",
                "dst_ci_id": "5002",
                "parent": {"_id": 6003, "ci_type": "docker", "name": "mysql-pod"},
                "child": {"id": "7004", "ci_type": "vserver", "name": "node-1"},
            }
        ]

        result = _collect_related_resource_ids(root_res_id="3094", resource_rows=resource_rows)

        self.assertEqual(result, ["3094", "4001", "5002", "6003", "7004"])

    def test_extract_resource_dicts_keeps_nested_resource_objects(self):
        resources = _extract_resource_dicts(
            [
                {
                    "relation": "deploy",
                    "source": {"_id": 3094, "ci_type": "mysql", "name": "db_mysql_001"},
                    "target": {"_id": 5002, "ci_type": "docker", "name": "mysql-pod"},
                }
            ]
        )

        resource_ids = {_resource["name"] for _resource in resources}
        self.assertEqual(resource_ids, {"db_mysql_001", "mysql-pod"})

    def test_build_topology_summary_counts_ci_types(self):
        resource_rows = [
            {"_id": 4001, "ci_type": "mysql", "ci_type_alias": "MySQL", "name": "mysql-main"},
            {"_id": 5002, "ci_type": "docker", "ci_type_alias": "Docker", "name": "mysql-pod"},
            {"_id": 6003, "ci_type": "docker", "ci_type_alias": "Docker", "name": "mysql-pod-2"},
        ]

        summary = _build_topology_summary(root_res_id="4001", resource_rows=resource_rows)

        self.assertEqual(summary["resourceCount"], 3)
        self.assertEqual(summary["resourceIds"], ["4001", "5002", "6003"])
        self.assertEqual(summary["ciTypeCounts"]["docker"], 2)
        self.assertEqual(summary["resources"][0]["resId"], "4001")

    def test_build_topology_summary_prefers_explicit_root_resource_for_root_ci_type(self):
        summary = _build_topology_summary(
            root_res_id="3094",
            resource_rows=[
                {"_id": 5002, "ci_type": "docker", "ci_type_alias": "Docker", "name": "mysql-pod"},
            ],
            root_resource={
                "_id": 3094,
                "ci_type": "mysql",
                "ci_type_alias": "MySQL",
                "name": "db_mysql_001",
            },
        )

        self.assertEqual(summary["rootResource"]["resId"], "3094")
        self.assertEqual(summary["rootResource"]["ciType"], "mysql")
        self.assertEqual(summary["resources"][0]["ciType"], "mysql")

    def test_build_alarm_comparison_summary_reports_growth(self):
        summary = _build_alarm_comparison_summary(
            current_rows=[
                {"alarmtitle": "数据库锁异常", "resId": "3094"},
                {"alarmtitle": "数据库锁异常", "resId": "6003"},
                {"alarmtitle": "MySQL连接数过高", "resId": "5002"},
            ],
            previous_rows=[
                {"alarmtitle": "数据库锁异常", "resId": "3094"},
            ],
        )

        self.assertEqual(summary["currentTotal"], 3)
        self.assertEqual(summary["previousTotal"], 1)
        self.assertEqual(summary["deltaTotal"], 2)
        self.assertEqual(summary["titleDelta"]["数据库锁异常"], 1)

    def test_infer_correlation_findings_mentions_same_alarm_title_metric_anomaly_and_alarm_growth(self):
        findings = _infer_correlation_findings(
            current_alarm={
                "alarmtitle": "数据库锁异常",
                "resId": "3094",
                "devName": "db_mysql_001",
            },
            related_alarm_rows=[
                {"alarmtitle": "数据库锁异常", "resId": "3094", "devName": "db_mysql_001"},
                {"alarmtitle": "数据库锁异常", "resId": "6003", "devName": "mysql-replica"},
                {"alarmtitle": "MySQL连接数过高", "resId": "5002", "devName": "mysql-pod"},
            ],
            metric_data_results=[
                {
                    "metricCode": "mysql_global_status_innodb_row_lock_time",
                    "latestValue": "1874522.50",
                    "avgValue": "1874522.50",
                    "unit": "ms",
                }
            ],
            alarm_comparison={
                "currentTotal": 3,
                "previousTotal": 1,
                "deltaTotal": 2,
                "titleDelta": {"数据库锁异常": 1},
            },
        )

        self.assertTrue(any("同名告警" in item for item in findings))
        self.assertTrue(any("锁等待" in item for item in findings))
        self.assertTrue(any("环比" in item for item in findings))

    @patch("analyze_alarm_context._load_cmdb_client")
    @patch("analyze_alarm_context._fetch_root_resource_detail")
    @patch("analyze_alarm_context._build_topology_summary")
    @patch("analyze_alarm_context._query_alarms_for_res_id")
    @patch("get_metric_definitions.analyze_metrics")
    def test_analyze_alarm_context_completes_metrics_and_topology_before_alarm_fanout(
        self,
        mock_analyze_metrics,
        mock_query_alarms_for_res_id,
        mock_build_topology_summary,
        mock_fetch_root_resource_detail,
        mock_load_cmdb_client,
    ):
        call_order = []

        class _FakeClient:
            def _request_json(self, _path):
                call_order.append("topology")
                return {"result": [{"_id": 5002, "ci_type": "docker", "name": "mysql-pod"}]}

        mock_load_cmdb_client.return_value = (_FakeClient(), None, "anonymous")
        mock_fetch_root_resource_detail.return_value = {
            "_id": 3094,
            "ci_type": "mysql",
            "ci_type_alias": "MySQL",
            "name": "db_mysql_001",
        }

        def _fake_build_topology_summary(root_res_id, resource_rows, root_resource=None):
            if resource_rows:
                return {
                    "rootResId": root_res_id,
                    "rootResource": {
                        "resId": "3094",
                        "ciType": "mysql",
                        "ciTypeAlias": "MySQL",
                        "name": "db_mysql_001",
                        "isRoot": True,
                    },
                    "resourceCount": 2,
                    "resourceIds": ["3094", "5002"],
                    "ciTypeCounts": {"docker": 1},
                    "resources": [],
                }
            return {
                "rootResId": root_res_id,
                "rootResource": {
                    "resId": "3094",
                    "ciType": "mysql",
                    "ciTypeAlias": "MySQL",
                    "name": "db_mysql_001",
                    "isRoot": True,
                },
                "resourceCount": 1,
                "resourceIds": ["3094"],
                "ciTypeCounts": {},
                "resources": [],
            }

        mock_build_topology_summary.side_effect = _fake_build_topology_summary

        def _fake_query_alarms_for_res_id(**kwargs):
            call_order.append(f"alarm:{kwargs['res_id']}")
            return {"resId": kwargs["res_id"], "code": 200, "msg": "ok", "total": 0, "rows": []}

        mock_query_alarms_for_res_id.side_effect = _fake_query_alarms_for_res_id

        def _fake_analyze_metrics(**kwargs):
            call_order.append("metrics")
            return {"metricType": kwargs["metric_type"], "metricDataResults": [], "selectedMetrics": []}

        mock_analyze_metrics.side_effect = _fake_analyze_metrics

        result = alarm_context_module.analyze_alarm_context(
            res_id="3094",
            event_time="2026-04-20 18:39:19",
        )

        self.assertEqual(result["metricAnalysis"]["metricType"], "mysql")
        metrics_index = call_order.index("metrics")
        topology_index = call_order.index("topology")
        first_alarm_index = next(index for index, item in enumerate(call_order) if item.startswith("alarm:"))
        self.assertLess(metrics_index, first_alarm_index)
        self.assertLess(topology_index, first_alarm_index)
        self.assertEqual(call_order[first_alarm_index:], ["alarm:3094", "alarm:5002", "alarm:3094", "alarm:5002"])
        self.assertEqual(result["execution"]["status"], "success")
        self.assertEqual(result["execution"]["rootResource"]["ciType"], "mysql")
        self.assertEqual(result["execution"]["relatedAlarmsRecent"]["expectedQueries"], 2)
        self.assertEqual(result["execution"]["relatedAlarmsRecent"]["successIds"], ["3094", "5002"])
        self.assertEqual(result["execution"]["relatedAlarmsPrevious"]["successIds"], ["3094", "5002"])

    @patch("analyze_alarm_context._load_cmdb_client")
    @patch("analyze_alarm_context._fetch_root_resource_detail")
    @patch("analyze_alarm_context._build_topology_summary")
    @patch("analyze_alarm_context._query_alarms_for_res_id")
    @patch("get_metric_definitions.analyze_metrics")
    def test_analyze_alarm_context_blocks_metric_analysis_when_root_ci_type_missing(
        self,
        mock_analyze_metrics,
        mock_query_alarms_for_res_id,
        mock_build_topology_summary,
        mock_fetch_root_resource_detail,
        mock_load_cmdb_client,
    ):
        class _FakeClient:
            def _request_json(self, _path):
                return {"result": []}

        mock_load_cmdb_client.return_value = (_FakeClient(), None, "anonymous")
        mock_fetch_root_resource_detail.return_value = {
            "_id": 3094,
            "name": "db_unknown_001",
        }
        mock_build_topology_summary.return_value = {
            "rootResId": "3094",
            "rootResource": {
                "resId": "3094",
                "ciType": "",
                "ciTypeAlias": "",
                "name": "db_unknown_001",
                "isRoot": True,
            },
            "resourceCount": 1,
            "resourceIds": ["3094"],
            "ciTypeCounts": {},
            "resources": [],
        }
        mock_query_alarms_for_res_id.return_value = {
            "resId": "3094",
            "code": 200,
            "msg": "ok",
            "total": 0,
            "rows": [],
        }

        result = alarm_context_module.analyze_alarm_context(
            res_id="3094",
            event_time="2026-04-20 18:39:19",
        )

        mock_analyze_metrics.assert_not_called()
        self.assertEqual(result["execution"]["status"], "blocked")
        self.assertFalse(result["execution"]["metrics"]["metricTypeResolved"])
        self.assertEqual(result["execution"]["metrics"]["skippedReason"], "missing_root_ci_type")
        self.assertEqual(result["metricAnalysis"]["metricType"], "")
        self.assertEqual(result["metricAnalysis"]["metricDataResults"], [])

    @patch("analyze_alarm_context._load_cmdb_client")
    @patch("analyze_alarm_context._fetch_root_resource_detail")
    @patch("analyze_alarm_context._build_topology_summary")
    @patch("analyze_alarm_context._query_alarms_for_res_id")
    @patch("get_metric_definitions.analyze_metrics")
    def test_analyze_alarm_context_marks_partial_when_any_topology_alarm_query_fails(
        self,
        mock_analyze_metrics,
        mock_query_alarms_for_res_id,
        mock_build_topology_summary,
        mock_fetch_root_resource_detail,
        mock_load_cmdb_client,
    ):
        class _FakeClient:
            def _request_json(self, _path):
                return {"result": [{"_id": 5002, "ci_type": "docker", "name": "mysql-pod"}]}

        mock_load_cmdb_client.return_value = (_FakeClient(), None, "anonymous")
        mock_fetch_root_resource_detail.return_value = {
            "_id": 3094,
            "ci_type": "mysql",
            "ci_type_alias": "MySQL",
            "name": "db_mysql_001",
        }

        def _fake_build_topology_summary(root_res_id, resource_rows, root_resource=None):
            if resource_rows:
                return {
                    "rootResId": root_res_id,
                    "rootResource": {
                        "resId": "3094",
                        "ciType": "mysql",
                        "ciTypeAlias": "MySQL",
                        "name": "db_mysql_001",
                        "isRoot": True,
                    },
                    "resourceCount": 2,
                    "resourceIds": ["3094", "5002"],
                    "ciTypeCounts": {"docker": 1},
                    "resources": [],
                }
            return {
                "rootResId": root_res_id,
                "rootResource": {
                    "resId": "3094",
                    "ciType": "mysql",
                    "ciTypeAlias": "MySQL",
                    "name": "db_mysql_001",
                    "isRoot": True,
                },
                "resourceCount": 1,
                "resourceIds": ["3094"],
                "ciTypeCounts": {},
                "resources": [],
            }

        mock_build_topology_summary.side_effect = _fake_build_topology_summary
        mock_analyze_metrics.return_value = {
            "metricType": "mysql",
            "metricDataResults": [],
            "selectedMetrics": [],
        }

        def _fake_query_alarms_for_res_id(**kwargs):
            if kwargs["res_id"] == "5002" and kwargs["begin_time"] == "2026-04-20 18:29:19":
                return {"resId": "5002", "code": 500, "msg": "boom", "total": 0, "rows": []}
            return {"resId": kwargs["res_id"], "code": 200, "msg": "ok", "total": 0, "rows": []}

        mock_query_alarms_for_res_id.side_effect = _fake_query_alarms_for_res_id

        result = alarm_context_module.analyze_alarm_context(
            res_id="3094",
            event_time="2026-04-20 18:39:19",
        )

        self.assertEqual(result["execution"]["status"], "partial")
        self.assertEqual(result["execution"]["relatedAlarmsRecent"]["expectedQueries"], 2)
        self.assertEqual(result["execution"]["relatedAlarmsRecent"]["attemptedQueries"], 2)
        self.assertEqual(result["execution"]["relatedAlarmsRecent"]["failedIds"], ["5002"])
        self.assertEqual(result["execution"]["relatedAlarmsPrevious"]["failedIds"], [])


if __name__ == "__main__":
    unittest.main()
