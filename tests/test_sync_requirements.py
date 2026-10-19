import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openpyxl import Workbook

import tdxoperations as tdx
from Requirements import requirementswebcalls
from excel_parser import ROOT_SPEC_ID, RequirementNode, parse_requirement_structure
from sync_requirements import (
    _expected_chapter_relations,
    _detect_live_relation_drift,
    _revise_nodes,
    plan_changes,
    persist_state,
    reconcile_relations,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class RequirementWorkbookTests(unittest.TestCase):
    def test_persist_state_updates_root_specification_revision(self):
        class FakeCursor:
            def __init__(self):
                self.executemany_calls = []
                self.execute_calls = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def executemany(self, query, values):
                self.executemany_calls.append((query, list(values)))

            def execute(self, query, values=None):
                self.execute_calls.append((query, values))

        class FakeConnection:
            def __init__(self):
                self.fake_cursor = FakeCursor()
                self.committed = False

            def cursor(self):
                return self.fake_cursor

            def commit(self):
                self.committed = True

        conn = FakeConnection()
        nodes = {
            "C1": RequirementNode("C1", "Chapter", "Chapter"),
        }
        db_nodes = {
            ROOT_SPEC_ID: {
                "3dxid": "spec-old",
                "content": "Spec",
                "object_type": "Requirement Specification",
            }
        }
        active_ids = {
            ROOT_SPEC_ID: "spec-revised",
            "C1": "chapter-current",
        }
        edges = {(ROOT_SPEC_ID, "C1")}
        connection_ids = {(ROOT_SPEC_ID, "C1"): "spec-chapter-usage"}

        persist_state(
            conn,
            nodes,
            edges,
            active_ids,
            connection_ids,
            db_nodes,
        )

        persisted_mappings = conn.fake_cursor.executemany_calls[0][1]
        self.assertIn(
            (
                ROOT_SPEC_ID,
                "spec-revised",
                "Spec",
                "Requirement Specification",
            ),
            persisted_mappings,
        )
        self.assertTrue(conn.committed)

    def test_chapter_expansion_parses_compact_and_namespaced_usage_types(self):
        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {
                    "member": [
                        {
                            "id": "req-usage-1",
                            "type": "Specification Structure",
                            "Path": ["chapter", "req-usage-1", "req-1"],
                        },
                        {
                            "id": "req-1",
                            "type": "Requirement",
                            "Path": ["chapter", "req-usage-1", "req-1"],
                        },
                        {
                            "id": "sub-usage-1",
                            "type": "Sub Requirement Usage",
                            "Path": [
                                "chapter",
                                "req-usage-1",
                                "req-1",
                                "sub-usage-1",
                                "req-2",
                            ],
                        },
                        {
                            "id": "req-2",
                            "type": "Requirement",
                            "Path": [
                                "chapter",
                                "req-usage-1",
                                "req-1",
                                "sub-usage-1",
                                "req-2",
                            ],
                        },
                        {
                            "id": "chapter-usage-1",
                            "type": "ChapterUsage",
                            "Path": ["chapter", "chapter-usage-1", "nested-chapter"],
                        },
                    ]
                }

        previous_token = tdx.ENO_CSRF_TOKEN
        tdx.ENO_CSRF_TOKEN = "test-token"
        try:
            structure = tdx._get_expanded_structure(
                "chapter",
                lambda *_args: FakeResponse(),
            )
        finally:
            tdx.ENO_CSRF_TOKEN = previous_token

        self.assertEqual(
            structure,
            {
                ("chapter", "req-1"): {
                    "connectionID": "req-usage-1",
                    "connectionIDs": ["req-usage-1"],
                    "type": "chapter-req",
                    "usageType": "Specification Structure",
                },
                ("req-1", "req-2"): {
                    "connectionID": "sub-usage-1",
                    "connectionIDs": ["sub-usage-1"],
                    "type": "req-req",
                    "usageType": "Sub Requirement Usage",
                },
                ("chapter", "nested-chapter"): {
                    "connectionID": "chapter-usage-1",
                    "connectionIDs": ["chapter-usage-1"],
                    "type": "chapter-req",
                    "usageType": "ChapterUsage",
                },
            },
        )

    def test_expansion_preserves_multiple_usage_ids_for_duplicate_child_links(self):
        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                paths = [
                    ("usage-1", ["chapter", "usage-1", "requirement"]),
                    ("usage-2", ["chapter", "usage-2", "requirement"]),
                ]
                members = []
                for usage_id, path in paths:
                    members.extend(
                        [
                            {
                                "id": usage_id,
                                "type": "Sub Requirement Usage",
                                "Path": path,
                            },
                            {
                                "id": "requirement",
                                "type": "Requirement",
                                "Path": path,
                            },
                        ]
                    )
                return {"member": members}

        previous_token = tdx.ENO_CSRF_TOKEN
        tdx.ENO_CSRF_TOKEN = "test-token"
        try:
            structure = tdx._get_expanded_structure(
                "chapter",
                lambda *_args: FakeResponse(),
            )
        finally:
            tdx.ENO_CSRF_TOKEN = previous_token

        self.assertEqual(
            structure[("chapter", "requirement")]["connectionIDs"],
            ["usage-1", "usage-2"],
        )

    def test_expansion_retries_successful_but_incomplete_index_results(self):
        class FakeResponse:
            status_code = 200
            text = ""

            def __init__(self, members):
                self.members = members

            def json(self):
                return {"member": self.members}

        complete_members = [
            {
                "id": "usage-1",
                "type": "Specification Structure",
                "Path": ["chapter", "usage-1", "requirement"],
            },
            {
                "id": "requirement",
                "type": "Requirement",
                "Path": ["chapter", "usage-1", "requirement"],
            },
        ]
        responses = iter([FakeResponse([]), FakeResponse(complete_members)])
        previous_token = tdx.ENO_CSRF_TOKEN
        tdx.ENO_CSRF_TOKEN = "test-token"
        try:
            with patch.object(tdx.time, "sleep") as sleep:
                structure = tdx._get_expanded_structure(
                    "chapter",
                    lambda *_args: next(responses),
                    expected_relations={("chapter", "requirement")},
                )
        finally:
            tdx.ENO_CSRF_TOKEN = previous_token

        self.assertIn(("chapter", "requirement"), structure)
        sleep.assert_called_once_with(10)

    def test_incomplete_expansion_fails_without_returning_partial_tree(self):
        class FakeResponse:
            status_code = 200
            text = ""

            def json(self):
                return {"member": []}

        previous_token = tdx.ENO_CSRF_TOKEN
        tdx.ENO_CSRF_TOKEN = "test-token"
        try:
            with patch.object(tdx.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "refusing to reconcile"):
                    tdx._get_expanded_structure(
                        "chapter",
                        lambda *_args: FakeResponse(),
                        expected_relations={("chapter", "old-requirement")},
                    )
        finally:
            tdx.ENO_CSRF_TOKEN = previous_token

    def test_expected_chapter_edges_include_descendants_at_recorded_revisions(self):
        db_nodes = {
            "__ROOT_SPEC__": {"3dxid": "spec-old"},
            "C1": {"3dxid": "chapter-old"},
            "R1": {"3dxid": "requirement-old"},
            "R2": {"3dxid": "subrequirement-old"},
        }
        db_edges = {
            ("__ROOT_SPEC__", "C1"): "spec-use",
            ("C1", "R1"): "chapter-use-old",
            ("R1", "R2"): "requirement-use-old",
        }

        expected = _expected_chapter_relations(
            "C1",
            {"C1": "chapter-new"},
            db_nodes,
            db_edges,
        )
        self.assertEqual(
            expected,
            {
                ("chapter-new", "requirement-old"),
                ("requirement-old", "subrequirement-old"),
            },
        )

    def test_detects_stale_subrequirement_links_on_no_change_sync(self):
        nodes = {
            "C1": RequirementNode("C1", "Chapter", "Chapter"),
            "R1": RequirementNode("R1", "Requirement", "Parent"),
            "R2": RequirementNode("R2", "Requirement", "Current child"),
        }
        edges = {(ROOT_SPEC_ID, "C1"), ("C1", "R1"), ("R1", "R2")}
        db_nodes = {
            ROOT_SPEC_ID: {
                "3dxid": "spec-current",
                "content": "Spec",
                "object_type": "Requirement Specification",
            },
            "C1": {
                "3dxid": "chapter-current",
                "content": "Chapter",
                "object_type": "Chapter",
            },
            "R1": {
                "3dxid": "parent-current",
                "content": "Parent",
                "object_type": "Requirement",
            },
            "R2": {
                "3dxid": "child-current",
                "content": "Current child",
                "object_type": "Requirement",
            },
        }
        db_edges = {
            (ROOT_SPEC_ID, "C1"): "spec-usage",
            ("C1", "R1"): "chapter-usage",
            ("R1", "R2"): "current-child-usage",
        }

        class FakeTdx:
            def get_specification_structure(self, _spec_id, expected_relations=None):
                return {
                    ("spec-current", "chapter-current"): {
                        "connectionID": "spec-usage",
                        "usageType": "Chapter Usage",
                    }
                }

            def get_parent_structure(self, _chapter_id, expected_relations=None):
                return {
                    ("chapter-current", "parent-current"): {
                        "connectionID": "chapter-usage",
                        "usageType": "Specification Structure",
                    },
                    ("parent-current", "child-old"): {
                        "connectionID": "old-child-usage",
                        "usageType": "Sub Requirement Usage",
                    },
                    ("parent-current", "child-current"): {
                        "connectionID": "current-child-usage",
                        "usageType": "Sub Requirement Usage",
                    },
                }

        drift = _detect_live_relation_drift(
            nodes, edges, db_nodes, db_edges, FakeTdx()
        )

        self.assertEqual(drift, {"R1"})

    def test_detects_duplicate_links_for_same_child_revision(self):
        nodes = {
            "C1": RequirementNode("C1", "Chapter", "Chapter"),
            "R1": RequirementNode("R1", "Requirement", "Parent"),
            "R2": RequirementNode("R2", "Requirement", "Child"),
        }
        edges = {(ROOT_SPEC_ID, "C1"), ("C1", "R1"), ("R1", "R2")}
        db_nodes = {
            ROOT_SPEC_ID: {
                "3dxid": "spec",
                "content": "Spec",
                "object_type": "Requirement Specification",
            },
            "C1": {
                "3dxid": "chapter",
                "content": "Chapter",
                "object_type": "Chapter",
            },
            "R1": {
                "3dxid": "parent",
                "content": "Parent",
                "object_type": "Requirement",
            },
            "R2": {
                "3dxid": "child",
                "content": "Child",
                "object_type": "Requirement",
            },
        }
        db_edges = {
            (ROOT_SPEC_ID, "C1"): "spec-usage",
            ("C1", "R1"): "chapter-usage",
            ("R1", "R2"): "subreq-usage",
        }

        class FakeTdx:
            def get_specification_structure(self, _spec_id, expected_relations=None):
                return {
                    ("spec", "chapter"): {
                        "connectionID": "spec-usage",
                    }
                }

            def get_parent_structure(self, _chapter_id, expected_relations=None):
                return {
                    ("chapter", "parent"): {
                        "connectionID": "chapter-usage",
                    },
                    ("parent", "child"): {
                        "connectionID": "subreq-usage-1",
                        "connectionIDs": ["subreq-usage-1", "subreq-usage-2"],
                    },
                }

        self.assertEqual(
            _detect_live_relation_drift(
                nodes, edges, db_nodes, db_edges, FakeTdx()
            ),
            {"R1"},
        )

    def test_chapter_requirement_relationship_uses_requirement_usage_endpoint(self):
        class FakeResponse:
            ok = True

        class FakeSession:
            def __init__(self):
                self.post_args = None
                self.delete_args = None

            def post(self, url, **kwargs):
                self.post_args = (url, kwargs)
                return FakeResponse()

            def delete(self, url, **kwargs):
                self.delete_args = (url, kwargs)
                return FakeResponse()

        fake_session = FakeSession()
        with patch.object(requirementswebcalls, "FullURL", side_effect=lambda path: path):
            requirementswebcalls.assign_child_chapter_req(
                fake_session, "csrf", "chapter-1", ["requirement-1"]
            )
            requirementswebcalls.delete_child_chapter_req(
                fake_session, "csrf", "chapter-1", "usage-1"
            )

        self.assertEqual(
            fake_session.post_args[0],
            "/dsreq:Chapter/chapter-1/dsreq:RequirementUsage",
        )
        self.assertEqual(
            fake_session.post_args[1]["params"]["$mask"],
            "dsreq:RequirementUsageMask.Filterable",
        )
        self.assertEqual(
            fake_session.delete_args[0],
            "/dsreq:Chapter/chapter-1/dsreq:RequirementUsage/usage-1",
        )

    def test_sample_workbook_builds_typed_hierarchy(self):
        nodes, edges = parse_requirement_structure(
            REPOSITORY_ROOT / "requirements_v1.xlsx"
        )

        self.assertEqual(nodes["A"].object_type, "Chapter")
        self.assertEqual(nodes["A1"].object_type, "Requirement")
        self.assertIn((ROOT_SPEC_ID, "A"), edges)
        self.assertIn(("A", "A1"), edges)
        self.assertIn(("A3", "A3a"), edges)
        self.assertEqual(len(nodes), 12)

    def test_rejects_top_level_requirement(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["internalid", "content", "parent_ids", "type"])
            sheet.append(["R1", "description", "", "R"])
            workbook.save(path)

            with self.assertRaisesRegex(ValueError, "Top-level requirement"):
                parse_requirement_structure(path)

    def test_supports_nested_chapters_and_rejects_chapter_under_requirement(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nested.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.append(["internalid", "content", "parent_ids", "type"])
            sheet.append(["C1", "Chapter 1", "", "C"])
            sheet.append(["C2", "Chapter 2", "C1", "C"])
            sheet.append(["R1", "Description 1", "C2", "R"])
            sheet.append(["R2", "Description 2", "R1", ""])
            workbook.save(path)

            nodes, edges = parse_requirement_structure(path)
            self.assertEqual(nodes["C2"].object_type, "Chapter")
            self.assertIn(("C1", "C2"), edges)
            self.assertIn(("R1", "R2"), edges)

            sheet.append(["C3", "Invalid Chapter", "R1", "C"])
            workbook.save(path)
            with self.assertRaisesRegex(ValueError, "cannot contain chapter"):
                parse_requirement_structure(path)

    def test_revision_plan_propagates_to_specification(self):
        nodes = {
            "C1": RequirementNode("C1", "Chapter", "Chapter"),
            "R1": RequirementNode("R1", "Requirement", "Updated"),
        }
        edges = {(ROOT_SPEC_ID, "C1"), ("C1", "R1")}
        db_nodes = {
            ROOT_SPEC_ID: {
                "3dxid": "spec-old",
                "content": "Spec",
                "object_type": "Requirement Specification",
            },
            "C1": {"3dxid": "chapter-old", "content": "Chapter", "object_type": "Chapter"},
            "R1": {
                "3dxid": "req-old",
                "content": "Original",
                "object_type": "Requirement",
            },
        }
        db_edges = {
            (ROOT_SPEC_ID, "C1"): "spec-usage",
            ("C1", "R1"): "chapter-usage",
        }

        to_create, direct_changes, to_revise = plan_changes(
            nodes, edges, db_nodes, db_edges
        )

        self.assertEqual(to_create, set())
        self.assertEqual(direct_changes, {"R1"})
        self.assertEqual(to_revise, {ROOT_SPEC_ID, "C1", "R1"})

    def test_new_specification_is_created_not_revised_for_initial_chapter_links(self):
        nodes = {"C1": RequirementNode("C1", "Chapter", "Chapter")}
        edges = {(ROOT_SPEC_ID, "C1")}
        db_nodes = {
            ROOT_SPEC_ID: {
                "3dxid": "spec-new",
                "content": "Spec",
                "object_type": "Requirement Specification",
            }
        }

        to_create, _, to_revise = plan_changes(
            nodes, edges, db_nodes, {}, root_spec_is_new=True
        )

        self.assertEqual(to_create, {"C1"})
        self.assertNotIn(ROOT_SPEC_ID, to_revise)

    def test_revises_each_hierarchy_level_separately(self):
        class FakeTdx:
            def __init__(self):
                self.calls = []

            def revise_several_reqs(self, ids, changes, object_type):
                self.calls.append((list(ids), object_type))
                return {old_id: f"{old_id}-new" for old_id in ids}

        nodes = {
            "C1": RequirementNode("C1", "Chapter", "Chapter"),
            "R1": RequirementNode("R1", "Requirement", "One"),
            "R2": RequirementNode("R2", "Requirement", "Two"),
        }
        db_nodes = {
            ROOT_SPEC_ID: {"3dxid": "spec", "content": "", "object_type": "Requirement Specification"},
            "C1": {"3dxid": "chapter", "content": "Chapter", "object_type": "Chapter"},
            "R1": {"3dxid": "req-1", "content": "One", "object_type": "Requirement"},
            "R2": {"3dxid": "req-2", "content": "Two", "object_type": "Requirement"},
        }
        to_revise = {ROOT_SPEC_ID, "C1", "R1", "R2"}
        active_ids = {key: value["3dxid"] for key, value in db_nodes.items()}
        fake_tdx = FakeTdx()

        _revise_nodes(
            nodes,
            db_nodes,
            to_revise,
            active_ids,
            {"C1": 0, "R1": 1, "R2": 2},
            fake_tdx,
        )

        self.assertEqual(
            fake_tdx.calls,
            [
                (["req-2"], "Requirement"),
                (["req-1"], "Requirement"),
                (["chapter"], "Chapter"),
                (["spec"], "Requirement Specification"),
            ],
        )
        self.assertEqual(active_ids["R2"], "req-2-new")

    def test_reconstructs_usage_ids_after_parent_and_child_revisions(self):
        class FakeTdx:
            def __init__(self):
                self.deleted = []
                self.added = []
                self.chapter_expansions = 0

            def get_specification_structure(
                self, _specification_id, expected_relations=None
            ):
                return {
                    ("spec-new", "chapter-old"): {
                        "connectionID": "old-spec-usage",
                        "usageType": "Chapter Usage",
                    }
                }

            def get_parent_structure(self, _chapter_id, expected_relations=None):
                self.chapter_expansions += 1
                structure = {
                    ("req-old", "subreq-old"): {
                        "connectionID": "old-subrequirement-usage",
                        "usageType": "Sub Requirement Usage",
                    },
                }
                if self.chapter_expansions == 1:
                    structure[("chapter-old", "req-old")] = {
                        "connectionID": "old-chapter-usage",
                        "usageType": "Requirement Usage",
                    }
                else:
                    structure.update(
                        {
                            ("chapter-new", "req-new"): {
                                "connectionID": "new-chapter-usage",
                                "usageType": "Requirement Usage",
                            },
                            ("req-new", "subreq-old"): {
                                "connectionID": "active-stale-subrequirement-usage",
                                "usageType": "Sub Requirement Usage",
                            },
                        }
                    )
                return structure

            def get_requirement_structure(self, _requirement_id):
                raise AssertionError("Requirement expansion must not be called")

            def delete_several_relations_spec_chapter(self, parents, relations):
                self.deleted.append((parents[0], relations[0]))

            def delete_several_relations_chapter_req(self, parents, relations):
                self.deleted.append((parents[0], relations[0]))

            def delete_several_relations(self, parents, relations):
                self.deleted.append((parents[0], relations[0]))

            def relate_several_elements_spec_chapter(self, parents, children):
                self.added.append((parents[0], children[0][0]))
                return {parents[0]: {children[0][0]: "new-spec-usage"}}

            def relate_several_elements_chapter_req(self, parents, children):
                self.added.append((parents[0], children[0][0]))
                return {parents[0]: {children[0][0]: "new-chapter-usage"}}

            def relate_several_elements_req_req(self, parents, children):
                self.added.append((parents[0], children[0][0]))
                return {parents[0]: {children[0][0]: "new-subrequirement-usage"}}

        nodes = {
            "C1": RequirementNode("C1", "Chapter", "Chapter"),
            "R1": RequirementNode("R1", "Requirement", "Description"),
            "R2": RequirementNode("R2", "Requirement", "Sub-description"),
        }
        edges = {(ROOT_SPEC_ID, "C1"), ("C1", "R1"), ("R1", "R2")}
        db_nodes = {
            ROOT_SPEC_ID: {
                "3dxid": "spec-old",
                "content": "Spec",
                "object_type": "Requirement Specification",
            },
            "C1": {"3dxid": "chapter-old", "content": "Chapter", "object_type": "Chapter"},
            "R1": {
                "3dxid": "req-old",
                "content": "Description",
                "object_type": "Requirement",
            },
            "R2": {
                "3dxid": "subreq-old",
                "content": "Sub-description",
                "object_type": "Requirement",
            },
        }
        db_edges = {
            (ROOT_SPEC_ID, "C1"): "old-spec-usage",
            ("C1", "R1"): "old-chapter-usage",
            ("R1", "R2"): "old-subrequirement-usage",
        }
        active_ids = {
            ROOT_SPEC_ID: "spec-new",
            "C1": "chapter-new",
            "R1": "req-new",
            "R2": "subreq-new",
        }
        fake_tdx = FakeTdx()

        relation_ids = reconcile_relations(
            nodes,
            edges,
            db_nodes,
            db_edges,
            active_ids,
            set(),
            {ROOT_SPEC_ID, "C1", "R1"},
            fake_tdx,
        )

        self.assertEqual(
            relation_ids,
            {
                (ROOT_SPEC_ID, "C1"): "new-spec-usage",
                ("C1", "R1"): "new-chapter-usage",
                ("R1", "R2"): "new-subrequirement-usage",
            },
        )
        self.assertEqual(
            set(fake_tdx.deleted),
            {
                ("spec-new", "old-spec-usage"),
                ("chapter-new", "old-chapter-usage"),
                ("req-new", "old-subrequirement-usage"),
                ("req-new", "active-stale-subrequirement-usage"),
            },
        )
        self.assertEqual(
            set(fake_tdx.added),
            {
                ("spec-new", "chapter-new"),
                ("chapter-new", "req-new"),
                ("req-new", "subreq-new"),
            },
        )
        self.assertEqual(fake_tdx.chapter_expansions, 2)

    def test_reuses_inherited_usage_when_child_revision_is_unchanged(self):
        class FakeTdx:
            deleted = []
            added = []

            def get_parent_structure(self, _chapter_id, expected_relations=None):
                return {
                    ("parent-rev-1", "child-rev-1"): {
                        "connectionID": "recreated-usage-id",
                        "connectionIDs": ["recreated-usage-id"],
                        "usageType": "Sub Requirement Usage",
                    }
                }

            def delete_several_relations(self, parents, relations):
                self.deleted.append((parents[0], relations[0]))

            def relate_several_elements_req_req(self, parents, children):
                self.added.append((parents[0], children[0][0]))
                return {parents[0]: {children[0][0]: "duplicate-usage"}}

        nodes = {
            "C1": RequirementNode("C1", "Chapter", "Chapter"),
            "R1": RequirementNode("R1", "Requirement", "Parent"),
            "R2": RequirementNode("R2", "Requirement", "Child"),
        }
        edges = {(ROOT_SPEC_ID, "C1"), ("C1", "R1"), ("R1", "R2")}
        db_nodes = {
            ROOT_SPEC_ID: {
                "3dxid": "spec",
                "content": "Spec",
                "object_type": "Requirement Specification",
            },
            "C1": {
                "3dxid": "chapter",
                "content": "Chapter",
                "object_type": "Chapter",
            },
            "R1": {
                "3dxid": "parent-rev-1",
                "content": "Parent",
                "object_type": "Requirement",
            },
            "R2": {
                "3dxid": "child-rev-1",
                "content": "Child",
                "object_type": "Requirement",
            },
        }
        db_edges = {
            (ROOT_SPEC_ID, "C1"): "spec-usage",
            ("C1", "R1"): "chapter-usage",
            ("R1", "R2"): "old-usage",
        }
        active_ids = {
            ROOT_SPEC_ID: "spec",
            "C1": "chapter",
            "R1": "parent-rev-2",
            "R2": "child-rev-1",
        }
        fake_tdx = FakeTdx()

        relation_ids = reconcile_relations(
            nodes,
            edges,
            db_nodes,
            db_edges,
            active_ids,
            set(),
            {"R1"},
            fake_tdx,
        )

        self.assertEqual(relation_ids[("R1", "R2")], "recreated-usage-id")
        self.assertEqual(fake_tdx.deleted, [])
        self.assertEqual(fake_tdx.added, [])


if __name__ == "__main__":
    unittest.main()
