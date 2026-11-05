import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import inoe_cmdb_stats as stats


def _catalog():
    models = [
        {"id": 61, "name": "redis", "alias": "Redis"},
        {"id": 36, "name": "nginx", "alias": "Nginx"},
        {"id": 77, "name": "mysql", "alias": "mySQL"},
        {"id": 142, "name": "Contract", "alias": "合同"},
    ]
    return {
        "groups": [
            {"id": 28, "name": "软件服务-中间件", "ci_types": models[:2]},
            {"id": 29, "name": "软件服务-数据库", "ci_types": [models[2]]},
            {"id": 36, "name": "合同", "ci_types": [models[3]]},
        ],
        "ci_types": models,
    }


class InoeCmdbStatsTest(unittest.TestCase):
    def setUp(self):
        self.catalog_patch = patch.object(
            stats, "query_type_catalog", return_value=_catalog()
        )
        self.catalog_patch.start()

    def tearDown(self):
        self.catalog_patch.stop()

    def test_categories_have_no_fixed_environment_ids(self):
        for category in ("中间件", "数据库", "服务器", "操作系统"):
            self.assertIsNone(
                stats.normalize_resource(category, None)["type_id"]
            )

    def test_renamed_middleware_and_database_groups_resolve_from_metadata(
        self,
    ):
        self.assertEqual(
            stats.resolve_resource("middleware", None)["type_id"], "28"
        )
        self.assertEqual(
            stats.resolve_resource("database", None)["type_id"], "29"
        )
        self.assertEqual(
            stats.resolve_resource("中间件", None)["type_kind"], "group"
        )

    def test_concrete_model_resolves_separately(self):
        resource = stats.resolve_resource("mysql", None)
        self.assertEqual(resource["type_id"], "77")
        self.assertEqual(resource["type_kind"], "model")

    def test_id_collision_requires_an_explicit_kind(self):
        with self.assertRaises(ValueError):
            stats.resolve_resource("unused", "36")
        self.assertEqual(
            stats.resolve_resource("unused", "36", type_kind="model")["label"],
            "Nginx",
        )
        self.assertEqual(
            stats.resolve_resource("unused", "36", type_kind="group")["label"],
            "合同",
        )

    def test_unknown_category_does_not_guess_a_group_id(self):
        with self.assertRaises(ValueError):
            stats.resolve_resource("服务器", None)

    def test_vendor_aliases(self):
        self.assertEqual(stats.normalize_attr("制造商"), "vendor")
        self.assertEqual(stats.normalize_attr("厂商"), "vendor")

    def test_group_count_uses_group_id(self):
        with patch.object(
            stats,
            "request_get",
            return_value={"code": 200, "data": {"total": 7}},
        ) as request:
            result = stats.query_stat("count", "middleware", None, None)
        self.assertEqual(result["code"], 200)
        self.assertEqual(
            request.call_args.args, (stats.stat_path("count"), {"type": "28"})
        )

    def test_concrete_group_request_uses_child_endpoint_to_avoid_id_collision(
        self,
    ):
        with patch.object(
            stats,
            "request_get",
            return_value={"code": 200, "data": {"total": 1}},
        ) as request:
            result = stats.query_stat("group", "nginx", None, None)
        self.assertEqual(result["_query"]["type_kind"], "model")
        self.assertEqual(
            request.call_args.args, (stats.stat_path("child"), {"type": "36"})
        )

    def test_group_attribute_statistics_query_each_model_not_the_group_id(
        self,
    ):
        def request(path, params):
            self.assertEqual(path, stats.stat_path("child-group"))
            self.assertEqual(params["attr"], "vendor")
            value = 2 if params["type"] == "61" else 3
            return {
                "code": 200,
                "data": [
                    {
                        "resourceClass": "vendor-a",
                        "resourceType": "mixed",
                        "total": value,
                        "normalCount": value,
                    }
                ],
            }

        with patch.object(stats, "request_get", side_effect=request) as calls:
            result = stats.query_stat("group", "middleware", None, "vendor")
        self.assertEqual(result["data"][0]["total"], 5)
        self.assertEqual(result["_query"]["model_ids"], ["61", "36"])
        self.assertEqual(calls.call_count, 2)

    def test_pure_attribute_counts_are_aggregated_and_charted_as_counts(self):
        with patch.object(
            stats,
            "request_get",
            side_effect=[
                {"code": 200, "data": [{"type": "vendor-a", "count": 2}]},
                {"code": 200, "data": [{"type": "vendor-a", "count": 3}]},
            ],
        ):
            result = stats.query_stat(
                "group-attr", "middleware", None, "vendor"
            )
        self.assertEqual(result["data"], [{"type": "vendor-a", "count": 5}])
        self.assertEqual(
            stats.build_chart("test", result["data"])["series"][0]["data"], [5]
        )
        self.assertIn("| 分组 | 资源数量 |", stats.render_markdown(result))

    def test_wrong_kind_and_missing_attribute_fail_before_statistics_requests(
        self,
    ):
        for args in (
            ("child", "middleware", None, None),
            ("child-group", "mysql", None, None),
        ):
            with patch.object(stats, "request_get") as request:
                result = stats.query_stat(*args)
            self.assertEqual(result["code"], 400)
            request.assert_not_called()

    def test_credential_attributes_are_not_used_as_group_labels(self):
        with patch.object(stats, "request_get") as request:
            result = stats.query_stat(
                "group-attr", "redis", None, "bearer_token"
            )
        self.assertEqual(result["code"], 400)
        request.assert_not_called()

    def test_metadata_error_does_not_fall_back_to_old_ids(self):
        self.catalog_patch.stop()
        with patch.object(
            stats, "request_get", return_value={"code": 401, "msg": "denied"}
        ) as request:
            result = stats.query_stat("count", "middleware", None, None)
        self.assertEqual(result["code"], 401)
        self.assertEqual(request.call_count, 1)

    def test_group_member_error_is_explicit_and_stops_fanout(self):
        with patch.object(
            stats,
            "request_get",
            side_effect=[
                {"code": 200, "data": []},
                {"code": 500, "msg": "member failed"},
            ],
        ):
            result = stats.query_stat("group", "middleware", None, "vendor")
        self.assertEqual(result["code"], 500)
        self.assertIsNone(result["data"])

    def test_disabled_metadata_requires_explicit_id_and_kind(self):
        self.assertEqual(
            stats.query_stat(
                "count", "middleware", None, None, dynamic_type=False
            )["code"],
            400,
        )
        with patch.object(
            stats,
            "request_get",
            return_value={"code": 200, "data": {"total": 7}},
        ):
            result = stats.query_stat(
                "count",
                "unused",
                "28",
                None,
                dynamic_type=False,
                type_kind="group",
            )
        self.assertEqual(result["code"], 200)

    def test_model_catalog_reads_all_pages_even_with_small_pages(self):
        self.catalog_patch.stop()

        def request(path, params):
            if path == stats.ci_type_groups_path():
                return {"code": 200, "data": []}
            rows = _catalog()["ci_types"]
            return {
                "ci_types": rows[:2] if params["page"] == 1 else rows[2:],
                "numfound": 4,
            }

        with patch.object(stats, "request_get", side_effect=request):
            result = stats.query_type_catalog()
        self.assertEqual(len(result["ci_types"]), 4)

    def test_empty_attribute_results_are_not_reported_as_zero_resources(self):
        with patch.object(
            stats, "request_get", return_value={"code": 200, "data": []}
        ):
            result = stats.query_stat("group-attr", "mysql", None, "vendor")
        self.assertEqual(result["code"], 200)
        self.assertIn("不能据此判断资源数量为零", stats.render_markdown(result))

    def test_invalid_statistic_shape_is_not_rendered_as_zero(self):
        for data in ([None], {"unexpected": 1}, {"total": None}):
            with patch.object(
                stats, "request_get", return_value={"code": 200, "data": data}
            ):
                result = stats.query_stat("child", "mysql", None, None)
            self.assertEqual(result["code"], 500)


if __name__ == "__main__":
    unittest.main()
