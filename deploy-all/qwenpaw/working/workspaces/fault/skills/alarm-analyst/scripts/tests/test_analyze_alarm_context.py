import unittest

from analyze_alarm_context import (
    _build_alarm_comparison_summary,
    _build_topology_summary,
    _collect_related_resource_ids,
    _infer_correlation_findings,
)


class AnalyzeAlarmContextTests(unittest.TestCase):
    def test_collect_related_resource_ids_deduplicates_and_keeps_root_first(self):
        resource_rows = [
            {"_id": 4001, "ci_type": "mysql", "name": "mysql-main"},
            {"_id": 5002, "ci_type": "docker", "name": "mysql-pod"},
            {"id": "5002", "ci_type": "docker", "name": "mysql-pod-dup"},
            {"_id": 6003, "ci_type": "vserver", "name": "node-1"},
        ]

        result = _collect_related_resource_ids(root_res_id="4001", resource_rows=resource_rows)

        self.assertEqual(result, ["4001", "5002", "6003"])

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
