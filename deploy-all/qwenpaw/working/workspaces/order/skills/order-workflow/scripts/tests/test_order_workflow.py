#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import unittest
from pathlib import Path
import sys
from unittest import mock


SKILL_ROOT = Path(__file__).resolve().parents[2]
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from runtime.client import OrderWorkflowClient, OrderWorkflowConfig
from runtime.formatters import (
    format_detail_markdown,
    format_list_markdown,
    format_stats_markdown,
)


class OrderWorkflowTests(unittest.TestCase):
    def test_build_list_params_uses_documented_query_keys(self) -> None:
        params = OrderWorkflowClient._build_list_params(
            page_num=2,
            page_size=20,
            begin_time="2026-04-23 00:00:00",
            end_time="2026-04-23 23:59:59",
        )
        self.assertEqual(
            params,
            {
                "pageNum": 2,
                "pageSize": 20,
                "params.beginTime": "2026-04-23 00:00:00",
                "params.endTime": "2026-04-23 23:59:59",
            },
        )

    def test_stats_markdown_renders_counts(self) -> None:
        markdown = format_stats_markdown(
            {
                "code": 200,
                "data": {
                    "inProgressCount": 3,
                    "finishedCount": 4,
                    "todoCount": 5,
                },
            }
        )
        self.assertIn("待处理：**3**", markdown)
        self.assertIn("已完成：**4**", markdown)
        self.assertIn("进行中：**5**", markdown)

    def test_list_markdown_renders_core_columns(self) -> None:
        markdown = format_list_markdown(
            {
                "total": 1,
                "rows": [
                    {
                        "taskId": "task-1",
                        "procDefName": "故障处置工单",
                        "procDefVersion": 7,
                        "startUserName": "xiaok",
                        "taskName": "人工处置",
                        "createTime": "2026-04-23 10:10:07",
                        "procVars": {
                            "title": "数据库锁异常",
                            "processStatus": "running",
                        },
                    }
                ],
            },
            title="待办工单",
        )
        self.assertIn("预览第 1 页 1 条", markdown)
        self.assertIn("| 序号 | 任务编号 | 流程名称 | 任务节点 | 流程版本 | 流程发起人 | 接收时间 |", markdown)
        self.assertIn("故障处置工单", markdown)
        self.assertIn("v7", markdown)
        self.assertIn("| 1 | task-1 | 故障处置工单 | 人工处置 | v7 | xiaok | 2026-04-23 10:10:07 |", markdown)
        self.assertIn("查看第 3 条", markdown)
        self.assertNotIn("### 完整编号", markdown)
        self.assertNotIn("portal-visualization", markdown)

    def test_finished_list_markdown_renders_page_columns(self) -> None:
        markdown = format_list_markdown(
            {
                "total": 1,
                "rows": [
                    {
                        "taskId": "task-2",
                        "procDefName": "故障处置工单",
                        "startUserName": "xiaok",
                        "taskName": "人工处置",
                        "createTime": "2026-04-23 10:25:37",
                        "finishTime": "2026-04-23 11:56:31",
                        "duration": "1小时30分54秒",
                    }
                ],
            },
            title="已办工单",
        )
        self.assertIn("| 序号 | 任务编号 | 流程名称 | 任务节点 | 流程发起人 | 接收时间 | 审批时间 | 耗时 |", markdown)
        self.assertIn("2026-04-23 11:56:31", markdown)
        self.assertIn("1小时30分54秒", markdown)
        self.assertIn("| 1 | task-2 | 故障处置工单 | 人工处置 | xiaok | 2026-04-23 10:25:37 | 2026-04-23 11:56:31 | 1小时30分54秒 |", markdown)
        self.assertNotIn("### 完整编号", markdown)
        self.assertNotIn("portal-visualization", markdown)

    def test_list_markdown_never_emits_portal_visualization(self) -> None:
        markdown = format_list_markdown(
            {
                "total": 1,
                "rows": [
                    {
                        "taskId": "task-3",
                        "procDefName": "故障处置工单",
                        "procDefVersion": 7,
                        "startUserName": "xiaok",
                        "taskName": "人工处置",
                        "createTime": "2026-04-23 10:10:07",
                    }
                ],
            },
            title="待办工单",
            lightweight=False,
        )
        self.assertIn("| 1 | task-3 | 故障处置工单 | 人工处置 | v7 | xiaok | 2026-04-23 10:10:07 |", markdown)
        self.assertNotIn("portal-visualization", markdown)

    def test_list_markdown_uses_global_index_for_later_pages(self) -> None:
        markdown = format_list_markdown(
            {
                "total": 31,
                "pageNum": 2,
                "pageSize": 10,
                "rows": [
                    {
                        "taskId": "task-11",
                        "procDefName": "故障处置工单",
                        "procDefVersion": 7,
                        "startUserName": "xiaok",
                        "taskName": "人工处置",
                        "createTime": "2026-04-23 10:10:07",
                    }
                ],
            },
            title="待办工单",
        )
        self.assertIn("| 11 | task-11 | 故障处置工单 | 人工处置 | v7 | xiaok | 2026-04-23 10:10:07 |", markdown)

    def test_detail_markdown_renders_light_preview(self) -> None:
        markdown = format_detail_markdown(
            {
                "data": {
                    "bpmnXml": """
<bpmn2:definitions>
  <bpmn2:process id="Process_1" name="故障处置工单">
    <bpmn2:startEvent id="StartEvent_1" name="开始"></bpmn2:startEvent>
    <bpmn2:userTask id="Activity_1" name="人工办理"></bpmn2:userTask>
    <bpmn2:endEvent id="Event_1" name="结束"></bpmn2:endEvent>
    <bpmn2:sequenceFlow id="Flow_1" sourceRef="StartEvent_1" targetRef="Activity_1" />
    <bpmn2:sequenceFlow id="Flow_2" sourceRef="Activity_1" targetRef="Event_1" />
  </bpmn2:process>
</bpmn2:definitions>
                    """,
                    "flowViewer": {
                        "finishedTaskSet": ["StartEvent_1"],
                        "unfinishedTaskSet": ["Activity_1"],
                    },
                    "processFormList": [
                        {
                            "title": "告警列表",
                            "formData": {
                                "alarmTitle": "云包异常",
                                "deviceName": "DKCZZ-HUAWEI-DCLEAF-1",
                                "manageIp": "172.27.34.15",
                            },
                            "formModel": {
                                "widgetList": [
                                    {
                                        "type": "input",
                                        "formItemFlag": True,
                                        "options": {"name": "alarmTitle", "label": "告警标题"},
                                    },
                                    {
                                        "type": "textarea",
                                        "formItemFlag": True,
                                        "options": {"name": "locationInfo", "label": "定位信息"},
                                    },
                                ]
                            },
                        }
                    ],
                    "historyProcNodeList": [
                        {
                            "activityId": "StartEvent_1",
                            "activityName": "开始",
                            "activityType": "startEvent",
                            "assigneeName": "xiaok",
                            "createTime": "2026-04-16 19:20:04",
                            "endTime": "2026-04-16 19:20:04",
                            "duration": "0秒",
                        },
                        {
                            "activityId": "Activity_1",
                            "activityName": "人工办理",
                            "activityType": "userTask",
                            "assigneeName": "xiaok",
                            "createTime": "2026-04-16 19:20:04",
                            "commentList": [{"fullMessage": "已接单"}],
                        },
                    ],
                }
            }
        )
        self.assertIn("### 表单信息预览", markdown)
        self.assertIn("| 字段 | 内容 |", markdown)
        self.assertIn("### 流转记录", markdown)
        self.assertIn("1. `开始`", markdown)
        self.assertIn("2. `人工办理`", markdown)
        self.assertIn("### 流程跟踪", markdown)
        self.assertIn("开始（已完成） -> 人工办理（处理中） -> 结束（未到达）", markdown)
        self.assertIn("查看完整表单信息", markdown)
        self.assertNotIn("portal-visualization", markdown)

    def test_detail_markdown_full_still_uses_markdown_only(self) -> None:
        markdown = format_detail_markdown(
            {
                "data": {
                    "processFormList": [
                        {
                            "title": "告警列表",
                            "formData": {"alarmTitle": "云包异常", "manageIp": "172.27.34.15"},
                            "formModel": {
                                "widgetList": [
                                    {
                                        "type": "input",
                                        "formItemFlag": True,
                                        "options": {"name": "alarmTitle", "label": "告警标题"},
                                    },
                                    {
                                        "type": "input",
                                        "formItemFlag": True,
                                        "options": {"name": "manageIp", "label": "设备IP"},
                                    },
                                ]
                            },
                        }
                    ],
                    "historyProcNodeList": [
                        {
                            "activityId": "StartEvent_1",
                            "activityName": "开始",
                            "activityType": "startEvent",
                            "assigneeName": "xiaok",
                            "createTime": "2026-04-16 19:20:04",
                            "endTime": "2026-04-16 19:20:04",
                            "duration": "0秒",
                        }
                    ],
                    "bpmnXml": "",
                    "flowViewer": {},
                }
            },
            lightweight=False,
        )
        self.assertIn("### 表单信息", markdown)
        self.assertIn("### 流转记录", markdown)
        self.assertIn("### 流程跟踪", markdown)
        self.assertNotIn("portal-visualization", markdown)

    def test_fetch_all_workorders_aggregates_pages(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://example.com",
                authorization="token",
            )
        )
        with mock.patch.object(
            client,
            "_request",
            side_effect=[
                {
                    "total": 3,
                    "rows": [
                        {"taskId": "task-1"},
                        {"taskId": "task-2"},
                    ],
                },
                {
                    "total": 3,
                    "rows": [
                        {"taskId": "task-3"},
                    ],
                },
            ],
        ) as request_mock:
            payload = client.list_todo_workorders(page_size=2, fetch_all=True)
        self.assertEqual([row["taskId"] for row in payload["rows"]], ["task-1", "task-2", "task-3"])
        self.assertTrue(payload["fetchedAll"])
        self.assertEqual(request_mock.call_count, 2)

    def test_client_uses_default_route_base_url(self) -> None:
        client = OrderWorkflowClient(
            OrderWorkflowConfig(
                base_url="http://192.168.130.51:30081",
                authorization="token",
            )
        )
        self.assertEqual(client.config.base_url, "http://192.168.130.51:30081")

    def test_config_falls_back_to_inoe_env(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {
                "INOE_API_BASE_URL": "http://192.168.130.51:30081/prod-api",
                "INOE_API_TOKEN": "inoe-token",
            },
            clear=True,
        ):
            config = OrderWorkflowConfig.from_env()
        self.assertEqual(config.base_url, "http://192.168.130.51:30081/prod-api")
        self.assertEqual(config.authorization, "inoe-token")

    def test_normalize_create_payload_accepts_lightweight_form_fields(self) -> None:
        payload = OrderWorkflowClient._normalize_create_payload(
            {
                "deviceName": "db_mysql_001",
                "manageIp": "10.43.150.186",
                "assetId": "3094",
                "suggestions": "数据库锁异常，需要人工排查长事务和阻塞链",
            }
        )
        self.assertEqual(payload["resId"], "3094")
        self.assertEqual(payload["alarm"]["deviceName"], "db_mysql_001")
        self.assertEqual(payload["alarm"]["manageIp"], "10.43.150.186")
        self.assertEqual(payload["alarm"]["assetId"], "3094")
        self.assertTrue(payload["chatId"])
        self.assertTrue(payload["alarm"]["alarmId"].startswith("alarm-"))
        self.assertIn("数据库锁异常", payload["alarm"]["title"])
        self.assertIn("人工排查", payload["analysis"]["summary"])
        self.assertGreaterEqual(len(payload["analysis"]["suggestions"]), 1)

    def test_normalize_create_payload_preserves_nested_fields(self) -> None:
        payload = OrderWorkflowClient._normalize_create_payload(
            {
                "chatId": "chat-1",
                "resId": "res-1",
                "metricType": "mysql",
                "alarm": {
                    "alarmId": "alarm-1",
                    "title": "数据库锁异常",
                    "visibleContent": "数据库锁异常（db_mysql_001 10.43.150.186）",
                    "deviceName": "db_mysql_001",
                    "manageIp": "10.43.150.186",
                    "assetId": "3094",
                    "level": "critical",
                    "status": "active",
                    "eventTime": "2026-04-23 20:00:00",
                },
                "analysis": {
                    "summary": "AI 无法直接止血，转人工处理",
                    "rootCause": "疑似长事务",
                    "suggestions": ["排查长事务", "检查阻塞链"],
                },
                "ticket": {
                    "title": "数据库锁异常人工处置",
                    "priority": "P1",
                    "category": "database-lock",
                    "source": "portal-fault-disposal",
                    "externalSystem": "manual-workorder",
                },
            }
        )
        self.assertEqual(payload["chatId"], "chat-1")
        self.assertEqual(payload["resId"], "res-1")
        self.assertEqual(payload["metricType"], "mysql")
        self.assertEqual(payload["alarm"]["alarmId"], "alarm-1")
        self.assertEqual(payload["alarm"]["eventTime"], "2026-04-23 20:00:00")
        self.assertEqual(payload["analysis"]["rootCause"], "疑似长事务")
        self.assertEqual(payload["analysis"]["suggestions"], ["排查长事务", "检查阻塞链"])
        self.assertEqual(payload["ticket"]["priority"], "P1")


if __name__ == "__main__":
    unittest.main()
