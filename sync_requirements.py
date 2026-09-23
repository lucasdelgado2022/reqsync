import os
import psycopg2
from psycopg2.extras import execute_values
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

def get_or_create_root_specification(conn, spec_title="System Requirements Specification"):
    """
    Checks the database for an existing Root Specification.
    If it doesn't exist, creates it in 3DX using tdx.create_spec() and saves it to the DB.
    """
    with conn.cursor() as cur:
        # Check if we already created the specification in a previous run
        cur.execute("SELECT \"3dxid\" FROM id_mappings WHERE internalid = '__ROOT_SPEC__';")
        row = cur.fetchone()
        
        if row and row[0]:
            return row[0] # Return existing Spec ID
            
        # If not found, create it in 3DX!
        print(f"Root Specification not found in DB. Creating '{spec_title}' in 3DX...")
        new_spec_id = tdx.create_spec(spec_title)
        
        # Save the new Spec ID to the database so we never create it again
        cur.execute(
            'INSERT INTO id_mappings (internalid, "3dxid", content) VALUES (%s, %s, %s);',
            ('__ROOT_SPEC__', new_spec_id, spec_title)
        )
        conn.commit()
        
        return new_spec_id
def step_1_detect_changes(conn, excel_reqs: dict[str, str], excel_edges: set[tuple[str, str]]):
    """
    Analyzes differences between the database and the target Excel state.
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
    """
    Bubbles up revisions to any parent whose child was modified, added, or removed.
    """
    child_to_parents = defaultdict(set)
    for p, c in excel_edges:
        child_to_parents[c].add(p)

    to_revise = set(direct_content_change)

    for p, _ in edges_to_add:
        if p in db_nodes:
            to_revise.add(p)
    for p, _ in edges_to_remove:
        if p in db_nodes:
            to_revise.add(p)

    dirty_nodes = set(to_create) | set(to_revise)
    queue = list(dirty_nodes)

    while queue:
        curr = queue.pop(0)
        for parent in child_to_parents.get(curr, []):
            if parent in db_nodes and parent not in to_revise:
                to_revise.add(parent)
                queue.append(parent)

    return to_revise

def step_3_execute_elements_in_3dx(db_nodes, excel_reqs, to_create, to_revise):
    """
    Creates new elements and batches revisions for modified elements in 3DX.
    """
    active_3dx_ids = {k: v["3dxid"] for k, v in db_nodes.items()}
    
    created_map = {}
    if to_create:
        create_list = list(to_create)
        contents = [excel_reqs[cid] for cid in create_list]
        created_map = tdx.create_several_reqs(create_list, contents)
        active_3dx_ids.update(created_map)

    revised_map = {}
    if to_revise:
        revise_list = list(to_revise)
        old_3dx_ids = [db_nodes[rid]["3dxid"] for rid in revise_list]
        
        new_contents = [
            excel_reqs[rid] if excel_reqs.get(rid) != db_nodes[rid]["content"] else None
            for rid in revise_list
        ]
        
        rev_3dx_to_3dx = tdx.revise_several_reqs(old_3dx_ids, new_contents)
        
        for rid in revise_list:
            old_id = db_nodes[rid]["3dxid"]
            new_id = rev_3dx_to_3dx.get(old_id)
            if new_id:
                revised_map[rid] = new_id
                active_3dx_ids[rid] = new_id

    return active_3dx_ids, created_map, revised_map

def step_4_reconcile_global_structure(req_spec_3dx_id, parents_to_check, excel_edges, excel_reqs, active_3dx_ids):
    """
    Fetches the live 3DX tree and aligns it with the Excel structure.
    Routes req-req and spec-req connections to their respective API functions.
    """
    final_db_connections = {}
    id_3dx_to_internal = {v: k for k, v in active_3dx_ids.items()}
    
    # --- PART A: Fetch and Parse Live 3DX Tree ---
    current_3dx_tree = tdx.get_parent_structure(req_spec_3dx_id)
    
    current_req_req = {}   # {(p_int, c_int): connection_3dx_id}
    current_spec_req = {}  # {c_int: connection_3dx_id} (Parent is implicitly the Root Spec)

    for (p_3dx, c_3dx), conn_data in current_3dx_tree.items():
        c_int = id_3dx_to_internal.get(c_3dx)
        if not c_int:
            continue
            
        if p_3dx == req_spec_3dx_id or conn_data.get("type") == "spec-req":
            current_spec_req[c_int] = conn_data["connectionID"]
        else:
            p_int = id_3dx_to_internal.get(p_3dx)
            if p_int:
                current_req_req[(p_int, c_int)] = conn_data["connectionID"]

    # --- PART B: Standard Requirement-to-Requirement (req-req) ---
    del_parents_req = []
    del_relids_req = []
    to_relate_parents_req = []
    to_relate_children_lists_req = []

    # 1. Prune stale req-req links
    stale_edges = set(current_req_req.keys()) - excel_edges
    for p_int, c_int in stale_edges:
        if p_int in parents_to_check:
            del_parents_req.append(active_3dx_ids[p_int])
            del_relids_req.append(current_req_req[(p_int, c_int)])

    # 2. Add missing req-req links
    missing_edges = excel_edges - set(current_req_req.keys())
    missing_by_parent = defaultdict(list)
    for p_int, c_int in missing_edges:
        if p_int in parents_to_check:
            missing_by_parent[active_3dx_ids[p_int]].append(active_3dx_ids[c_int])

    for p_3dx, c_3dx_list in missing_by_parent.items():
        to_relate_parents_req.append(p_3dx)
        to_relate_children_lists_req.append(c_3dx_list)

    if del_parents_req:
        tdx.delete_several_relations(del_parents_req, del_relids_req)

    if to_relate_parents_req:
        new_links = tdx.relate_several_elements(to_relate_parents_req, to_relate_children_lists_req)
        for p_3dx, children_dict in new_links.items():
            p_int = id_3dx_to_internal.get(p_3dx)
            for c_3dx, rel_id in children_dict.items():
                c_int = id_3dx_to_internal.get(c_3dx)
                if p_int and c_int:
                    final_db_connections[(p_int, c_int)] = rel_id

    # 3. Retain verified existing req-req connections
    preserved_edges = excel_edges & set(current_req_req.keys())
    for p_int, c_int in preserved_edges:
        final_db_connections[(p_int, c_int)] = current_req_req[(p_int, c_int)]

    # --- PART C: Specification-to-Requirement (spec-req) ---
    all_excel_children = {c for p, c in excel_edges}
    desired_top_level = {req for req in excel_reqs.keys() if req not in all_excel_children}
    
    # 1. Prune stale spec-req links (auto-cloned by 3DX or removed in Excel)
    stale_top_level = set(current_spec_req.keys()) - desired_top_level
    del_parents_spec = []
    del_relids_spec = []
    
    for c_int in stale_top_level:
        del_parents_spec.append(req_spec_3dx_id)
        del_relids_spec.append(current_spec_req[c_int])
        
    if del_parents_spec:
        tdx.delete_several_relations_spec(del_parents_spec, del_relids_spec)

    # 2. Add missing spec-req links (newly created root requirements)
    missing_top_level = desired_top_level - set(current_spec_req.keys())
    
    if missing_top_level:
        missing_children_3dx = [active_3dx_ids[c] for c in missing_top_level]
        tdx.relate_several_elements_spec([req_spec_3dx_id], [missing_children_3dx])
        
    return final_db_connections

def step_5_persist_and_release(conn, excel_reqs, active_3dx_ids, to_create, to_revise, excel_edges, new_relation_records, db_edges):
    """
    Saves updated records and connection mappings to PostgreSQL, then releases active items in 3DX.
    """
    with conn.cursor() as cur:
        # Insert New
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

        # Update Revised
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

        # Sync Connections
        parents_cleared = set(to_revise) | set(to_create)
        if parents_cleared:
            cur.execute(
                'DELETE FROM requirement_connections WHERE parent_id = ANY(%s);',
                (list(parents_cleared),)
            )

        records_to_insert = []
        for p, c in excel_edges:
            if (p, c) in new_relation_records:
                records_to_insert.append((p, c, new_relation_records[(p, c)]))
            elif (p, c) in db_edges and p not in parents_cleared:
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

    # Final Release in 3DX
    items_to_release = [active_3dx_ids[i] for i in set(to_create) | set(to_revise)]
    if items_to_release:
        tdx.release_serveral_reqs(items_to_release)

def sync_excel_to_3dx(conn, excel_reqs: dict[str, str], excel_edges: set[tuple[str, str]], req_spec_3dx_id: str):
    """
    Master runner function.
    """
    diff = step_1_detect_changes(conn, excel_reqs, excel_edges)
    
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

    active_3dx_ids, created_map, revised_map = step_3_execute_elements_in_3dx(
        diff["db_nodes"],
        excel_reqs,
        diff["to_create"],
        to_revise
    )

    parents_to_check = set(diff["to_create"]) | to_revise
    
    new_relations = step_4_reconcile_global_structure(
        req_spec_3dx_id,
        parents_to_check,
        excel_edges,
        excel_reqs,
        active_3dx_ids
    )

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

if __name__ == "__main__":
    conn = get_db_connection()
    
    try:
        print("\n--- Running Synchronization ---")
        
        # 1. Automatically get or create the Root Specification
        root_spec_id = get_or_create_root_specification(conn, "Main Excel Requirement Specification")
        print(f"Using Root Specification ID: {root_spec_id}")
        
        # 2. Parse Excel
        reqs_v1, edges_v1 = parse_requirements_excel("requirements_v1.xlsx")
        
        # 3. Run Sync
        sync_excel_to_3dx(conn, reqs_v1, edges_v1, root_spec_id)
        
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()