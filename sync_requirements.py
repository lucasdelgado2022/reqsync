import argparse
import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import psycopg2
from dotenv import dotenv_values

from excel_parser import ROOT_SPEC_ID, RequirementNode, parse_requirement_structure


LOGGER = logging.getLogger("reqsync")
SPEC_TITLE_DEFAULT = "STM RRFF"
REVISION_BATCH_SIZE = 100
INDEX_RETRY_TIMEOUT_SECONDS = 5 * 60
INDEX_RETRY_STEP_SECONDS = 10

RELATION_METHODS = {
    ("Requirement Specification", "Chapter"): (
        "relate_several_spec_chapter",
        "delete_several_relations_spec_chapter",
        "spec-chapter",
    ),
    ("Chapter", "Chapter"): (
        "relate_several_chapter_chapter",
        "delete_several_relations_chapter_chapter",
        "chapter-chapter",
    ),
    ("Chapter", "Requirement"): (
        "relate_several_chapter_req",
        "delete_several_relations_chapter_req",
        "chapter-req",
    ),
    ("Requirement", "Requirement"): (
        "relate_several_req_req",
        "delete_several_relations_req_req",
        "req-req",
    ),
}


class TdxAdapter:
    def __init__(self, operations: Any):
        self.operations = operations

    @classmethod
    def from_tdxoperations(cls) -> "TdxAdapter":
        import tdxoperations

        return cls(tdxoperations)

    def create_specification(self, title: str) -> str:
        return self.operations.create_spec(title)

    def create_nodes(
        self, object_type: str, nodes: list[RequirementNode]
    ) -> dict[str, str]:
        titles = [node.display_title for node in nodes]
        if object_type == "Chapter":
            result = self.operations.create_several_chapters(
                titles, [node.content for node in nodes]
            )
        else:
            result = self.operations.create_several_reqs(
                titles, [node.content for node in nodes]
            )
        return result

    def update_chapter_title(self, object_id: str, title: str) -> None:
        response = self.operations.edit_chapter(
            self.operations.session,
            self.operations.ENO_CSRF_TOKEN,
            object_id,
            title,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Could not set 3DEXPERIENCE chapter title {title!r}: "
                f"{response.status_code} {response.text}"
            )

    def revise_requirements(
        self, ids: list[str], content_changes: list[str | None]
    ) -> dict[str, str]:
        return self.operations.revise_several_reqs(ids, content_changes)

    def revise_chapters(self, ids: list[str]) -> dict[str, str]:
        return self.operations.revise_several_chapters(ids)

    def revise_specification(self, object_id: str) -> dict[str, str]:
        return self.operations.revise_spec(object_id)

    def release(self, object_type: str, ids: list[str]) -> None:
        if object_type == "Chapter":
            self.operations.release_several_chapters(ids)
        elif object_type == "Requirement":
            self.operations.release_several_reqs(ids)
        elif object_type == "Requirement Specification":
            for object_id in ids:
                self.operations.release_spec(object_id)
        else:
            raise ValueError(f"Unsupported 3DEXPERIENCE object type: {object_type}")

    def add_relation(
        self, parent_type: str, child_type: str, parent_id: str, child_id: str
    ) -> str:
        method_name, _, relation_type = _relation_methods(parent_type, child_type)
        result = getattr(self.operations, method_name)(
            [parent_id], [[child_id]]
        )
        try:
            connection_id = result[parent_id][child_id]
        except (KeyError, TypeError) as error:
            raise RuntimeError(
                f"3DEXPERIENCE did not return a usage ID for {relation_type} "
                f"{parent_id!r} -> {child_id!r}"
            ) from error
        if not connection_id:
            raise RuntimeError(
                f"3DEXPERIENCE returned an empty usage ID for {relation_type} "
                f"{parent_id!r} -> {child_id!r}"
            )
        return connection_id

    def delete_relation(
        self, relation_type: str, parent_id: str, connection_id: str
    ) -> None:
        method_name = _delete_method_for_relation(relation_type)
        getattr(self.operations, method_name)([parent_id], [connection_id])

    def get_specification_structure(self, object_id: str) -> dict:
        return self.operations.get_structure_spec(object_id)

    def get_chapter_structure(self, object_id: str) -> dict:
        return self.operations.get_structure_chapter(object_id)


def _relation_methods(parent_type: str, child_type: str) -> tuple[str, str, str]:
    try:
        return RELATION_METHODS[(parent_type, child_type)]
    except KeyError as error:
        raise ValueError(
            f"Unsupported relationship: {parent_type} -> {child_type}"
        ) from error


def _delete_method_for_relation(relation_type: str) -> str:
    for _, delete_method, known_type in RELATION_METHODS.values():
        if known_type == relation_type:
            return delete_method
    raise ValueError(f"Unsupported relationship type: {relation_type}")


def connect_to_database(env_file: str | Path):
    values = dotenv_values(env_file)

    def setting(name: str) -> str:
        value = os.environ.get(name) or values.get(name)
        if not value:
            raise RuntimeError(
                f"Database setting {name} is missing from {env_file} and the environment"
            )
        return str(value)

    return psycopg2.connect(
        dbname=setting("POSTGRES_DB"),
        user=setting("POSTGRES_USER"),
        password=setting("POSTGRES_PASSWORD"),
        host=setting("DB_HOST"),
        port=setting("DB_PORT"),
        connect_timeout=10,
    )


