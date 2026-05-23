# irtool — Continuation Notes

A snapshot of where the project stands, what works, what doesn't, and
where to pick up. Read alongside `README.md` for the user-facing usage.

---

## 1. Project Overview

**`irtool`** converts a small YAML intermediate representation (IR) into
drawio diagrams (and PNG previews) for six diagram types: DFD, class,
state (`std`), sequence, activity, and dialog map.

### Pipeline

```
YAML IR  ──▶  validate  ──▶  build  ──▶  .drawio  ──▶  render  ──▶  .png
              (schema +     (size +                    (real drawio
               semantic)     layout +                   in headless
                             emit)                      Chrome)
```

Three layers, each replaceable:

1. **Validate** — `irtool/validate.py`. YAML → Pydantic schema → semantic
   checks (orphans, duplicate ids, dangling refs, type-specific
   invariants). Issue codes are stable strings; fixtures pin them.
2. **Build** — `irtool/build/`. One file per diagram type. Each owns its
   sizing, layout, and styling. Shared XML emitter is mechanical.
3. **Render** — `irtool/render.py`. POSTs the drawio XML to a local
   `jgraph/draw-image-export2` server (Node + Puppeteer). Real drawio
   code in headless Chrome — same renderer `export.draw.io` uses.

### Layout

```
irtool/
├── models.py          Pydantic IR — single source of truth
├── issues.py          Issue + IssueCode vocabulary
├── semantic.py        Per-type semantic checks
├── validate.py        YAML -> schema -> semantic pipeline
├── render.py          Export-server client (PNG)
├── cli.py             python -m irtool check|build|render
└── build/
    ├── __init__.py    dispatcher on IR type
    ├── types.py       Shape, Connector, BuildResult dataclasses
    ├── xml_emit.py    BuildResult -> drawio XML (mechanical only)
    ├── _common.py     shared helpers (parallel_track, outside_route,
                       pseudo-states, edge styles, label-offset)
    ├── dfd.py         (3-column layout)
    ├── class_.py      (hierarchical by inheritance)
    ├── state.py       (BFS-layered or circular)
    ├── sequence.py    (lifelines + messages, polished)
    ├── activity.py    (swimlanes)
    └── dialog.py      (★ spine-aware tree layout, current reference)

tests/
├── test_validator.py  parametrized sweep of fixtures
├── test_build.py      every valid fixture must build to parseable XML
└── ir/
    ├── valid/         one minimal fixture per diagram type
    └── invalid/       11 fixtures + .expected.json with required codes

scripts/
├── setup_export_server.ps1
└── start_export_server.ps1

tools/
└── draw-image-export2/   gitignored; jgraph's real renderer

examples/
├── senaryo1.yaml          13-message sequence diagram (Turkish, real-world)
└── checkout_flow.yaml     8-state dialog with main spine + side branches
```

### IR conventions

- Every node has `id` (machine handle, required) and `name` (display
  label, optional — defaults to `id`).
- Pydantic models use `extra="forbid"` — unknown fields are errors.
- Edges always use `from` / `to` (aliased to `src` / `dst` in code).
- State and dialog node types support `is_initial` / `is_final` flags.
  The renderer materialises these as separate pseudo-state cells
  (filled circle / bullseye) with their own connecting arrows.

---

## 2. Where we left off

### What just got built (the dialog builder is the reference)

The `dialog.py` builder went through a multi-iteration redesign and is
now the most polished:

| Feature | Implementation |
|---|---|
| Tree-shaped layout | Each parent sits over its centered child. |
| Spine detection | Shortest BFS path from `is_initial` → `is_final` defines the main column. |
| Child ranking | spine (0) > bidir (1) > one-way other (2). Top-ranked gets the centered slot. |
| Bidir loops sideways | Same Y level as parent (a side-step, not a forward step). |
| Single-child alignment | A node with one child is vertically aligned with it (clean column). |
| Pseudo-states | Initial = black dot above; final = bullseye below ("Exit" label). |
| Long-edge routing | Edges spanning ≥2 spine levels route via outside gutters, not through cells. |
| Self-loops | Explicit waypoints draw a small arc above the cell. |
| Parallel-edge separation | `parallel_track` is geometry-aware (facing-side attachment); `parallel_label_offset` pushes labels off arrow lines and apart. |

### Helpers in `_common.py` that any builder can reuse

