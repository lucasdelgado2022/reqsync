import pandas as pd

def parse_requirements_excel(file_path: str, sheet_name: str = 0) -> tuple[dict[str, str], set[tuple[str, str]]]:
    """
    Parses an Excel sheet expecting at least:
      - 'internalid': unique requirement identifier
      - 'content': requirement description / text
      - 'parent_ids': (optional) delimited list of parent IDs, e.g. "REQ_SYS_01, REQ_SYS_02"
      
    Returns:
      - excel_reqs:  {internalid: content}
      - excel_edges: {(parent_id, child_id)}
    """
    # Read as string to avoid auto-formatting issues (e.g., numeric IDs or dates)
    df = pd.read_excel(file_path, sheet_name=sheet_name, dtype=str)
    
    # Normalize column names: lowercase and stripped of whitespace
    df.columns = [str(col).strip().lower() for col in df.columns]

    required_cols = {"internalid", "content"}
    if not required_cols.issubset(df.columns):
        raise ValueError(f"Excel must contain columns: {required_cols}. Found: {list(df.columns)}")

    excel_reqs: dict[str, str] = {}
    excel_edges: set[tuple[str, str]] = set()

    has_parents = "parent_ids" in df.columns

    for _, row in df.iterrows():
        raw_id = row.get("internalid")
        if pd.isna(raw_id) or not str(raw_id).strip():
            continue  # Skip empty rows

        internal_id = str(raw_id).strip()
        raw_content = row.get("content")
        content = "" if pd.isna(raw_content) else str(raw_content).strip()

        excel_reqs[internal_id] = content

        # Process parent relationships
        if has_parents:
            raw_parents = row.get("parent_ids")
            if pd.notna(raw_parents) and str(raw_parents).strip():
                # Split by comma or semicolon
                delimiter = ";" if ";" in str(raw_parents) else ","
                parent_list = [p.strip() for p in str(raw_parents).split(delimiter) if p.strip()]

                for p in parent_list:
                    # Stored as (parent_id, child_id)
                    excel_edges.add((p, internal_id))

    return excel_reqs, excel_edges