def ensure_schema(connection) -> None:
    statements = (
        'ALTER TABLE id_mappings ALTER COLUMN "3dxid" DROP NOT NULL',
        'ALTER TABLE id_mappings ADD COLUMN IF NOT EXISTS previous_3dxid VARCHAR(255)',
        "ALTER TABLE id_mappings "
        "ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE id_mappings "
        "ADD COLUMN IF NOT EXISTS release_pending BOOLEAN NOT NULL DEFAULT FALSE",
        """
        CREATE TABLE IF NOT EXISTS object_revision_history (
            history_id BIGSERIAL PRIMARY KEY,
            internalid VARCHAR(255) NOT NULL REFERENCES id_mappings(internalid),
            "3dxid" VARCHAR(255) NOT NULL,
            content TEXT,
            object_type VARCHAR(64) NOT NULL,
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (internalid, "3dxid")
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS connection_history (
            history_id BIGSERIAL PRIMARY KEY,
            child_id VARCHAR(255) NOT NULL REFERENCES id_mappings(internalid),
            parent_id VARCHAR(255) NOT NULL REFERENCES id_mappings(internalid),
            connection_3dx_id VARCHAR(255),
            recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "ALTER TABLE requirement_connections "
        "ADD COLUMN IF NOT EXISTS position INTEGER NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS idx_revision_history_3dxid "
        'ON object_revision_history("3dxid")',
        "CREATE INDEX IF NOT EXISTS idx_connection_history_3dxid "
        "ON connection_history(connection_3dx_id)",
    )
    with connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)
    connection.commit()


def load_state(connection) -> tuple[dict[str, dict], dict[tuple[str, str], str | None]]:
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT internalid, "3dxid", content, object_type, active, '
            'release_pending, previous_3dxid '
            "FROM id_mappings"
        )
        nodes = {
            row[0]: {
                "3dxid": row[1],
                "content": row[2],
                "object_type": row[3],
                "active": row[4],
                "release_pending": row[5],
                "previous_3dxid": row[6],
            }
            for row in cursor.fetchall()
        }
        cursor.execute(
            "SELECT parent_id, child_id, connection_3dx_id FROM requirement_connections"
        )
        edges = {(row[0], row[1]): row[2] for row in cursor.fetchall()}
    return nodes, edges


def load_edge_positions(connection) -> dict[tuple[str, str], int]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT parent_id, child_id, position FROM requirement_connections"
        )
        return {(row[0], row[1]): row[2] for row in cursor.fetchall()}


def load_historical_ids(connection) -> dict[str, str]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT internalid, previous_3dxid FROM id_mappings "
            "WHERE previous_3dxid IS NOT NULL"
        )
        return {row[1]: row[0] for row in cursor.fetchall()}


def persist_mapping(
    connection,
    internalid: str,
    object_id: str,
    content: str | None,
    object_type: str,
    *,
    active: bool = True,
    release_pending: bool = False,
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT "3dxid", content, object_type FROM id_mappings '
            "WHERE internalid = %s FOR UPDATE",
            (internalid,),
        )
        previous = cursor.fetchone()
        cursor.execute(
            """
            INSERT INTO id_mappings
                (internalid, "3dxid", previous_3dxid, content, object_type, active, release_pending)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (internalid) DO UPDATE SET
                previous_3dxid = COALESCE(EXCLUDED.previous_3dxid, id_mappings.previous_3dxid),
                "3dxid" = EXCLUDED."3dxid",
                content = EXCLUDED.content,
                object_type = EXCLUDED.object_type,
                active = EXCLUDED.active,
                release_pending = EXCLUDED.release_pending
            """,
            (
                internalid,
                object_id,
                previous[0]
                if previous is not None
                and previous[0] is not None
                and previous[0] != object_id
                else None,
                content,
                object_type,
                active,
                release_pending,
            ),
        )
    connection.commit()


def stage_workbook_state(
    connection,
    nodes: dict[str, RequirementNode],
    edges: set[tuple[str, str]],
) -> None:
    edge_positions = _relation_positions(nodes, edges)
    with connection.cursor() as cursor:
        for node in nodes.values():
            cursor.execute(
                """
                INSERT INTO id_mappings
                    (internalid, "3dxid", content, object_type, active)
                VALUES (%s, NULL, %s, %s, TRUE)
                ON CONFLICT (internalid) DO NOTHING
                """,
                (
                    node.internalid,
                    node.content
                    if node.object_type == "Requirement"
                    else node.display_title,
                    node.object_type,
                ),
            )
        for parent_id, child_id in _ordered_edges(nodes, edges):
            cursor.execute(
                """
                INSERT INTO requirement_connections
                    (parent_id, child_id, connection_3dx_id, position)
                VALUES (%s, %s, NULL, %s)
                ON CONFLICT (child_id, parent_id) DO NOTHING
                """,
                (parent_id, child_id, edge_positions[(parent_id, child_id)]),
            )
    connection.commit()


def _relation_positions(
    nodes: dict[str, RequirementNode],
    edges: set[tuple[str, str]],
) -> dict[tuple[str, str], int]:
    node_order = {internalid: index for index, internalid in enumerate(nodes)}
    children: dict[str, list[str]] = defaultdict(list)
    for parent_id, child_id in edges:
        children[parent_id].append(child_id)
    return {
        (parent_id, child_id): position
        for parent_id, child_ids in children.items()
        for position, child_id in enumerate(
            sorted(
                child_ids,
                key=lambda child_id: node_order.get(child_id, len(node_order)),
            )
        )
    }


def _ordered_edges(
    nodes: dict[str, RequirementNode],
    edges: set[tuple[str, str]],
) -> list[tuple[str, str]]:
    node_order = {internalid: index for index, internalid in enumerate(nodes)}
    positions = _relation_positions(nodes, edges)
    return sorted(
        edges,
        key=lambda edge: (
            -1 if edge[0] == ROOT_SPEC_ID else node_order.get(edge[0], len(node_order)),
            positions[edge],
        ),
    )


def plan_changes(
    nodes: dict[str, RequirementNode],
    edges: set[tuple[str, str]],
    db_nodes: dict[str, dict],
    db_edges: dict[tuple[str, str], str | None],
    db_edge_positions: dict[tuple[str, str], int] | None = None,
) -> dict[str, set]:
    active_db_ids = {
        internalid
        for internalid, record in db_nodes.items()
        if record["active"] and internalid != ROOT_SPEC_ID
    }
    present_ids = set(nodes)
    created = {
        internalid
        for internalid in present_ids
        if internalid not in db_nodes or db_nodes[internalid]["3dxid"] is None
    }
    removed = active_db_ids.difference(present_ids)
    inactive = {
        internalid
        for internalid, record in db_nodes.items()
        if not record["active"] and internalid != ROOT_SPEC_ID
    }

    for internalid in present_ids.intersection(db_nodes):
        old_type = db_nodes[internalid]["object_type"]
        if old_type != nodes[internalid].object_type:
            raise ValueError(
                f"Object {internalid!r} changed type from {old_type} to "
                f"{nodes[internalid].object_type}; use a new internalid instead"
            )

    target_edges = set(edges)
    edge_changes = set(db_edges).symmetric_difference(target_edges)
    pending_edges = {
        edge for edge, connection_id in db_edges.items() if connection_id is None
    }
    desired_positions = _relation_positions(nodes, target_edges)
    reordered_parents = {
        edge[0]
        for edge, position in desired_positions.items()
        if edge in db_edges
        and db_edge_positions is not None
        and db_edge_positions.get(edge) != position
    }
    changed_parents = {
        parent_id
        for parent_id, _ in edge_changes | pending_edges
        if (
            parent_id in db_nodes
            and parent_id not in removed | inactive
            and db_nodes[parent_id]["3dxid"] is not None
            and not db_nodes[parent_id]["release_pending"]
        )
    }
    changed_parents.update(
        parent_id
        for parent_id in reordered_parents
        if (
            parent_id in db_nodes
            and parent_id not in removed | inactive
            and db_nodes[parent_id]["3dxid"] is not None
            and not db_nodes[parent_id]["release_pending"]
        )
    )
    direct_changes = {
        internalid
        for internalid, node in nodes.items()
        if (
            internalid in db_nodes
            and db_nodes[internalid]["3dxid"] is not None
            and node.object_type == "Requirement"
            and db_nodes[internalid]["content"] != node.content
        )
    }
    title_changes = {
        internalid
        for internalid, node in nodes.items()
        if (
            node.object_type == "Chapter"
            and internalid in db_nodes
            and db_nodes[internalid]["3dxid"] is not None
            and db_nodes[internalid]["content"] != node.display_title
        )
    }

    to_revise = changed_parents | direct_changes | title_changes
    parent_graph: dict[str, set[str]] = defaultdict(set)
    for parent_id, child_id in set(db_edges) | target_edges:
        parent_graph[child_id].add(parent_id)

    pending = list(to_revise)
    while pending:
        child_id = pending.pop()
        for parent_id in parent_graph.get(child_id, set()):
            if (
                parent_id in db_nodes
                and parent_id not in removed | inactive
                and db_nodes[parent_id]["3dxid"] is not None
                and parent_id not in to_revise
            ):
                to_revise.add(parent_id)
                pending.append(parent_id)

    return {
        "created": created,
        "removed": removed,
        "direct_changes": direct_changes,
        "title_changes": title_changes,
        "to_revise": to_revise,
        "target_edges": target_edges,
        "edge_changes": edge_changes,
        "pending_edges": pending_edges,
        "reordered_parents": reordered_parents,
    }


def _compute_depths(
    nodes: dict[str, RequirementNode],
    edges: set[tuple[str, str]],
    known_ids: set[str],
) -> dict[str, int]:
    all_ids = set(nodes) | (known_ids - {ROOT_SPEC_ID})
    parents: dict[str, set[str]] = defaultdict(set)
    for parent_id, child_id in edges:
        if child_id in all_ids and (parent_id == ROOT_SPEC_ID or parent_id in all_ids):
            parents[child_id].add(parent_id)

    depths: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(internalid: str) -> int:
        if internalid in depths:
            return depths[internalid]
        if internalid in visiting:
            raise ValueError(f"Stored hierarchy contains a cycle at {internalid!r}")
        visiting.add(internalid)
        ancestors = parents.get(internalid, set())
        result = (
            max(depth(parent_id) + 1 for parent_id in ancestors if parent_id != ROOT_SPEC_ID)
            if any(parent_id != ROOT_SPEC_ID for parent_id in ancestors)
            else 0
        )
        visiting.remove(internalid)
        depths[internalid] = result
        return result

    for internalid in all_ids:
        depth(internalid)
    return depths


def _ensure_id_map(result: dict, titles: list[str], kind: str) -> dict[str, str]:
    if not isinstance(result, dict):
        raise RuntimeError(f"3DEXPERIENCE returned an invalid {kind} ID map")
    missing = [title for title in titles if not result.get(title)]
    if missing:
        raise RuntimeError(
            f"3DEXPERIENCE did not return IDs for {kind}: {', '.join(missing)}"
        )
    return result


def _create_missing_nodes(
    connection,
    api: TdxAdapter,
    nodes: dict[str, RequirementNode],
    created: set[str],
) -> dict[str, str]:
    object_ids: dict[str, str] = {}
    for object_type in ("Chapter", "Requirement"):
        batch = [
            nodes[internalid]
            for internalid in nodes
            if internalid in created and nodes[internalid].object_type == object_type
        ]
        if not batch:
            continue
        titles = [node.display_title for node in batch]
        id_map = _ensure_id_map(
            api.create_nodes(object_type, batch), titles, object_type.lower()
        )
        for node in batch:
            object_id = id_map[node.display_title]
            persist_mapping(
                connection,
                node.internalid,
                object_id,
                node.content
                if object_type == "Requirement"
                else node.display_title,
                object_type,
                active=True,
                release_pending=True,
            )
            object_ids[node.internalid] = object_id
            LOGGER.info("Created %s %s (%s)", object_type, node.internalid, object_id)
    return object_ids


def _revise_nodes(
    connection,
    api: TdxAdapter,
    nodes: dict[str, RequirementNode],
    db_nodes: dict[str, dict],
    to_revise: set[str],
    active_ids: dict[str, str],
    target_edges: set[tuple[str, str]],
    content_changes: set[str],
    title_changes: set[str],
) -> set[str]:
    revision_ids: set[str] = set()
    depths = _compute_depths(nodes, target_edges, set(db_nodes))
    levels: dict[int, list[str]] = defaultdict(list)
    for internalid in to_revise:
        if internalid != ROOT_SPEC_ID and internalid in active_ids:
            levels[depths.get(internalid, 0)].append(internalid)

    for level in sorted(levels, reverse=True):
        level_ids = sorted(levels[level])
        for object_type in ("Requirement", "Chapter"):
            selected = [
                internalid
                for internalid in level_ids
                if db_nodes[internalid]["object_type"] == object_type
            ]
            for offset in range(0, len(selected), REVISION_BATCH_SIZE):
                batch = selected[offset : offset + REVISION_BATCH_SIZE]
                old_ids = [active_ids[internalid] for internalid in batch]
                if object_type == "Requirement":
                    changes = [
                        nodes[internalid].content
                        if internalid in content_changes and internalid in nodes
                        else None
                        for internalid in batch
                    ]
                    revisions = api.revise_requirements(old_ids, changes)
                else:
                    revisions = api.revise_chapters(old_ids)
                _ensure_id_map(revisions, old_ids, f"{object_type.lower()} revisions")
                for internalid, old_id in zip(batch, old_ids):
                    new_id = revisions[old_id]
                    active_ids[internalid] = new_id
                    node = nodes.get(internalid)
                    content = (
                        node.content
                        if node is not None and node.object_type == "Requirement"
                        else node.display_title
                        if node is not None
                        else db_nodes[internalid]["content"]
                    )
                    if (
                        object_type == "Chapter"
                        and internalid in title_changes
                        and node is not None
                    ):
                        api.update_chapter_title(new_id, node.display_title)
                    persist_mapping(
                        connection,
                        internalid,
                        new_id,
                        content,
                        object_type,
                        active=node is not None,
                        release_pending=True,
                    )
                    db_nodes[internalid]["3dxid"] = new_id
                    db_nodes[internalid]["content"] = content
                    db_nodes[internalid]["active"] = node is not None
                    db_nodes[internalid]["release_pending"] = True
                    revision_ids.add(internalid)
                    LOGGER.info(
                        "Revised %s %s: %s -> %s",
                        object_type,
                        internalid,
                        old_id,
                        new_id,
                    )
    return revision_ids


def _affected_chapters(
    parent_id: str,
    nodes: dict[str, RequirementNode],
    db_nodes: dict[str, dict],
    old_edges: set[tuple[str, str]],
    target_edges: set[tuple[str, str]],
) -> set[str]:
    if parent_id == ROOT_SPEC_ID:
        return set()
    record = db_nodes.get(parent_id)
    node = nodes.get(parent_id)
    object_type = node.object_type if node is not None else (
        record["object_type"] if record is not None else None
    )
    if object_type == "Chapter":
        return {parent_id}

    parents: dict[str, set[str]] = defaultdict(set)
    for parent, child in old_edges | target_edges:
        parents[child].add(parent)
    found: set[str] = set()
    visited: set[str] = set()
    pending = list(parents.get(parent_id, set()))
    while pending:
        ancestor = pending.pop()
        if ancestor in visited:
            continue
        visited.add(ancestor)
        if ancestor == ROOT_SPEC_ID:
            continue
        ancestor_node = nodes.get(ancestor)
        ancestor_record = db_nodes.get(ancestor)
        ancestor_type = (
            ancestor_node.object_type
            if ancestor_node is not None
            else ancestor_record["object_type"]
            if ancestor_record is not None
            else None
        )
        if ancestor_type == "Chapter":
            found.add(ancestor)
        else:
            pending.extend(parents.get(ancestor, set()))
    return found


def _fetch_structures(
    api: TdxAdapter,
    specification_id: str | None,
    chapter_ids: set[str],
    expected: dict[tuple[str, str], set[tuple[str, str]]],
    *,
    timeout_seconds: int,
    sleeper=time.sleep,
    clock=time.monotonic,
) -> dict[tuple[str, str], dict]:
    started_at = clock()
    interval = INDEX_RETRY_STEP_SECONDS

    while True:
        structures: dict[tuple[str, str], dict] = {}
        index_error: Exception | None = None
        try:
            if specification_id:
                structures.update(api.get_specification_structure(specification_id))
            for chapter_id in sorted(chapter_ids):
                structures.update(api.get_chapter_structure(chapter_id))
        except Exception as error:
            if not _is_not_yet_indexed_error(error):
                raise
            index_error = error

        missing = {
            relation
            for relations in expected.values()
            for relation in relations
            if relation not in structures
        }
        if not missing and index_error is None:
            return structures

        elapsed = clock() - started_at
        if elapsed >= timeout_seconds:
            raise RuntimeError(
                "3DEXPERIENCE indexing did not return structures and expected "
                "relations within "
                f"{timeout_seconds} seconds; refusing to reconcile incomplete "
                f"structures. Missing: {sorted(missing)}"
                + (
                    f". Last indexing response: {index_error}"
                    if index_error is not None
                    else ""
                )
            ) from index_error
        wait = min(interval, timeout_seconds - elapsed)
        LOGGER.info(
            "Waiting %.0f seconds for 3DEXPERIENCE indexing; %d expected "
            "relationship(s) are not visible yet%s",
            wait,
            len(missing),
            " (API reports data not yet indexed)" if index_error else "",
        )
        sleeper(wait)
        interval += INDEX_RETRY_STEP_SECONDS


def _is_not_yet_indexed_error(error: Exception) -> bool:
    prefix = "Error fetching structure:"
    message = str(error).strip()
    if not message.startswith(prefix):
        return False
    try:
        payload = json.loads(message[len(prefix) :].strip())
    except (TypeError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("status") == 400
        and payload.get("message") == "Data not yet indexed"
    )


def _persist_connection_id(
    connection,
    edge: tuple[str, str],
    connection_id: str | None,
    position: int,
) -> None:
    parent_id, child_id = edge
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT connection_3dx_id FROM requirement_connections "
            "WHERE parent_id = %s AND child_id = %s FOR UPDATE",
            (parent_id, child_id),
        )
        previous = cursor.fetchone()
        if (
            previous is not None
            and previous[0] is not None
            and previous[0] != connection_id
        ):
            cursor.execute(
                """
                INSERT INTO connection_history
                    (child_id, parent_id, connection_3dx_id)
                VALUES (%s, %s, %s)
                """,
                (child_id, parent_id, previous[0]),
            )
        cursor.execute(
            """
            INSERT INTO requirement_connections
                (parent_id, child_id, connection_3dx_id, position)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (child_id, parent_id) DO UPDATE SET
                connection_3dx_id = EXCLUDED.connection_3dx_id,
                position = EXCLUDED.position
            """,
            (parent_id, child_id, connection_id, position),
        )
    connection.commit()


def _remove_connection_record(
    connection, edge: tuple[str, str]
) -> None:
    parent_id, child_id = edge
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO connection_history
                (child_id, parent_id, connection_3dx_id)
            SELECT child_id, parent_id, connection_3dx_id
            FROM requirement_connections
            WHERE parent_id = %s AND child_id = %s
            """,
            (parent_id, child_id),
        )
        cursor.execute(
            "DELETE FROM requirement_connections "
            "WHERE parent_id = %s AND child_id = %s",
            (parent_id, child_id),
        )
    connection.commit()


