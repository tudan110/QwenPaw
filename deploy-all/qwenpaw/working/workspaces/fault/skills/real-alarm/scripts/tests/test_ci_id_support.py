import json
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from analyze_alarms import validate_args
from get_alarms import execute
from utils.alarm_analyzer import apply_filters, analyze_by_mode
from utils.alarm_normalizer import build_alarm_rows, normalize_alarms


class CiIdSupportTests(unittest.TestCase):
    @patch("get_alarms.requests.post")
    def test_execute_includes_ne_id_in_request_payload(self, mock_post):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"code": 200, "msg": "ok", "total": 0, "rows": []}
        mock_post.return_value = response

        result = execute(token="token", ci_id="18")

        self.assertEqual(result["code"], 200)
        self.assertEqual(mock_post.call_args.kwargs["json"]["neId"], 18)

    @patch("get_alarms.subprocess.run")
    @patch("get_alarms.requests.post", side_effect=requests.ConnectionError("No route to host"))
    def test_execute_falls_back_to_curl_when_requests_connection_fails(self, _mock_post, mock_run):
        def _fake_run(args, capture_output, text, encoding, timeout, check):
            body_path = args[args.index("-o") + 1]
            Path(body_path).write_text(
                json.dumps({"code": 200, "msg": "ok", "total": 1, "rows": [{"alarmtitle": "A"}]}),
                encoding="utf-8",
            )
            return SimpleNamespace(returncode=0, stdout="200", stderr="")

        mock_run.side_effect = _fake_run

        result = execute(token="token", ci_id="18")

        self.assertEqual(result["code"], 200)
        self.assertEqual(result["total"], 1)
        curl_payload = json.loads(mock_run.call_args.args[0][mock_run.call_args.args[0].index("--data-binary") + 1])
        self.assertEqual(curl_payload["neId"], 18)

    def test_apply_filters_supports_ci_id(self):
        alarms = [
            {"alarmtitle": "A", "neId": 18},
            {"alarmtitle": "B", "neId": 19},
            {"alarmtitle": "C", "ciId": "18"},
            {"alarmtitle": "D", "devId": "18"},
        ]

        filtered = apply_filters(alarms, ci_id="18")

        self.assertEqual([alarm["alarmtitle"] for alarm in filtered], ["A", "C", "D"])

    def test_build_alarm_rows_uses_dev_id_as_ci_id_fallback(self):
        rows = build_alarm_rows(
            normalize_alarms(
                [
                    {
                        "alarmtitle": "A",
                        "alarmseverity": "1",
                        "alarmstatus": "1",
                        "devId": "18",
                    }
                ]
            )
        )

        self.assertEqual(rows[0]["neId"], "18")

    def test_search_mode_preview_uses_dev_id_as_ci_id_fallback(self):
        result = analyze_by_mode(
            mode="search",
            alarms=normalize_alarms(
                [
                    {
                        "alarmtitle": "A",
                        "alarmseverity": "1",
                        "alarmstatus": "1",
                        "devId": "18",
                    }
                ]
            ),
            include_alarms=True,
        )

        self.assertEqual(result["rows"][0]["neId"], "18")

    def test_search_mode_accepts_ci_id_as_only_filter(self):
        args = Namespace(
            fetch_page_size=100,
            top_n=10,
            output="json",
            mode="search",
            keyword="",
            severity="",
            device_name="",
            manage_ip="",
            speciality="",
            region="",
            ci_id="18",
        )

        self.assertIsNone(validate_args(args))


if __name__ == "__main__":
    unittest.main()