| Helper | What it does |
|---|---|
| `EDGE_STYLE` | Standard orthogonal edge style. |
| `STRAIGHT_EDGE_STYLE` | Non-orthogonal style for the rare diagonal pair. |
| `find_bidirectional(edges)` | Returns the set of (src,dst) pairs whose reverse exists. |
| `parallel_track(...)` | Returns (exit_x, exit_y, entry_x, entry_y) pins for one half of a bidir pair. Picks track axis (X for vertical pair, Y for horizontal) and natural facing side. |
| `parallel_label_offset(...)` | Returns label (dx, dy) so two pair labels don't sit on the same point — and for horizontal pairs, pushes labels off the arrow line. |
| `initial_pseudo(...)`, `final_pseudo(...)` | Build a small filled circle (initial) / bullseye (final) shape + connecting arrow. |
| `outside_route(...)` | Pinned endpoints + waypoints to route an edge around the outside of the diagram. |

### Test status

- **41 / 41 passing.** No flakes. Run with `python -m pytest tests/`.
- `tests/ir/valid/*.yaml` — one minimal fixture per diagram type.
- `tests/ir/invalid/*.yaml + *.expected.json` — 11 fixtures pin which
  issue codes the validator must produce.

### Reference renders

Two non-trivial examples live in `examples/`:

- `examples/senaryo1.yaml` — 4 lifelines, 13 messages, one self-message,
  Turkish text. Exercises the sequence builder. Renders cleanly.
- `examples/checkout_flow.yaml` — 8 dialogs, 11 transitions, two bidir
  pairs, one self-loop, initial + final pseudo-states. Exercises the
  full spine-aware dialog layout. Renders cleanly with a vertical main
  spine and sideways branches.

---

## 3. What's planned next

In rough priority order:

### 3.1 Port spine-aware layout to state diagrams

`state.py` still uses the older row-based BFS layout. It hasn't been
upgraded to:
- the tree-shaped placement that aligns parent-child cleanly,
- the spine-aware ranking that promotes the main flow to the axis,
- the `_spine_levels` that puts bidir loops sideways instead of below.

Should be a mostly mechanical port from `dialog.py` — the IR types are
similar (`State` has `is_initial`/`is_final` flags too, transitions
have `from`/`to`). About 60-80 lines of touched code.

### 3.2 Visual regression tests

The current `test_build.py` only validates that the output XML
parses and has the right cell counts. It does **not** check what the
diagram looks like.

Now that the dialog layout is deterministic, we can:
1. Render every valid fixture through the export server.
2. Commit the PNGs as goldens under `tests/visual/golden/`.
3. Add a test that renders fresh, pixel-diffs against the golden,
   fails if difference > some threshold and writes the diff image.

Requires Pillow or pixelmatch-py. Maybe 100 lines of test harness.

### 3.3 Improve class diagram layout

`class_.py` is the least polished. Issues:
- Multiple disconnected inheritance trees aren't handled specially —
  they all squash into the same horizontal row.
- No special handling for associations vs inheritance (both drive
  layout currently).
- Variable box heights (attr/method count) cause vertical bleed when
  there's a tall class on one row.

Could apply the same spine-aware logic if "inheritance edges" play
the role of "spine."

### 3.4 Optional: UML interaction frames for sequence

The Senaryo #1 source had a `loop` frame ("repeats for durak2 / durak3
between messages 3-6"). My IR has no concept of interaction frames
(loop / alt / opt / par / break). Adding support touches:
- `models.py` (new `Frame` model on `SequenceDiagram`)
- `semantic.py` (validate frame message ranges)
- `sequence.py` builder (render a tan-bordered container around frame
  messages)

Real work — maybe 200 lines across files. Skip unless someone needs it.

### 3.5 Optional: diagram-level description / subtitle

Source diagrams often have a paragraph of context below the title (the
Senaryo source had one). My IR only has `title`. Adding `description:
str | None = None` to every diagram model and rendering it as a text
cell above the diagram is trivial — about 30 lines.

### 3.6 Optional: migrate old example YAMLs

There used to be `test_1_simple_dfd.yaml`, `uc1_checkout_*.yaml`, etc.
in the repo root using the **old** IR (no `id` on classes, `type:
start` on states instead of `is_initial: true`, etc.). They were all
deleted during the legacy cleanup. If you want them back as fixtures,
a one-time conversion is mechanical.

---