def _parent_type(
    parent_id: str,
    nodes: dict[str, RequirementNode],
    db_nodes: dict[str, dict],
) -> str:
    if parent_id == ROOT_SPEC_ID:
        return "Requirement Specification"
    parent = nodes.get(parent_id)
    parent_record = db_nodes.get(parent_id)
    parent_type = (
        parent.object_type
        if parent is not None
        else parent_record["object_type"]
        if parent_record is not None
        else None
    )
    return parent_type or ""


def _reconcile_relations(
    connection,
    api: TdxAdapter,
    nodes: dict[str, RequirementNode],
    db_nodes: dict[str, dict],
    old_edges: set[tuple[str, str]],
    target_edges: set[tuple[str, str]],
    parents_to_reconcile: set[str],
    active_ids: dict[str, str],
    old_ids: dict[str, str],
    historical_id_to_internal: dict[str, str],
    created_ids: set[str],
    *,
    index_timeout_seconds: int,
    sleeper=time.sleep,
    clock=time.monotonic,
) -> dict[tuple[str, str], str | None]:
    id_to_internal = dict(historical_id_to_internal)
    id_to_internal.update({object_id: key for key, object_id in old_ids.items()})
    id_to_internal.update({object_id: key for key, object_id in active_ids.items()})
    desired_children: dict[str, set[str]] = defaultdict(set)
    for parent_id, child_id in target_edges:
        desired_children[parent_id].add(child_id)
    edge_positions = _relation_positions(nodes, target_edges)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT parent_id, child_id, connection_3dx_id "
            "FROM requirement_connections"
        )
        connection_ids = {
            (row[0], row[1]): row[2] for row in cursor.fetchall()
        }

    depths = _compute_depths(nodes, target_edges, set(db_nodes))
    edge_positions = _relation_positions(nodes, target_edges)
    node_order = {internalid: index for index, internalid in enumerate(nodes)}
    ordered_parents = sorted(
        parents_to_reconcile,
        key=lambda internalid: (
            -1 if internalid == ROOT_SPEC_ID else depths.get(internalid, 0),
            node_order.get(internalid, -1),
        ),
    )

    for parent_internal_id in ordered_parents:
        parent_3dx_id = active_ids.get(parent_internal_id)
        if not parent_3dx_id:
            continue
        parent_type = _parent_type(parent_internal_id, nodes, db_nodes)
        if not parent_type:
            continue

        structures: dict[tuple[str, str], dict] = {}
        if parent_internal_id not in created_ids:
            query_chapters = _affected_chapters(
                parent_internal_id, nodes, db_nodes, old_edges, target_edges
            )
            query_chapters.intersection_update(active_ids)
            query_chapters.difference_update(created_ids)
            chapter_object_ids = {
                active_ids[chapter_id] for chapter_id in query_chapters
            }
            specification_id = (
                parent_3dx_id if parent_internal_id == ROOT_SPEC_ID else None
            )
            expected_relations: set[tuple[str, str]] = set()
            for edge_parent, child_id in old_edges:
                if (
                    edge_parent == parent_internal_id
                    and child_id in old_ids
                    and connection_ids.get((edge_parent, child_id)) is not None
                ):
                    expected_relations.add((parent_3dx_id, old_ids[child_id]))
            expected = {
                (parent_internal_id, parent_3dx_id): expected_relations
            }
            structures = _fetch_structures(
                api,
                specification_id,
                chapter_object_ids,
                expected,
                timeout_seconds=index_timeout_seconds,
                sleeper=sleeper,
                clock=clock,
            )

        actual = [
            (child_3dx_id, details)
            for (actual_parent_id, child_3dx_id), details in structures.items()
            if actual_parent_id == parent_3dx_id
        ]
        desired_for_parent = desired_children.get(parent_internal_id, set())

        for child_3dx_id, details in actual:
            relation_type = details.get("type")
            connection_id = details.get("connectionID")
            if not relation_type or not connection_id:
                raise RuntimeError(
                    f"Cannot remove unrecognized relationship from {parent_3dx_id}: "
                    f"{details!r}"
                )
            api.delete_relation(relation_type, parent_3dx_id, connection_id)
            internal_child = id_to_internal.get(child_3dx_id)
            if internal_child is not None:
                edge = (parent_internal_id, internal_child)
                connection_ids.pop(edge, None)
                _remove_connection_record(connection, edge)
            LOGGER.info(
                "Removed %s usage %s from %s",
                relation_type,
                connection_id,
                parent_internal_id,
            )

        for child_internal_id in sorted(
            desired_for_parent,
            key=lambda child: node_order.get(child, len(node_order)),
        ):
            child_3dx_id = active_ids.get(child_internal_id)
            if not child_3dx_id:
                raise RuntimeError(
                    f"No active 3DEXPERIENCE ID for {child_internal_id!r}"
                )
            child_type = (
                nodes[child_internal_id].object_type
                if child_internal_id in nodes
                else db_nodes[child_internal_id]["object_type"]
            )
            _, _, relation_type = _relation_methods(parent_type, child_type)
            usage_id = api.add_relation(
                parent_type, child_type, parent_3dx_id, child_3dx_id
            )
            connection_ids[(parent_internal_id, child_internal_id)] = usage_id
            _persist_connection_id(
                connection,
                (parent_internal_id, child_internal_id),
                usage_id,
                edge_positions[(parent_internal_id, child_internal_id)],
            )
            LOGGER.info(
                "Added %s usage %s -> %s (%s)",
                relation_type,
                parent_internal_id,
                child_internal_id,
                usage_id,
            )

    for edge in set(connection_ids).difference(target_edges):
        connection_ids.pop(edge, None)
    return connection_ids


