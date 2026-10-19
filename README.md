# reqsync

One-way synchronization of a typed Excel requirement hierarchy to 3DEXPERIENCE.

## Workbook format

The selected worksheet must contain `internalid` and `content` columns, plus
`parent_ids` and optionally `type`.

- `type = C` identifies a Chapter.
- `type = R`, an empty cell, or no `type` column identifies a Requirement.
- A chapter's `content` is its 3DEXPERIENCE title.
- A requirement's `internalid` is its 3DEXPERIENCE title, and `content` is
  its description.
- `parent_ids` is a comma- or semicolon-delimited list of parent identifiers.
  A chapter with no parent is placed under the generated Requirement
  Specification. A requirement must have a parent.
- Chapters may contain chapters or requirements. Requirements may contain
  requirements. Requirements cannot contain chapters.

Identifiers must be unique. Unknown parents and cyclic hierarchies are rejected
before any 3DEXPERIENCE changes are made.

## Synchronization behavior

The database stores each Excel identifier's current 3DEXPERIENCE ID, object
type, and source content, plus the relation ID for each parent-child edge. The
root Requirement Specification uses the reserved identifier `__ROOT_SPEC__`.
Configure the database connection in `deploy/.env`. Create the database schema
with `deploy/init/01-init-schema.sql` (or apply the matching `schema.sql`).

When an object or its child links change, the synchronizer revises the affected
object and its ancestors. It revises from the deepest children up through the
hierarchy, one level at a time, never revising a parent and child in the same
operation, and respects
the 3DEXPERIENCE 100-object revision limit. It expands affected chapters to
reconstruct their complete descendant usage tree; requirement relations are
never expanded through a Requirement endpoint. The root Requirement
Specification is expanded when its links need reconciliation. Expansions wait
and retry when the platform reports that an object is not yet indexed or a
successful response is missing previously recorded relations. If recorded
relations remain absent after retries, synchronization stops instead of
assuming those links were removed. Existing usage relations are replaced only
when they do not point to the desired active child revision. New and revised
objects are released from the leaves upwards, with the Requirement
Specification released last.

When the database and workbook show no changes, the synchronizer also compares
the live specification/chapter expansions with the expected active object IDs.
If a previous run left extra or missing links in 3DEXPERIENCE, it revises the
affected parent chain and reconciles those relations on the new revisions.
The synthetic root specification mapping is persisted along with the workbook
objects so a revised specification ID remains aligned with its chapter links.
When revisions are needed, requirements are revised from the deepest child
upwards before their parents (with each hierarchy level revised separately),
then their relations are reconciled from the specification down. Stale usages
found through an inherited parent revision are compared by child object ID,
not by the parent revision ID. If the child is still the desired revision, the
recreated usage is retained; if the child has a different active revision, the
usage is replaced. Duplicate usages to the same child are detected and reduced
to one. Chapter expansions are refreshed after relation changes so descendant
links are read again before being reconciled.
After upgrading from a version that revised the root without persisting its
new ID, repair the `__ROOT_SPEC__` row in `id_mappings` to the latest released
specification ID shown by the last successful sync log before running again.

Existing databases need an `object_type` column. The synchronizer adds the
column if needed and identifies the root specification, but will stop if an
existing workbook mapping has no recorded type. Backfill each such row with
its actual 3DEXPERIENCE type (`Chapter` or `Requirement`) before synchronizing;
the type cannot safely be inferred from the workbook for objects created by an
older, untyped importer.

## Run

```bash
python sync_requirements.py
```

The default input is `requirements_v1.xlsx`, worksheet 1. Override the file,
worksheet, or generated specification title with:

```bash
python sync_requirements.py \
  --file /path/to/requirements.xlsx \
  --sheet Requirements \
  --spec-title "Product Requirements"
```

`--spec-title` is used only when the database does not yet have a root
specification; it does not rename an existing 3DEXPERIENCE object.

Each run writes timestamped progress and error details to
`sync_requirements.log` in the current directory and also prints them to the
console. To choose a different log path or increase detail:

```bash
python sync_requirements.py --log-file logs/import.log --log-level DEBUG
```
