import os
import re
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from dotenv import load_dotenv
import tdxoperations as tdx
from pathlib import Path
from excel_parser import parse_requirements_excel
from collections import defaultdict


# --- Configuration & DB Connection ---
env_path = Path(__file__).resolve().parent / "deploy" / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()  # Fallback to current directory's .env

def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB", "mapping_db"),
        user=os.getenv("POSTGRES_USER", "db_user"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
    )


def step_1_detect_changes(conn, excel_reqs: dict[str, str], excel_edges: set[tuple[str, str]]):
    """
    excel_reqs:  {internalid: content}
    excel_edges: {(parent_id, child_id)}
    """
    cursor = conn.cursor()
    
    # 1. Fetch current database state
    cursor.execute('SELECT internalid, "3dxid", content FROM id_mappings;')
    db_nodes = {row[0]: {"3dxid": row[1], "content": row[2]} for row in cursor.fetchall()}
    
    cursor.execute('SELECT parent_id, child_id, connection_3dx_id FROM requirement_connections;')
    db_edges = {}
    for parent_id, child_id, rel_id in cursor.fetchall():
        db_edges[(parent_id, child_id)] = rel_id

    # 2. Classify nodes
    to_create = set()
    direct_content_change = set()
    
    for int_id, content in excel_reqs.items():
        if int_id not in db_nodes:
            to_create.add(int_id)
        elif db_nodes[int_id]["content"] != content:
            direct_content_change.add(int_id)

    # 3. Classify edges
    db_edge_pairs = set(db_edges.keys())
    edges_to_add = excel_edges - db_edge_pairs
    edges_to_remove = db_edge_pairs - excel_edges

    return {
        "db_nodes": db_nodes,
        "db_edges": db_edges,
        "to_create": to_create,
        "direct_content_change": direct_content_change,
        "edges_to_add": edges_to_add,
        "edges_to_remove": edges_to_remove
    }
    
def step_2_propagate_revisions(db_nodes, to_create, direct_content_change, edges_to_add, edges_to_remove, excel_edges):
    # Map each child to all parents (both existing DB and incoming Excel)
    child_to_parents = defaultdict(set)
    for p, c in excel_edges:
        child_to_parents[c].add(p)

    # Start with nodes that are already in DB and need direct revision
    to_revise = set(direct_content_change)

    # Parents directly affected by edge additions/removals
    for p, _ in edges_to_add:
        if p in db_nodes:
            to_revise.add(p)
    for p, _ in edges_to_remove:
        if p in db_nodes:
            to_revise.add(p)

    # Propagate upward: any parent of a node being created or revised must be revised
    dirty_nodes = set(to_create) | set(to_revise)
    queue = list(dirty_nodes)

    while queue:
        curr = queue.pop(0)
        for parent in child_to_parents.get(curr, []):
            # Only revise parents that exist in DB and haven't been marked yet
            if parent in db_nodes and parent not in to_revise:
                to_revise.add(parent)
                queue.append(parent)

    return to_revise

def step_3_execute_elements_in_3dx(db_nodes, excel_reqs, to_create, to_revise):
    active_3dx_ids = {k: v["3dxid"] for k, v in db_nodes.items()}
    
    # 1. Batch Create
    created_map = {}
    if to_create:
        create_list = list(to_create)
        contents = [excel_reqs[cid] for cid in create_list]
        created_map = tdx.create_several_reqs(create_list, contents)
        active_3dx_ids.update(created_map)

    # 2. Batch Revise
    revised_map = {}
    if to_revise:
        revise_list = list(to_revise)
        old_3dx_ids = [db_nodes[rid]["3dxid"] for rid in revise_list]
        
        # If content didn't change in Excel, pass None to retain old content
        new_contents = [
            excel_reqs[rid] if excel_reqs.get(rid) != db_nodes[rid]["content"] else None
            for rid in revise_list
        ]
        
        # revise_several_reqs returns {old_3dxid: new_3dxid}
        rev_3dx_to_3dx = tdx.revise_several_reqs(old_3dx_ids, new_contents)
        
        for rid in revise_list:
            old_id = db_nodes[rid]["3dxid"]
            new_id = rev_3dx_to_3dx[old_id]
            revised_map[rid] = new_id
            active_3dx_ids[rid] = new_id

    return active_3dx_ids, created_map, revised_map