def persist_edges(
    connection,
    target_edges: set[tuple[str, str]],
    connection_ids: dict[tuple[str, str], str | None],
    nodes: dict[str, RequirementNode],
) -> None:
    edge_positions = _relation_positions(nodes, target_edges)
    with connection.cursor() as cursor:
        cursor.execute("SELECT parent_id, child_id FROM requirement_connections")
        current_edges = {(row[0], row[1]) for row in cursor.fetchall()}
        for parent_id, child_id in current_edges.difference(target_edges):
            cursor.execute(
                """
                INSERT INTO connection_history
                    (child_id, parent_id, connection_3dx_id)
                SELECT child_id, parent_id, connection_3dx_id
                FROM requirement_connections
                WHERE parent_id = %s AND child_id = %s
                """,
                (parent_id, child_id),
            )
            cursor.execute(
                "DELETE FROM requirement_connections "
                "WHERE parent_id = %s AND child_id = %s",
                (parent_id, child_id),
            )

        for parent_id, child_id in target_edges:
            connection_id = connection_ids.get((parent_id, child_id))
            if connection_id is None:
                raise RuntimeError(
                    f"No 3DEXPERIENCE usage ID was reconciled for "
                    f"{parent_id!r} -> {child_id!r}"
                )
            cursor.execute(
                """
                SELECT connection_3dx_id FROM requirement_connections
                WHERE parent_id = %s AND child_id = %s FOR UPDATE
                """,
                (parent_id, child_id),
            )
            previous = cursor.fetchone()
            if (
                previous is not None
                and previous[0] is not None
                and previous[0] != connection_id
            ):
                cursor.execute(
                    """
                    INSERT INTO connection_history
                        (child_id, parent_id, connection_3dx_id)
                    VALUES (%s, %s, %s)
                    """,
                    (child_id, parent_id, previous[0]),
                )
            cursor.execute(
                """
                INSERT INTO requirement_connections
                    (parent_id, child_id, connection_3dx_id, position)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (child_id, parent_id) DO UPDATE SET
                    connection_3dx_id = EXCLUDED.connection_3dx_id,
                    position = EXCLUDED.position
                """,
                (
                    parent_id,
                    child_id,
                    connection_id,
                    edge_positions[(parent_id, child_id)],
                ),
            )
    connection.commit()


