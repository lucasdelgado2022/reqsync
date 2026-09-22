import os
import re
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

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


# --- 3DEXPERIENCE Service Stub ---
# Replace these stubs with your actual 3DEXPERIENCE REST Web Services calls
# (e.g., /resources/v1/modeler/dseng/dseng:EngItem or Requirement Modeler APIs)
class ThreeDXClient:
    def __init__(self, base_url="https://3dx.internal.net/3dspace"):
        self.base_url = base_url

    def create_requirement(self, internal_id: str, content: str, parent_3dx_id: str | None) -> str:
        """
        Creates a new requirement object in 3DX and attaches it under parent_3dx_id.
        Returns the generated 3DX physicalId / object ID.
        """
        print(f"[3DX API] Creating Requirement '{internal_id}' (Parent 3DX: {parent_3dx_id})")
        # Example: response = requests.post(...)
        # return response.json()["data"][0]["id"]
        generated_id = f"3DX-PHYS-{internal_id.replace('.', '_')}-REV-A.1"
        return generated_id

    def revise_requirement(self, old_3dx_id: str, internal_id: str, content: str, parent_3dx_id: str | None) -> str:
        """
        Revises the requirement in 3DX, updates the content,
        and re-links to parent if the structure requires it.
        Returns the new revision's 3DX physicalId.
        """
        print(f"[3DX API] Revising '{old_3dx_id}' for '{internal_id}' (Parent 3DX: {parent_3dx_id})")
        # Example: response = requests.post(f".../revise/{old_3dx_id}")
        revised_id = f"{old_3dx_id.rsplit('.', 1)[0]}.2"
        return revised_id


# --- Core Hierarchy Utility ---
def extract_parent_id(internal_id: str) -> str | None:
    """
    Extracts parent ID from dot notation.
    '1.2.1' -> '1.2'
    '1'     -> None
    """
    parts = str(internal_id).strip().split(".")
    if len(parts) > 1:
        return ".".join(parts[:-1])
    return None


def sort_key_hierarchy(internal_id: str):
    """
    Ensures natural numerical sorting by depth:
    '1', '1.1', '1.2', '1.2.1', '1.10', etc.
    """
    return [int(p) if p.isdigit() else p for p in str(internal_id).strip().split(".")]


# --- Main Sync Processor ---
def sync_requirements_from_excel(excel_path: str):
    threedx = ThreeDXClient()
    df = pd.read_excel(excel_path)

    # Standardize column headers
    df.columns = [c.strip().lower() for c in df.columns]
    if "internalid" not in df.columns or "content" not in df.columns:
        raise ValueError("Excel file must contain 'internalid' and 'content' columns.")

    # Clean IDs and content
    df["internalid"] = df["internalid"].astype(str).str.strip()
    df["content"] = df["content"].fillna("").astype(str).str.strip()

    # Sort so parents are ALWAYS processed before children
    df["sort_order"] = df["internalid"].apply(sort_key_hierarchy)
    df = df.sort_values(by="sort_order").drop(columns=["sort_order"])

    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    try:
        for _, row in df.iterrows():
            internal_id = row["internalid"]
            incoming_content = row["content"]
            parent_internal_id = extract_parent_id(internal_id)

            # 1. Fetch parent's 3DX ID if parent exists
            parent_3dx_id = None
            if parent_internal_id:
                cursor.execute(
                    'SELECT "3dxid" FROM id_mappings WHERE internalid = %s;',
                    (parent_internal_id,)
                )
                parent_row = cursor.fetchone()
                if parent_row:
                    parent_3dx_id = parent_row["3dxid"]
                else:
                    print(f"[WARN] Parent '{parent_internal_id}' not found in DB for child '{internal_id}'.")

            # 2. Check current state of this requirement in the DB
            cursor.execute(
                'SELECT "3dxid", content, parent_id FROM id_mappings WHERE internalid = %s;',
                (internal_id,)
            )
            existing_record = cursor.fetchone()

            # --- Scenario 1: New Requirement ---
            if existing_record is None:
                new_3dx_id = threedx.create_requirement(internal_id, incoming_content, parent_3dx_id)

                cursor.execute(
                    """
                    INSERT INTO id_mappings (internalid, "3dxid", parent_id, content)
                    VALUES (%s, %s, %s, %s);
                    """,
                    (internal_id, new_3dx_id, parent_internal_id, incoming_content)
                )
                print(f"[SUCCESS] Created and mapped: {internal_id} -> {new_3dx_id}")

            # --- Scenario 2 & 3: Requirement already exists ---
            else:
                existing_content = existing_record["content"] or ""
                old_3dx_id = existing_record["3dxid"]

                # Content unchanged -> Do nothing
                if existing_content.strip() == incoming_content.strip():
                    print(f"[SKIP] Unchanged: {internal_id}")
                    continue

                # --- Scenario 3: Requirement Modified ---
                print(f"[EDIT DETECTED] Requirement '{internal_id}' content has changed.")
                new_revision_3dx_id = threedx.revise_requirement(
                    old_3dx_id, internal_id, incoming_content, parent_3dx_id
                )

                cursor.execute(
                    """
                    UPDATE id_mappings
                    SET "3dxid" = %s,
                        content = %s,
                        parent_id = %s
                    WHERE internalid = %s;
                    """,
                    (new_revision_3dx_id, incoming_content, parent_internal_id, internal_id)
                )
                print(f"[SUCCESS] Revised: {internal_id} -> {new_revision_3dx_id}")

        conn.commit()
        print("\nAll requirements processed and synchronized successfully.")

    except Exception as e:
        conn.rollback()
        print(f"\n[ERROR] Transaction rolled back due to error: {e}")
        raise e
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    # Point to your test Excel file
    sync_requirements_from_excel("requirements.xlsx")