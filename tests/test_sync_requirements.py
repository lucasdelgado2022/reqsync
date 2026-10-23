import unittest
import importlib.util
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import patch

from openpyxl import Workbook

from Requirements import requirementswebcalls
from excel_parser import ROOT_SPEC_ID, RequirementNode, parse_requirement_structure
from sync_requirements import (
    TdxAdapter,
    _confirm_release,
    _fetch_structures,
    _has_pending_release,
    _ordered_edges,
    _release_pending_objects,
    plan_changes,
)


class RequirementWorkbookTests(unittest.TestCase):
    def _make_workbook(self, rows):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "requirements.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["internalid", "content", "parent_ids", "type"])
        for row in rows:
            sheet.append(row)
        workbook.save(path)
        return path

    def _make_hierarchical_workbook(self, rows):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "hierarchy.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.append([None, None, None, None, None, None, "REQUERIMIENTOS"])
        sheet.append([1, 2, 3, 4, 5, 6])
        for row in rows:
            sheet.append(row)
        workbook.save(path)
        return path

    def test_parses_typed_hierarchy_with_semicolon_separated_parents(self):
        path = self._make_workbook(
            [
                ["C1", "", "", "C"],
                ["C2", "", "C1", "C"],
                ["R1", "Description 1", "C1; C2", "R"],
                ["R2", "Description 2", "R1", ""],
            ]
        )

        nodes, edges = parse_requirement_structure(path)

        self.assertEqual(nodes["C1"].object_type, "Chapter")
        self.assertEqual(nodes["R2"].object_type, "Requirement")
        self.assertEqual(nodes["R1"].content, "Description 1")
        self.assertEqual(
            edges,
            {
                (ROOT_SPEC_ID, "C1"),
                ("C1", "C2"),
                ("C1", "R1"),
                ("C2", "R1"),
                ("R1", "R2"),
            },
        )

    def test_rejects_requirement_without_parent(self):
        path = self._make_workbook([["R1", "Description", "", ""]])

        with self.assertRaisesRegex(ValueError, "Top-level requirement"):
            parse_requirement_structure(path)

    def test_rejects_chapter_under_requirement(self):
        path = self._make_workbook(
            [
                ["C1", "", "", "C"],
                ["R1", "Description", "C1", "R"],
                ["C2", "", "R1", "C"],
            ]
        )

        with self.assertRaisesRegex(ValueError, "cannot be contained"):
            parse_requirement_structure(path)

    def test_rejects_cycles(self):
        path = self._make_workbook(
            [
                ["C1", "", "C2", "C"],
                ["C2", "", "C1", "C"],
            ]
        )

        with self.assertRaisesRegex(ValueError, "cycle"):
            parse_requirement_structure(path)

    def test_rejects_missing_parent(self):
        path = self._make_workbook([["R1", "Description", "missing", "R"]])

        with self.assertRaisesRegex(ValueError, "unknown parent"):
            parse_requirement_structure(path)

    def test_parses_implicit_hierarchy_and_metadata_columns(self):
        path = self._make_hierarchical_workbook(
            [
                ["A", None, None, None, None, None, "GENERALES"],
                [None, 3, None, None, None, None, "Parent requirement"],
                [None, None, "a", None, None, None, "Child requirement",
                 None, "Observation", "Must", "Optional",
                 datetime(2026, 8, 13), None, "Difference"],
            ]
        )

        nodes, edges = parse_requirement_structure(path)

        self.assertEqual(nodes["A"].object_type, "Chapter")
        self.assertEqual(nodes["A"].display_title, "A GENERALES")
        self.assertEqual(nodes["A-3"].object_type, "Requirement")
        self.assertEqual(nodes["A-3"].display_title, "A-3")
        self.assertEqual(nodes["A-3-a"].display_title, "A-3-a")
        self.assertEqual(
            nodes["A-3-a"].content,
            "Child requirement\n"
            "NOTAS/OBSERVACIONES: Observation\n"
            "CLASIFICACIÓN FACH: Must\n"
            "CLASIFICACIÓN ARMADA: Optional\n"
            "FACH FECHA: 2026-08-13\n"
            "DIFERENCIAS: Difference",
        )
        self.assertEqual(
            edges,
            {
                (ROOT_SPEC_ID, "A"),
                ("A", "A-3"),
                ("A-3", "A-3-a"),
            },
        )

    def test_parses_current_import_workbook_hierarchy(self):
        repository_root = Path(__file__).resolve().parents[1]
        path = repository_root / "requirements_import.xlsx"
        if not path.exists():
            self.skipTest("Current requirements_import.xlsx is not present")

        nodes, edges = parse_requirement_structure(path)

        self.assertEqual(nodes["A"].display_title, "A GENERALES")
        self.assertEqual(nodes["B"].display_title, "B OPERACIONALES")
        self.assertIn(("B-8", "B-8-a"), edges)
        self.assertEqual(nodes["B-8-a"].object_type, "Requirement")


