import unittest

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


if __name__ == "__main__":
    unittest.main()
