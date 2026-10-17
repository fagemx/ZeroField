# Durable Head / Limb execution

OpenBench schedules persisted tasks; registered workers perform inference or media
generation on their own machine. The server does not execute arbitrary commands.
All endpoints return JSON. Member POST requests need `X-Requested-With: projects`
and normal member authentication. Worker endpoints use only the issued
`Authorization: Bearer <worker-token>`; an application login token is not a worker token.

## Register a worker

An administrator calls `POST /projects/api/limbs/register`:

```json
{"name":"Local text worker","capabilities":["llm"],"project_slug":"demo"}
```

Alternatively provide `allowed_projects: ["demo", "other"]`. Capabilities are
`llm`, `image_gen`, `video_gen`, `media_assemble`. Returns `{limb, token}`. Copy
the token immediately: only its SHA-256 hash is stored. Registration grants access
to that project's model inputs. `GET /projects/api/limbs?project_slug=demo` lists
nonsecret worker metadata; `POST /projects/api/limbs/revoke {limb_id}` disables a
worker and immediately prevents further claims, renewal, upload and completion.

For a local protocol acceptance test (no provider calls or external costs):

```powershell
$env:OPENBENCH_LIMB_TOKEN = '<issued-token>'
python examples/worker.py --url http://127.0.0.1:3020 --once
```

This example echoes the task prompt. `--asset path/to/image.png` uploads an
existing media file instead. The example renews leases while working. For actual
models and assembly, use `openbench-worker --config examples/worker.example.json`:
the packaged runtime includes OpenAI-compatible, ComfyUI, HTTP bridge, speech and
FFmpeg adapters. See [WORKERS.md](WORKERS.md) for configuration and bridge contracts.

## Persist a DAG

`GET /projects/api/<slug>/tabs/<key>/flow` returns `{definition, revision}`.
An unsaved flow returns empty nodes/edges with revision 0. `POST` to the same
URL saves `{definition, revision}`; a stale revision returns HTTP 409.

```json
{
  "revision": 0,
  "definition": {
    "nodes": [
      {"id":"draft","title":"Write shot prompt","x":40,"y":80,
       "capability":"llm","prompt":"Write a camera prompt for this shot.",
       "input_tabs":["script","shots"],
       "target":{"tab_key":"shots","row_id":"b_example","col_index":3},
       "write_mode":"proposal"},
      {"id":"image","title":"Generate first frame","x":380,"y":80,
       "capability":"image_gen","prompt":"Generate from the approved draft.",
       "input_tabs":["shots"],
       "target":{"tab_key":"shots","row_id":"b_example","col_index":4}}
    ],
    "edges":[{"source":"draft","target":"image"}]
  }
}
```

Optional `limb_id` binds a node to one registered worker. A node without a target
stores its JSON output as an intermediate result. Targets support existing table
cells, structured table edits, or document text with `kind: "doc"`.
The graph rejects cycles, duplicate ids, missing nodes and unsupported capabilities.
The saved definition and revision are copied into each run; editing the canvas
never changes an already-running graph.

### Once, rows and aggregate scopes

Use explicit scopes for a complete script-to-film pipeline:

```json
{
  "nodes": [
    {"id":"split","scope":"once","capability":"llm",
     "input_tabs":["script"],"target":{"tab_key":"shots"},
     "prompt":"Return new_rows arrays matching target_tables headers."},
    {"id":"image","scope":"rows","capability":"image_gen",
     "row_source":{"tab_key":"shots","table_id":"b_shots"},
     "target":{"tab_key":"shots","col_index":4}},
    {"id":"audio","scope":"rows","capability":"media_assemble",
     "row_source":{"tab_key":"shots","table_id":"b_shots"},
     "target":{"tab_key":"shots","col_index":6}},
    {"id":"video","scope":"rows","capability":"video_gen",
     "row_source":{"tab_key":"shots","table_id":"b_shots"},
     "target":{"tab_key":"shots","col_index":5}},
    {"id":"assemble","scope":"aggregate","capability":"media_assemble",
     "input_tabs":["shots"],"target":{"tab_key":"delivery","kind":"doc"}}
  ],
  "edges":[{"source":"split","target":"image"},
           {"source":"split","target":"audio"},
           {"source":"image","target":"video"},
           {"source":"video","target":"assemble"},
           {"source":"audio","target":"assemble"}]
}
```