def _set_active_state(connection, internalid: str, active: bool) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE id_mappings SET active = %s WHERE internalid = %s",
            (active, internalid),
        )
    connection.commit()


def _has_pending_release(db_nodes: dict[str, dict]) -> bool:
    return any(record["release_pending"] for record in db_nodes.values())


def _confirm_release(input_fn=None) -> bool:
    read_input = input if input_fn is None else input_fn
    while True:
        try:
            answer = read_input(
                "Structure is ready. Release it to 3DEXPERIENCE now? [y/N]: "
            ).strip().lower()
        except EOFError:
            print("No response received; keeping the structure unreleased.")
            return False
        if answer in {"y", "yes"}:
            return True
        if answer in {"", "n", "no"}:
            return False
        print("Please answer yes or no.")


def _release_pending_objects(
    connection,
    api: TdxAdapter,
    nodes: dict[str, RequirementNode],
    db_nodes: dict[str, dict],
    active_ids: dict[str, str],
    target_edges: set[tuple[str, str]],
    *,
    confirm_release=None,
) -> bool:
    if not _has_pending_release(db_nodes):
        return False

    should_release = (
        _confirm_release() if confirm_release is None else confirm_release()
    )
    if not should_release:
        LOGGER.info(
            "Release deferred by user; objects remain pending release for the next run"
        )
        return False

    pending_ids = {
        internalid
        for internalid, record in db_nodes.items()
        if record["release_pending"] and internalid != ROOT_SPEC_ID
    }
    depths = _compute_depths(nodes, target_edges, set(db_nodes))
    by_level: dict[int, dict[str, list[str]]] = defaultdict(
        lambda: {"Requirement": [], "Chapter": []}
    )
    for internalid in pending_ids:
        if internalid not in active_ids:
            raise RuntimeError(
                f"Pending release has no 3DEXPERIENCE ID for {internalid!r}"
            )
        object_type = db_nodes[internalid]["object_type"]
        if object_type in by_level[depths.get(internalid, 0)]:
            by_level[depths.get(internalid, 0)][object_type].append(
                active_ids[internalid]
            )

    for level in sorted(by_level, reverse=True):
        for object_type in ("Requirement", "Chapter"):
            ids = sorted(by_level[level][object_type])
            if ids:
                api.release(object_type, ids)
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE id_mappings SET release_pending = FALSE "
                        'WHERE "3dxid" = ANY(%s)',
                        (ids,),
                    )
                connection.commit()
                LOGGER.info("Released %d %s object(s)", len(ids), object_type)

    if db_nodes.get(ROOT_SPEC_ID, {}).get("release_pending"):
        spec_id = active_ids.get(ROOT_SPEC_ID)
        if not spec_id:
            raise RuntimeError("The root specification has no active 3DEXPERIENCE ID")
        api.release("Requirement Specification", [spec_id])
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE id_mappings SET release_pending = FALSE WHERE internalid = %s",
                (ROOT_SPEC_ID,),
            )
        connection.commit()
        LOGGER.info("Released root specification %s", spec_id)
    return True


