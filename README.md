# reqsync

One-way synchronization of an Excel requirement hierarchy to 3DEXPERIENCE.
Excel is the source of truth; PostgreSQL stores current object mappings, active
parent-child usage IDs, and prior object and usage IDs.

## Workbook format

The selected worksheet must have these four headers (case-insensitive):

| Header | Meaning |
| --- | --- |
| `internalid` | Unique, stable workbook ID and the 3DEXPERIENCE title |
| `content` | Requirement description; ignored for chapters |
| `parent_ids` | Zero or more parent `internalid` values, separated by semicolons |
| `type` | `C` for Chapter; `R` or blank for Requirement |

Rows are processed in worksheet order. For each parent, its children are linked
in that same row order.

A row without parents must be a Chapter and is placed under the generated
Requirement Specification. Chapters can contain chapters or requirements;
requirements can contain requirements but not chapters. Requirements must
have a parent. Multiple parents are supported. Unknown IDs, duplicate IDs,
invalid types, and cyclic hierarchies are rejected before 3DEXPERIENCE changes
are made.

## Synchronization

The script validates the workbook before making 3DEXPERIENCE changes. On the
first run against an empty mapping database, it creates the root specification,
stages workbook IDs and relationships in PostgreSQL, creates the chapters and
requirements, stores their 3DEXPERIENCE IDs, creates the usage relationships,
and releases objects from the deepest level upwards, releasing the
specification last.

On later runs, it compares workbook content and relationships with PostgreSQL.
Changed requirements and affected ancestors are revised from the deepest level
up; relationships are then expanded, cleared, and recreated parent-by-parent
from the specification down. This restores children in worksheet order even
when revision inheritance or a link change rearranged the structure. Removed
workbook rows stay mapped as inactive objects but their links are removed from
the active specification structure. The current and immediately previous
3DEXPERIENCE object IDs are stored in `3dxid` and `previous_3dxid`.
New and revised objects are released after reconciliation.
Relationship expansions are retried when expected inherited links are not yet
indexed, waiting 10 seconds and increasing the interval by 10 seconds up to a
five-minute limit. If expected links remain missing, the run fails rather than
assuming they were removed. A later run resumes from the state persisted in
PostgreSQL.

Rows removed from the workbook are marked inactive in PostgreSQL; their
3DEXPERIENCE objects are not deleted. Their active relationships are removed
from the specification structure. Older 3DEXPERIENCE revisions are retained
as version history; the script does not delete 3DEXPERIENCE objects or
revisions.
Changing an existing object's type is rejected; use a new `internalid` to
represent a different object type. Unchanged runs do not scan 3DEXPERIENCE for
manual drift.

The root specification display name defaults to `SPEC_TITLE_DEFAULT` near the
top of `sync_requirements.py`; `--spec-title` can override it on a first run.
The root mapping key is the reserved `ROOT_SPEC_ID` in `excel_parser.py`, not
the display title. Existing specification titles are not renamed by later runs.
3DEXPERIENCE authentication settings are read by the existing API modules from
the root `.env`. PostgreSQL connection settings are read from `deploy/.env`.
The script applies the additive schema migration on startup; the corresponding
SQL is also available at `deploy/migrations/002-sync-history.sql` and
`deploy/migrations/003-current-previous-and-order.sql`. For a fresh database,
use `deploy/init/01-init-schema.sql` or `schema.sql`.

## Run

```bash
python3 sync_requirements.py
```

The default workbook is `requirements_import.xlsx`; the first worksheet is
used unless a sheet name is specified. Override the workbook, worksheet,
specification title, database environment file, or log settings with:

```bash
python3 sync_requirements.py \
  --file /path/to/requirements.xlsx \
  --sheet Requirements \
  --spec-title "Product Requirements" \
  --db-env-file deploy/.env \
  --log-file logs/import.log \
  --log-level DEBUG
```

Progress and errors are written to the selected log file and the console.