`once` and `aggregate` create exactly one task with an empty `row_id`. `rows`
requires `row_source.tab_key`; optional `table_id` chooses a worksheet/table.
Without `table_id`, rows from all tables appear in document/table order. Optional
`status` is a string or array of exact rendered cell values; `status_col` is a
zero-based column. Without a column, matching any cell includes the row. Status
capsules use their current field values, without display brackets.

The scheduler expands a node only when **all tasks of every predecessor** have
succeeded, including proposal approval. This is a stage barrier: tasks within
one stage and independent fork branches can run concurrently. After a splitter's
approved `new_rows` write, row nodes read those persisted rows. The first use of
each identical row source freezes its stable row IDs and table order for that
run; later stages read current values for those same IDs. At most 200 selected
rows are expanded per row source. Zero matching rows is a persisted, successful
empty stage; downstream aggregate still runs once with empty `rows` and
`predecessor_tasks`. An aggregate worker should handle that case explicitly.

Expansion state is in `run.execution`, separate from the immutable definition.
`expanded` maps each expanded node to its ordered row IDs (including an empty
array); `active_nodes` lists the selected subgraph; `errors` reports source or
target expansion failures. A missing source or failed task produces a terminal
failure when other active work finishes, not a permanently blocked run. Retry
preserves successful tasks and frozen expansion sets. Cancellation invalidates
leases and dismisses pending proposals. Repeated polling/restarts cannot create
duplicate tasks because expansion and task insertion share the run lock and the
database enforces `(run_id,node_id,row_id)` uniqueness.

Nodes without `scope` retain the original behavior: one task per explicitly
selected row, or one task when no rows are supplied. Entirely legacy graphs keep
their original per-row dependency scheduling. In a mixed graph, legacy nodes
retain that task cardinality and use stage barriers.

For a redraw without repeating the splitter:

```json
{"start_node_id":"image","row_ids":["b_shot12"],"target_tab":"shots"}
```

Only the selected start node and its descendants execute; ancestor edges are
ignored, so existing sheet values provide the redraw's initial inputs. This is a
new run, not mutation of the previous run. Optional run-level `row_source`
overrides row sources for this run, for example
`{"tab_key":"shots","status_col":7,"status":["未開始"]}`. Selection and status
filter intersect. Aggregate output for a selected-row run includes those selected
rows only. Start a new full-source aggregate run to assemble the entire film.
An aggregate with `row_source` also freezes and applies that source's selection
and status filter when started directly, even when no row stage executes first.
Its source tab's structured rows and rendered text use the same filtered set.
With only `row_ids` and `target_tab`, the run records `selection_tabs` and filters
that source tab in both structured and rendered inputs; unrelated reference tabs
remain complete even when the aggregate itself has no `row_source`.

### Document text delivery

Use `target:{"tab_key":"weekly-report","kind":"doc","mode":"append"}` with
`output:{"text":"Weekly report..."}`. `mode` defaults to `append`; `replace`
replaces the document's top-level blocks. Text lines become plain paragraphs;
this interface does not interpret HTML or arbitrary editor JSON. An uploaded
`asset_url` can accompany or replace text and is written as a clickable editor
link mark after `safe_href` validation (not literal Markdown text).
The existing `table_edit` ProposalCard transports the prepared document block
operations and text preview. Direct mode uses the same application path.
Document writes check the claim-time revision, active locks and creator
permission, then create normal revision history. A changed document requires a
fresh attempt. Maximum text is 100,000 characters and 200 block operations.

## Run, observe, cancel and retry

* `POST .../flow/runs {}` starts the saved graph.
* `POST .../flow/runs {"row_ids":["b_shot1","b_shot2"],"target_tab":"shots"}`
  creates one graph execution per selected row. A node's row target is replaced
  with that selected row. `target_tab` supplies a missing target tab.
* `GET .../flow/runs` returns `{runs}` (latest 50).
* `GET .../flow/runs/<run-uuid>` returns `{run,tasks}` and recovers expired leases.
* `GET /projects/api/<slug>/tasks?target_tab=<key>` returns `{tasks}` (latest 200)
  for live progress on sheet rows, including `row_id`, `status`, `run_id`, `node_id`.
