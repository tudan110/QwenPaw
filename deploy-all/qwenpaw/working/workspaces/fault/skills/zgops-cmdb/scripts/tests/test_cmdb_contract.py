"""Regression contracts for the current CMDB API and legacy responses."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cmdb_contract import (
    CmdbContractError,
    catalog_items,
    ci_detail,
    fetch_ci_pages,
    fetch_catalog_pages,
    fetch_relations,
    merge_cis,
)
from find_project import CmdbHttpClient


class CmdbContractTests(unittest.TestCase):
    def test_ci_detail_unwraps_current_legacy_and_bare_objects(self):
        ci = {"_id": 11, "_type": 61, "ci_type": "redis"}
        for payload in ({"ci_id": 11, "ci": ci}, {"result": ci}, ci):
            self.assertEqual(ci_detail(payload), ci)

    def test_business_failure_and_invalid_detail_are_not_empty_successes(self):
        for payload in (
            {"code": 403, "msg": "denied"},
            {"message": "not a CI"},
            {"ci": None},
            {"ci": {}},
        ):
            with self.subTest(payload=payload), self.assertRaises(
                CmdbContractError
            ):
                ci_detail(payload)

    def test_ci_attributes_are_not_mistaken_for_business_status_fields(self):
        ci = {"_id": 11, "ci_type": "custom", "code": 500, "success": False}
        self.assertEqual(ci_detail({"ci": ci}), ci)

    def test_catalog_handles_bare_groups_and_wrapped_types(self):
        rows = [{"id": 28, "name": "software-middleware"}]
        for payload in (rows, {"groups": rows}, {"data": rows}):
            self.assertEqual(catalog_items(payload, ("groups",)), rows)

    def test_catalog_pagination_validates_and_collects_every_model(self):
        def request(path):
            page = int(parse_qs(urlsplit(path).query)["page"][0])
            return {
                "ci_types": [{"id": page, "name": f"model-{page}"}],
                "numfound": 3,
            }

        rows = fetch_catalog_pages(request, "/api/v0.1/ci_types")
        self.assertEqual([row["id"] for row in rows], [1, 2, 3])
        with self.assertRaises(CmdbContractError):
            fetch_catalog_pages(
                lambda _: {"ci_types": [{"name": "missing-id"}]},
                "/api/v0.1/ci_types",
            )

    def test_relations_use_one_csv_level_parameter_and_return_all_layers(self):
        paths = []

        def request(path):
            paths.append(path)
            query = parse_qs(urlsplit(path).query)
            self.assertEqual(query["level"], ["1,2,3"])
            self.assertNotIn("reverse", query)
            return {
                "numfound": 53,
                "total": 53,
                "result": [{"_id": value} for value in range(1, 54)],
            }

        result = fetch_relations(request, 99)
        self.assertEqual(len(result), 53)
        self.assertEqual(len(paths), 1)
        self.assertEqual(result[0]["_query_directions"], ["forward"])

    def test_reverse_and_requested_layers_are_transmitted(self):
        def request(path):
            query = parse_qs(urlsplit(path).query)
            self.assertEqual(query["root_id"], ["11"])
            self.assertEqual(query["level"], ["1,2"])
            self.assertEqual(query["reverse"], ["1"])
            return {"numfound": 2, "result": [{"_id": 12}, {"_id": 13}]}

        result = fetch_relations(request, 11, reverse=1, levels=[1, 2, 1])
        self.assertEqual([row["_id"] for row in result], [12, 13])
        self.assertEqual(result[1]["_query_directions"], ["reverse"])

    def test_pagination_uses_numfound_not_page_total(self):
        pages = []

        def request(path):
            page = int(parse_qs(urlsplit(path).query)["page"][0])
            pages.append(page)
            return {
                "numfound": 3,
                "total": 1,
                "page": page,
                "result": [{"_id": page}],
            }

        rows = fetch_ci_pages(request, "/api/v0.1/ci/s", {"count": 1})
        self.assertEqual(pages, [1, 2, 3])
        self.assertEqual([row["_id"] for row in rows], [1, 2, 3])

    def test_overlapping_pages_are_deduplicated_without_stopping_early(self):
        def request(path):
            page = int(parse_qs(urlsplit(path).query)["page"][0])
            ids = {1: [1, 2], 2: [2, 3], 3: [4]}[page]
            return {"numfound": 4, "result": [{"_id": value} for value in ids]}

        result = fetch_ci_pages(request, "/api/v0.1/ci/s", {"count": 2})
        self.assertEqual([row["_id"] for row in result], [1, 2, 3, 4])

    def test_ignored_page_and_premature_empty_page_are_explicit_errors(self):
        for second in ([{"_id": 1}], []):
            calls = []

            def request(path):
                calls.append(path)
                return {
                    "numfound": 2,
                    "result": [{"_id": 1}] if len(calls) == 1 else second,
                }

            with self.subTest(second=second), self.assertRaises(
                CmdbContractError
            ):
                fetch_ci_pages(request, "/api/v0.1/ci/s", {"count": 1})

    def test_legacy_search_list_is_supported(self):
        result = fetch_ci_pages(
            lambda _: [{"_id": 1}],
            "/api/v0.1/ci/s",
            {"count": 10},
        )
        self.assertEqual(result, [{"_id": 1}])

    def test_projection_without_ci_objects_is_not_treated_as_no_resources(
        self,
    ):
        with self.assertRaises(CmdbContractError):
            fetch_ci_pages(
                lambda _: {"numfound": 2, "result": [None, None]},
                "/api/v0.1/ci/s",
                {"count": 10},
            )

    def test_empty_relations_remain_valid(self):
        self.assertEqual(
            fetch_relations(lambda _: {"numfound": 0, "result": []}, 11),
            [],
        )

    def test_directions_and_numeric_string_ids_merge_without_mutation(self):
        first = {"_id": 1, "_query_directions": ["forward"]}
        second = {"_id": "1", "name": "same", "_query_directions": ["reverse"]}
        result = merge_cis([first], [second])
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["_query_directions"], ["forward", "reverse"]
        )
        self.assertEqual(result[0]["name"], "same")
        self.assertEqual(first["_query_directions"], ["forward"])

    def test_invalid_reverse_level_count_and_total_are_rejected(self):
        for kwargs in (
            {"reverse": 2},
            {"reverse": True},
            {"reverse": 1.0},
            {"levels": []},
            {"levels": [0]},
            {"count": 0},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                fetch_relations(lambda _: {"result": []}, 11, **kwargs)
        with self.assertRaises(CmdbContractError):
            fetch_relations(lambda _: {"numfound": True, "result": []}, 11)

    def test_client_supports_an_explicit_cmdb_base_without_duplicate_prefix(
        self,
    ):
        client = CmdbHttpClient("http://gateway.example/cmdb", "fixture-token")
        self.assertEqual(client.base_url, "http://gateway.example/cmdb")


if __name__ == "__main__":
    unittest.main()