def synchronize(
    connection,
    nodes: dict[str, RequirementNode],
    edges: set[tuple[str, str]],
    api: TdxAdapter,
    *,
    spec_title: str = SPEC_TITLE_DEFAULT,
    index_timeout_seconds: int = INDEX_RETRY_TIMEOUT_SECONDS,
    sleeper=time.sleep,
    clock=time.monotonic,
    confirm_release=None,
) -> None:
    ensure_schema(connection)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(hashtext('reqsync_requirements_sync'))")

    try:
        db_nodes, db_edge_ids = load_state(connection)
        db_edges = set(db_edge_ids)
        db_edge_positions = load_edge_positions(connection)
        old_ids = {
            internalid: record["3dxid"]
            for internalid, record in db_nodes.items()
            if record["3dxid"] is not None
        }
        historical_id_to_internal = load_historical_ids(connection)
        historical_id_to_internal.update(
            {object_id: internalid for internalid, object_id in old_ids.items()}
        )

        specification_created = ROOT_SPEC_ID not in db_nodes
        if specification_created:
            if db_nodes:
                raise RuntimeError(
                    "Database contains requirement mappings but no root "
                    "specification mapping; refusing to create a second structure"
                )
            spec_id = api.create_specification(spec_title)
            if not spec_id:
                raise RuntimeError("3DEXPERIENCE returned an empty specification ID")
            persist_mapping(
                connection,
                ROOT_SPEC_ID,
                spec_id,
                spec_title,
                "Requirement Specification",
                active=True,
                release_pending=True,
            )
            db_nodes[ROOT_SPEC_ID] = {
                "3dxid": spec_id,
                "content": spec_title,
                "object_type": "Requirement Specification",
                "active": True,
                "release_pending": True,
            }
            old_ids[ROOT_SPEC_ID] = spec_id
            historical_id_to_internal[spec_id] = ROOT_SPEC_ID
            LOGGER.info("Created root specification %s (%s)", spec_title, spec_id)

        plan = plan_changes(
            nodes, edges, db_nodes, db_edge_ids, db_edge_positions
        )
        if specification_created:
            plan["to_revise"].discard(ROOT_SPEC_ID)

        stage_workbook_state(connection, nodes, edges)
        created_ids = _create_missing_nodes(
            connection, api, nodes, plan["created"]
        )
        for internalid, object_id in created_ids.items():
            node = nodes[internalid]
            db_nodes[internalid] = {
                "3dxid": object_id,
                "content": node.content
                if node.object_type == "Requirement"
                else node.display_title,
                "object_type": node.object_type,
                "active": True,
                "release_pending": True,
            }
        active_ids = {
            internalid: record["3dxid"]
            for internalid, record in db_nodes.items()
            if record["3dxid"] is not None
        }
        active_ids.update(created_ids)

        for internalid, node in nodes.items():
            if internalid in db_nodes and not db_nodes[internalid]["active"]:
                content = (
                    node.content
                    if node.object_type == "Requirement"
                    else node.display_title
                )
                persist_mapping(
                    connection,
                    internalid,
                    active_ids[internalid],
                    content,
                    node.object_type,
                    active=True,
                    release_pending=db_nodes[internalid]["release_pending"],
                )
                db_nodes[internalid]["active"] = True

        revision_ids = _revise_nodes(
            connection,
            api,
            nodes,
            db_nodes,
            plan["to_revise"],
            active_ids,
            plan["target_edges"],
            plan["direct_changes"],
            plan["title_changes"],
        )
        if ROOT_SPEC_ID in plan["to_revise"] and not specification_created:
            old_spec_id = active_ids[ROOT_SPEC_ID]
            revisions = api.revise_specification(old_spec_id)
            _ensure_id_map(revisions, [old_spec_id], "specification revisions")
            new_spec_id = revisions[old_spec_id]
            active_ids[ROOT_SPEC_ID] = new_spec_id
            persist_mapping(
                connection,
                ROOT_SPEC_ID,
                new_spec_id,
                db_nodes[ROOT_SPEC_ID]["content"],
                "Requirement Specification",
                active=True,
                release_pending=True,
            )
            db_nodes[ROOT_SPEC_ID]["release_pending"] = True
            db_nodes[ROOT_SPEC_ID]["3dxid"] = new_spec_id
            revision_ids.add(ROOT_SPEC_ID)
            LOGGER.info(
                "Revised root specification: %s -> %s", old_spec_id, new_spec_id
            )

        for internalid in plan["removed"]:
            if db_nodes[internalid]["active"]:
                _set_active_state(connection, internalid, False)
                db_nodes[internalid]["active"] = False

        parents_to_reconcile = {
            parent_id
            for parent_id, _ in plan["edge_changes"]
            if parent_id == ROOT_SPEC_ID or parent_id in nodes
        }
        parents_to_reconcile.update(revision_ids)
        parents_to_reconcile.update(
            parent_id
            for (parent_id, _), connection_id in db_edge_ids.items()
            if connection_id is None
            and (
                parent_id == ROOT_SPEC_ID
                or parent_id in nodes
            )
        )
        parents_to_reconcile.update(
            parent_id
            for parent_id, _ in plan["target_edges"]
            if parent_id in created_ids
        )
        connection_ids = _reconcile_relations(
            connection,
            api,
            nodes,
            db_nodes,
            db_edges,
            plan["target_edges"],
            parents_to_reconcile,
            active_ids,
            old_ids,
            historical_id_to_internal,
            set(created_ids) | ({ROOT_SPEC_ID} if specification_created else set()),
            index_timeout_seconds=index_timeout_seconds,
            sleeper=sleeper,
            clock=clock,
        )
        persist_edges(
            connection, plan["target_edges"], connection_ids, nodes
        )

        _release_pending_objects(
            connection,
            api,
            nodes,
            db_nodes,
            active_ids,
            plan["target_edges"],
            confirm_release=confirm_release,
        )
        LOGGER.info(
            "Synchronization complete: %d workbook object(s), %d relationship(s)",
            len(nodes),
            len(edges),
        )
    finally:
        try:
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_unlock(hashtext('reqsync_requirements_sync'))"
                )
            connection.commit()
        except psycopg2.Error as error:
            LOGGER.warning("Could not release the PostgreSQL sync lock cleanly: %s", error)
            connection.rollback()


def _configure_logging(log_file: str, log_level: str) -> None:
    level = getattr(logging, log_level.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"Invalid log level: {log_level}")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
        force=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize a requirements workbook to 3DEXPERIENCE"
    )
    parser.add_argument("--file", default="requirements_import.xlsx")
    parser.add_argument("--sheet")
    parser.add_argument("--spec-title", default=SPEC_TITLE_DEFAULT)
    parser.add_argument("--db-env-file", default="deploy/.env")
    parser.add_argument("--log-file", default="sync_requirements.log")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    try:
        _configure_logging(args.log_file, args.log_level)
        nodes, edges = parse_requirement_structure(args.file, args.sheet)
        LOGGER.info("Read %d objects and %d relationships from %s", len(nodes), len(edges), args.file)
        connection = connect_to_database(args.db_env_file)
        try:
            synchronize(
                connection,
                nodes,
                edges,
                TdxAdapter.from_tdxoperations(),
                spec_title=args.spec_title,
            )
        finally:
            connection.close()
        return 0
    except Exception:
        LOGGER.exception("Synchronization failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