* `POST .../flow/runs/<run-uuid>/cancel {}` invalidates active leases and dismisses
  its pending result proposals; already-approved changes remain in revision history.
* `POST .../flow/runs/<run-uuid>/retry {}` requeues failed/canceled work and keeps
  previously successful tasks. Only the creator or an administrator can control a run.

Missing connected capability returns a useful HTTP 409. A registered worker
must poll at least once before starting a run; a poll within five minutes counts
as connected. Keep the worker's claim loop running; the canvas does not simulate it.
Node states: `blocked`, `queued`, `running`, `awaiting_approval`, `succeeded`,
`failed`, `canceled`. Run states omit `blocked`. Forks run independently; a join
is released only after **every** predecessor in that row has succeeded.

## Worker lease protocol

1. `POST /projects/api/limbs/claim {}` returns `{task:null,retry_after:3}` or
   `{task,lease_seconds:120}`. `task` includes `id`, `node_id`, `row_id`, `target`,
   `lease_token`, and `input:{prompt,tabs,predecessors,scope,row_id,rows,target,
   target_tables,predecessor_tasks}`. Each tab has rendered current field values
   and `tables:[{table_id,headers,rows:[{row_id,cells}]}]`. `rows` provides ordered
   source records `{tab_key,table_id,row_id,cells}`; `cells` are strings. Row tasks
   restrict their source/target tab to that row; reference tabs remain complete.
   `target_tables` contains only target table IDs and headers, allowing a splitter
   to match column count without exposing a private target snapshot.
   `predecessor_tasks:[{node_id,row_id,output}]` retains IDs and orders records by
   frozen table row order, then graph node order. Each row task receives matching
   row predecessor tasks plus once-node outputs. Aggregates receive all rows.
   Legacy `predecessors` remains a node-to-output map; an explicit aggregate's
   per-row predecessor value is `[{row_id,output},...]`. Empty upstream stages
   have no predecessor records. IDs and coordinates remain intact under privacy
   masking; prompts, rendered values and outputs use the current project policy.
2. Renew with `POST /projects/api/limbs/renew {task_id,lease_token}` before expiry.
3. Complete with `POST /projects/api/limbs/complete {task_id,lease_token,output}`.
   Output can be `{"text":"..."}`, `{"asset_url":"/projects/api/.../assets/pa_..."}`
   for cell targets, or `{"row_edits":[{"row_id":"b_...","cells":{"3":"..."}}],
   "new_rows":[["...","..."]],"table_id":"b_table"}` for a table target.
4. Fail with `POST /projects/api/limbs/fail {task_id,lease_token,error,retryable}`.
   Retryable failures and expired leases get at most three attempts. Late results,
   stale lease tokens and another worker's completion are rejected with HTTP 409.

Claim uses PostgreSQL `FOR UPDATE SKIP LOCKED` under a transaction. Restarting the
head or worker does not lose definitions, run state, output or retry counts.
Privacy policy is checked again at claim and completion, so switching a project
to `mask_numbers` also affects existing queued runs. No source blobs or auth
tokens are included in task inputs.

## Media and review

Upload raw media bytes to
`POST /projects/api/limbs/upload-cell-asset?task_id=<uuid>&lease_token=<lease>`
using the worker bearer token and the actual media `Content-Type`. Uploads enforce
the same 64 MB limit and format validation as interactive media uploads. The
response has `{asset_id,asset_url,content_type}`. Complete the task separately with
that `asset_url`; uploading alone does not write a cell or release downstream work.

`write_mode` defaults to `proposal`. The creator sees a normal table-edit
ProposalCard. The task stays `awaiting_approval` and downstream tasks stay blocked
until that proposal is applied. Dismissal or an apply conflict fails that task;
retry creates a fresh attempt. Explicit `direct` mode applies the same optimistic
row and field checks, active editing locks, revision history and current creator
permission checks. Changes made during worker execution cannot be silently
overwritten. A revoked or viewer creator cannot write a delayed worker result.
Parallel proposals for different columns in the same row can merge when their
individual cell bases are unchanged. Same-cell edits, row structure/metadata
changes, field-value conflicts and active locks still reject stale proposals.

The document proposal service calls
`flow_runner.proposal_decided(conn, proposal_id, applied)` in its apply/dismiss
transaction to release or fail dependent nodes atomically.