class ChangePlanningTests(unittest.TestCase):
    def setUp(self):
        self.nodes = {
            "C1": RequirementNode("C1", "Chapter", ""),
            "R1": RequirementNode("R1", "Requirement", "Parent"),
            "R2": RequirementNode("R2", "Requirement", "Original"),
        }
        self.edges = {
            (ROOT_SPEC_ID, "C1"),
            ("C1", "R1"),
            ("R1", "R2"),
        }
        self.db_nodes = {
            ROOT_SPEC_ID: {
                "3dxid": "spec-old",
                "content": "Spec",
                "object_type": "Requirement Specification",
                "active": True,
                "release_pending": False,
            },
            "C1": {
                "3dxid": "chapter-old",
                "content": None,
                "object_type": "Chapter",
                "active": True,
                "release_pending": False,
            },
            "R1": {
                "3dxid": "parent-old",
                "content": "Parent",
                "object_type": "Requirement",
                "active": True,
                "release_pending": False,
            },
            "R2": {
                "3dxid": "child-old",
                "content": "Original",
                "object_type": "Requirement",
                "active": True,
                "release_pending": False,
            },
        }
        self.db_edges = {
            (ROOT_SPEC_ID, "C1"): "spec-usage",
            ("C1", "R1"): "chapter-usage",
            ("R1", "R2"): "req-usage",
        }

    def test_content_change_revises_object_and_every_ancestor(self):
        self.nodes["R2"] = RequirementNode("R2", "Requirement", "Updated")

        plan = plan_changes(self.nodes, self.edges, self.db_nodes, self.db_edges)

        self.assertEqual(plan["created"], set())
        self.assertEqual(plan["direct_changes"], {"R2"})
        self.assertEqual(plan["to_revise"], {ROOT_SPEC_ID, "C1", "R1", "R2"})

    def test_new_edge_revises_parent_and_specification(self):
        self.nodes["R3"] = RequirementNode("R3", "Requirement", "New")
        edges = self.edges | {("R1", "R3")}

        plan = plan_changes(self.nodes, edges, self.db_nodes, self.db_edges)

        self.assertEqual(plan["created"], {"R3"})
        self.assertEqual(plan["to_revise"], {ROOT_SPEC_ID, "C1", "R1"})

    def test_removed_row_is_retained_in_database_but_removed_from_structure(self):
        nodes = {
            "C1": RequirementNode("C1", "Chapter", ""),
            "R1": RequirementNode("R1", "Requirement", "Parent"),
            "R3": RequirementNode("R3", "Requirement", "Descendant"),
        }
        edges = {(ROOT_SPEC_ID, "C1"), ("C1", "R1"), ("C1", "R3")}
        old_edges = {
            (ROOT_SPEC_ID, "C1"): "spec-usage",
            ("C1", "R1"): "chapter-usage",
            ("R1", "R2"): "historical-child-usage",
            ("R2", "R3"): "historical-descendant-usage",
        }
        db_nodes = dict(self.db_nodes)
        db_nodes["R3"] = {
            "3dxid": "descendant-old",
            "content": "Descendant",
            "object_type": "Requirement",
            "active": True,
            "release_pending": False,
        }

        plan = plan_changes(nodes, edges, db_nodes, old_edges)

        self.assertEqual(plan["removed"], {"R2"})
        self.assertEqual(plan["target_edges"], edges)
        self.assertNotIn(("R1", "R2"), plan["target_edges"])
        self.assertNotIn(("R2", "R3"), plan["target_edges"])
        self.assertIn("R1", plan["to_revise"])
        self.assertNotIn("R2", plan["to_revise"])

    def test_detects_changed_sibling_order(self):
        nodes = {
            "C1": RequirementNode("C1", "Chapter", ""),
            "R2": RequirementNode("R2", "Requirement", "Two"),
            "R1": RequirementNode("R1", "Requirement", "One"),
        }
        edges = {(ROOT_SPEC_ID, "C1"), ("C1", "R1"), ("C1", "R2")}
        db_positions = {
            (ROOT_SPEC_ID, "C1"): 0,
            ("C1", "R1"): 0,
            ("C1", "R2"): 1,
        }

        plan = plan_changes(
            nodes,
            edges,
            self.db_nodes,
            self.db_edges,
            db_positions,
        )

        self.assertIn("C1", plan["reordered_parents"])
        self.assertIn("C1", plan["to_revise"])

    def test_relationship_creation_order_follows_workbook_rows(self):
        nodes = {
            "C1": RequirementNode("C1", "Chapter", ""),
            "R2": RequirementNode("R2", "Requirement", "Two"),
            "R1": RequirementNode("R1", "Requirement", "One"),
        }
        edges = {
            (ROOT_SPEC_ID, "C1"),
            ("C1", "R1"),
            ("C1", "R2"),
        }

        ordered = _ordered_edges(nodes, edges)

        self.assertEqual(
            ordered,
            [(ROOT_SPEC_ID, "C1"), ("C1", "R2"), ("C1", "R1")],
        )

    def test_rejects_object_type_changes_for_existing_internal_id(self):
        self.nodes["R1"] = RequirementNode("R1", "Chapter", "")

        with self.assertRaisesRegex(ValueError, "changed type"):
            plan_changes(self.nodes, self.edges, self.db_nodes, self.db_edges)