def step_4_rewire_relations(db_nodes, db_edges, active_3dx_ids, to_create, to_revise, excel_edges, edges_to_remove):
    # 1. Delete relations explicitly removed
    del_parents = []
    del_relids = []
    for (p, c) in edges_to_remove:
        # If parent was revised, its old relations are obsolete on the old revision anyway.
        # But if not revised, we delete the relation explicitly:
        if p not in to_revise and (p, c) in db_edges:
            rel_id = db_edges[(p, c)]
            if rel_id:
                del_parents.append(active_3dx_ids[p])
                del_relids.append(rel_id)

    if del_parents:
        tdx.delete_several_relations(del_parents, del_relids)

    # 2. Collect edges that must be re-linked
    # Any parent newly created or revised must be linked to all of its children in excel_edges
    parents_to_link = set(to_create) | set(to_revise)
    
    parent_child_map = defaultdict(list)
    for p, c in excel_edges:
        if p in parents_to_link:
            parent_child_map[p].append(c)

    new_relation_records = {} # {(p_id, c_id): rel_3dx_id}

    if parent_child_map:
        parents_3dx = []
        children_3dx_lists = []
        parent_order = []

        for p_id, child_ids in parent_child_map.items():
            parent_order.append(p_id)
            parents_3dx.append(active_3dx_ids[p_id])
            children_3dx_lists.append([active_3dx_ids[cid] for cid in child_ids])

        # relate_several_elements returns: {"parent_3dxid": {"child_3dxid": "rel_id"}}
        raw_res = tdx.relate_several_elements(parents_3dx, children_3dx_lists)

        # Invert active_3dx_ids to map back to internal IDs
        id_3dx_to_internal = {v: k for k, v in active_3dx_ids.items()}

        for p_3dx, child_dict in raw_res.items():
            p_int = id_3dx_to_internal.get(p_3dx)
            for c_3dx, rel_id in child_dict.items():
                c_int = id_3dx_to_internal.get(c_3dx)
                if p_int and c_int:
                    new_relation_records[(p_int, c_int)] = rel_id

    return new_relation_records

def step_5_persist_and_release(conn, excel_reqs, active_3dx_ids, to_create, to_revise, excel_edges, new_relation_records, db_edges):
    with conn.cursor() as cur:
        # 1. Insert newly created requirements into id_mappings
        if to_create:
            insert_data = [
                (cid, active_3dx_ids[cid], excel_reqs[cid])
                for cid in to_create
            ]
            execute_values(
                cur,
                'INSERT INTO id_mappings (internalid, "3dxid", content) VALUES %s;',
                insert_data
            )

        # 2. Update revised requirements in id_mappings
        if to_revise:
            update_data = [
                (active_3dx_ids[rid], excel_reqs[rid], rid)
                for rid in to_revise
            ]
            execute_values(
                cur,
                'UPDATE id_mappings AS m SET "3dxid" = v.new_3dxid, content = v.content '
                'FROM (VALUES %s) AS v(new_3dxid, content, internalid) '
                'WHERE m.internalid = v.internalid;',
                update_data
            )

        # 3. Synchronize requirement_connections
        # Remove old/stale connections for revised parents and removed edges
        parents_cleared = set(to_revise) | set(to_create)
        if parents_cleared:
            cur.execute(
                'DELETE FROM requirement_connections WHERE parent_id = ANY(%s);',
                (list(parents_cleared),)
            )

        # Insert new/updated relations
        records_to_insert = []
        for p, c in excel_edges:
            if (p, c) in new_relation_records:
                records_to_insert.append((p, c, new_relation_records[(p, c)]))
            elif (p, c) in db_edges:
                records_to_insert.append((p, c, db_edges[(p, c)]))

        if records_to_insert:
            execute_values(
                cur,
                'INSERT INTO requirement_connections (parent_id, child_id, connection_3dx_id) '
                'VALUES %s ON CONFLICT (child_id, parent_id) '
                'DO UPDATE SET connection_3dx_id = EXCLUDED.connection_3dx_id;',
                records_to_insert
            )

    conn.commit()

    # 4. Final Release in 3DX
    items_to_release = [active_3dx_ids[i] for i in set(to_create) | set(to_revise)]
    if items_to_release:
        tdx.release_serveral_reqs(items_to_release)

def sync_excel_to_3dx(conn, excel_reqs: dict[str, str], excel_edges: set[tuple[str, str]]):
    """
    Master runner function.
    """
    # 1. Diff analysis
    diff = step_1_detect_changes(conn, excel_reqs, excel_edges)
    
    # 2. Bubble up revisions to all affected parents
    to_revise = step_2_propagate_revisions(
        diff["db_nodes"],
        diff["to_create"],
        diff["direct_content_change"],
        diff["edges_to_add"],
        diff["edges_to_remove"],
        excel_edges
    )
    
    if not diff["to_create"] and not to_revise and not diff["edges_to_remove"]:
        print("Everything is up to date.")
        return

    # 3. Create & Revise elements in 3DX
    active_3dx_ids, created_map, revised_map = step_3_execute_elements_in_3dx(
        diff["db_nodes"],
        excel_reqs,
        diff["to_create"],
        to_revise
    )

    # 4. Re-link relations in 3DX
    new_relations = step_4_rewire_relations(
        diff["db_nodes"],
        diff["db_edges"],
        active_3dx_ids,
        diff["to_create"],
        to_revise,
        excel_edges,
        diff["edges_to_remove"]
    )

    # 5. Persist to DB & Release all touched items in 3DX
    step_5_persist_and_release(
        conn,
        excel_reqs,
        active_3dx_ids,
        diff["to_create"],
        to_revise,
        excel_edges,
        new_relations,
        diff["db_edges"]
    )
    
    print(f"Sync complete: {len(diff['to_create'])} created, {len(to_revise)} revised/relinked.")


conn = get_db_connection()
try:
    # Run 1: Initial upload
    print("\n--- RUN 1: Baseline Sync ---")
    reqs_v1, edges_v1 = parse_requirements_excel("requirements_v2.xlsx")
    sync_excel_to_3dx(conn, reqs_v1, edges_v1)

    

finally:
    conn.close()