## 4. Open tasks

These map to in-flight or pending work. Numbers refer to the live task
tracker; some have rolled over between sessions.

| # | Task | Status |
|---|---|---|
| — | Port spine-aware layout from `dialog.py` to `state.py` | open |
| — | Visual regression test harness with golden PNGs | open |
| — | Class diagram layout improvements (disconnected trees, etc.) | open |
| — | UML interaction frames (loop/alt/opt) in sequence | optional |
| — | `description:` field on diagram models | optional |
| — | Migrate any old YAML fixtures forward to the new IR shape | optional |

### Known small issues (cosmetic, not blocking)

- **Bidir-pair labels on tight horizontal pairs can still be close.**
  When two cells are very close horizontally, the upper-track label and
  lower-track label are ~48px apart vertically — readable, but not
  spacious. Could widen `_H_GAP` adaptively when a bidir pair exists.
- **Self-loop above-the-cell arc can overlap incoming top arrows.**
  When a node has both an incoming forward edge from above AND a
  self-loop, both reach the top edge of the cell. The self-loop arc
  sits above but very close to the incoming arrow. Cosmetic; only
  visible on dense layouts.
- **Order Confirmation's "Exit" label sits below the cell, between
  it and the bullseye.** Looks OK but might collide if more cells
  end up directly below.

---

## How to pick up

```bash
# Start the export server (one-time setup, then leave running)
.\scripts\setup_export_server.ps1       # installs deps + Chromium
.\scripts\start_export_server.ps1       # listens on :8005

# Validate, build, render
python -m irtool check examples/checkout_flow.yaml
python -m irtool build examples/checkout_flow.yaml --render \
       --server http://localhost:8005

# Run the test suite
python -m pytest tests/

# Reference outputs to eyeball
examples/checkout_flow.png      # dialog, spine-aware layout
examples/senaryo1.png           # sequence, 13 messages + self-loop
```

### When adding a new layout rule

1. Reach for `_common.py` first — most rules generalise across diagram
   types and belong as a shared helper (like `parallel_track`,
   `outside_route`, `parallel_label_offset`).
2. Only specialise per-builder when the rule truly is type-specific
   (e.g. swimlane container coordinates for activity).
3. Add a fixture that exercises the new rule. Run the regression test.
4. If the visual changes, eyeball the rendered PNG before declaring
   victory — schema/semantic tests alone don't catch layout regressions.

### When in doubt about layout

The mental model for the dialog builder, in three sentences:

> The **spine** is the shortest path from start to end — it's the
> vertical axis. **Bidir loops** are side-trips at the same flow
> level — they dock sideways on the y of their parent. **Everything
> else** (one-way exceptions, terminal off-shoots) gets the next y
> level, branching to whichever side is free.

Everything else is either an implementation detail or fallback for
diagrams without a clean start/end (`is_initial`/`is_final` missing).

---

## Architecture invariants (don't break these)

- **`models.py` is the spec.** All schema lives there. Don't validate
  shape elsewhere — just call `IR.model_validate(data)`.
- **`extra="forbid"`** on every model. Unknown fields must error
  loudly, not be silently dropped.
- **`xml_emit.py` is dumb.** No geometry decisions; it just translates
  Shapes and Connectors into mxCells. If layout logic crept in there,
  it's a bug.
- **`_common.py` is shared, builders are type-specific.** A helper that
  any diagram type might want goes in `_common.py`. A rule that's
  inherently about (e.g.) lifelines goes in `sequence.py`.
- **Cell `id`s on Shapes equal IR `id`s.** Drawio allows string cell
  IDs as long as they aren't `"0"` or `"1"`. Don't introduce a
  renaming layer; the IR ID is the cell ID.
- **41 tests should always be green.** If a test broke as a side
  effect of a layout fix, it usually means a cell or edge count
  changed and `test_build.py`'s counting needs an extra accounting
  rule (e.g. pseudo-states). Update the test alongside, don't ignore.

---

## File map at a glance

```
drawio/
├── irtool/                  ← the tool (validate + build + render)
├── tests/                   ← 41 tests, fixture-driven
├── scripts/                 ← PowerShell helpers for the export server
├── tools/                   ← gitignored, jgraph's renderer
├── examples/                ← non-trivial reference YAMLs + renders
├── README.md                ← user-facing usage
├── CONTINUATION.md          ← (this file)
└── .gitignore
```