class TdxAdapterTests(unittest.TestCase):
    def test_creates_nodes_with_display_titles_and_requirement_content(self):
        class Operations:
            def create_several_chapters(self, titles, contents):
                self.chapter_call = (titles, contents)
                return {title: f"chapter-{index}" for index, title in enumerate(titles)}

            def create_several_reqs(self, titles, contents):
                self.requirement_call = (titles, contents)
                return {title: f"requirement-{index}" for index, title in enumerate(titles)}

        operations = Operations()
        adapter = TdxAdapter(operations)

        chapter_ids = adapter.create_nodes(
            "Chapter",
            [RequirementNode("A", "Chapter", "", "A GENERALES")],
        )
        requirement_ids = adapter.create_nodes(
            "Requirement",
            [RequirementNode("A-1", "Requirement", "Text\nNOTAS: note", "A-1")],
        )

        self.assertEqual(operations.chapter_call, (["A GENERALES"], [""]))
        self.assertEqual(operations.requirement_call, (["A-1"], ["Text\nNOTAS: note"]))
        self.assertEqual(chapter_ids, {"A GENERALES": "chapter-0"})
        self.assertEqual(requirement_ids, {"A-1": "requirement-0"})

    def test_requirement_content_sends_html_line_breaks(self):
        class Response:
            status_code = 200

        class Session:
            def __init__(self):
                self.kwargs = None

            def patch(self, _url, **kwargs):
                self.kwargs = kwargs
                return Response()

        session = Session()
        with patch.object(
            requirementswebcalls, "FullURL", side_effect=lambda path: path
        ):
            response = requirementswebcalls.edit_requirement(
                session,
                "csrf-token",
                "requirement-id",
                "Requirement text\r\nNOTAS: <pending> & detail",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            session.kwargs["json"]["contentData"],
            "Requirement text<br/>NOTAS: &lt;pending&gt; &amp; detail",
        )

    def test_creates_relationship_using_existing_operations(self):
        class Operations:
            calls = []

            def relate_several_chapter_req(self, parents, children):
                self.calls.append((parents, children))
                return {parents[0]: {children[0][0]: "usage-id"}}

        operations = Operations()
        adapter = TdxAdapter(operations)

        result = adapter.add_relation("Chapter", "Requirement", "chapter-id", "req-id")

        self.assertEqual(result, "usage-id")
        self.assertEqual(
            operations.calls, [(["chapter-id"], [["req-id"]])]
        )

    def test_tdx_operations_requirement_content_and_chapter_release_fixes(self):
        calls = {"create": [], "edit": [], "states": []}

        class Response:
            status_code = 200

        def create_requirements(_session, _csrf, titles):
            calls["create"].append(titles)
            return Response(), {title: f"id-{title}" for title in titles}

        def edit_requirement(_session, _csrf, object_id, content):
            calls["edit"].append((object_id, content))
            return Response()

        def change_state(_session, _csrf, ids, state, object_type):
            calls["states"].append((ids, state, object_type))
            return Response()

        auth_package = ModuleType("auth")
        auth_package.__path__ = []
        auth_csrf = ModuleType("auth.csrf")
        auth_csrf.getcsrf = lambda _session: "test-token"
        requirements_package = ModuleType("Requirements")
        requirements_package.__path__ = []
        requirement_calls = ModuleType("Requirements.requirementswebcalls")
        requirement_calls.create_requirements = create_requirements
        requirement_calls.edit_requirement = edit_requirement
        lifecycle_package = ModuleType("Lifecycle")
        lifecycle_package.__path__ = []
        lifecycle_calls = ModuleType("Lifecycle.lifecyclewebservice")
        lifecycle_calls.changeState = change_state
        modules = {
            "auth": auth_package,
            "auth.csrf": auth_csrf,
            "Requirements": requirements_package,
            "Requirements.requirementswebcalls": requirement_calls,
            "Lifecycle": lifecycle_package,
            "Lifecycle.lifecyclewebservice": lifecycle_calls,
        }
        module_path = Path(__file__).resolve().parents[1] / "tdxoperations.py"
        spec = importlib.util.spec_from_file_location("tdxoperations_tested", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        operations = importlib.util.module_from_spec(spec)

        with patch.dict("sys.modules", modules):
            spec.loader.exec_module(operations)

        mapping = operations.create_several_reqs(["R1"], ["Requirement text"])
        operations.release_several_chapters(["C1"])

        self.assertEqual(mapping, {"R1": "id-R1"})
        self.assertEqual(calls["create"], [["R1"]])
        self.assertEqual(calls["edit"], [("id-R1", "Requirement text")])
        self.assertEqual(
            calls["states"],
            [
                (["C1"], "Frozen", "Chapter"),
                (["C1"], "Release", "Chapter"),
            ],
        )


class IndexRetryTests(unittest.TestCase):
    def test_retries_explicit_data_not_yet_indexed_response(self):
        expected = ("spec-id", "chapter-id")

        class Api:
            attempts = 0

            def get_specification_structure(self, _object_id):
                self.attempts += 1
                if self.attempts < 3:
                    raise Exception(
                        'Error fetching structure: {"status":400,'
                        '"message":"Data not yet indexed"}'
                    )
                return {expected: {"connectionID": "usage-id"}}

        now = [0]
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            now[0] += seconds

        result = _fetch_structures(
            Api(),
            "spec-id",
            set(),
            {("ROOT", "spec-id"): {expected}},
            timeout_seconds=300,
            sleeper=sleep,
            clock=lambda: now[0],
        )

        self.assertIn(expected, result)
        self.assertEqual(waits, [10, 20])

    def test_explicit_not_indexed_error_retries_until_deadline(self):
        now = [0]

        class Api:
            def get_chapter_structure(self, _object_id):
                raise Exception(
                    'Error fetching structure: {"status":400,'
                    '"message":"Data not yet indexed"}'
                )

        def sleep(seconds):
            now[0] += seconds

        with self.assertRaisesRegex(RuntimeError, "Data not yet indexed"):
            _fetch_structures(
                Api(),
                None,
                {"chapter-id"},
                {},
                timeout_seconds=30,
                sleeper=sleep,
                clock=lambda: now[0],
            )

    def test_does_not_retry_other_structure_errors(self):
        class Api:
            def get_chapter_structure(self, _object_id):
                raise Exception("Permission denied")

        with self.assertRaisesRegex(Exception, "Permission denied"):
            _fetch_structures(
                Api(),
                None,
                {"chapter-id"},
                {},
                timeout_seconds=300,
                sleeper=self.fail,
                clock=lambda: 0,
            )

    def test_retries_incomplete_index_with_increasing_waits(self):
        expected = ("chapter-id", "child-id")

        class Api:
            attempts = 0

            def get_chapter_structure(self, _object_id):
                self.attempts += 1
                return {expected: {"connectionID": "usage-id"}} if self.attempts == 3 else {}

        now = [0]
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            now[0] += seconds

        result = _fetch_structures(
            Api(),
            None,
            {"chapter-id"},
            {("C1", "chapter-id"): {expected}},
            timeout_seconds=300,
            sleeper=sleep,
            clock=lambda: now[0],
        )

        self.assertIn(expected, result)
        self.assertEqual(waits, [10, 20])

    def test_fails_after_retry_deadline_when_expected_link_is_missing(self):
        now = [0]

        class Api:
            def get_chapter_structure(self, _object_id):
                return {}

        def sleep(seconds):
            now[0] += seconds

        with self.assertRaisesRegex(RuntimeError, "refusing to reconcile"):
            _fetch_structures(
                Api(),
                None,
                {"chapter-id"},
                {("C1", "chapter-id"): {("chapter-id", "child-id")}},
                timeout_seconds=30,
                sleeper=sleep,
                clock=lambda: now[0],
            )


class ReleasePromptTests(unittest.TestCase):
    def test_accepts_yes_and_no_answers(self):
        self.assertTrue(_confirm_release(lambda _prompt: "yes"))
        self.assertFalse(_confirm_release(lambda _prompt: "no"))
        self.assertFalse(_confirm_release(lambda _prompt: ""))

    def test_reprompts_on_invalid_answer(self):
        answers = iter(["later", "y"])
        prompts = []

        def input_fn(prompt):
            prompts.append(prompt)
            return next(answers)

        self.assertTrue(_confirm_release(input_fn))
        self.assertEqual(len(prompts), 2)

    def test_end_of_input_defers_release(self):
        self.assertFalse(
            _confirm_release(
                lambda _prompt: (_ for _ in ()).throw(EOFError())
            )
        )

    def test_pending_release_detection(self):
        self.assertTrue(
            _has_pending_release(
                {"C1": {"release_pending": False}, "R1": {"release_pending": True}}
            )
        )
        self.assertFalse(
            _has_pending_release({"C1": {"release_pending": False}})
        )

    def test_declining_keeps_pending_objects_unreleased(self):
        class Api:
            def release(self, *_args):
                raise AssertionError("Release must not run after declining")

        pending = {
            ROOT_SPEC_ID: {"release_pending": True},
            "C1": {"release_pending": True},
        }

        released = _release_pending_objects(
            connection=None,
            api=Api(),
            nodes={},
            db_nodes=pending,
            active_ids={},
            target_edges=set(),
            confirm_release=lambda: False,
        )

        self.assertFalse(released)
        self.assertTrue(all(node["release_pending"] for node in pending.values()))


if __name__ == "__main__":
    unittest.main()
