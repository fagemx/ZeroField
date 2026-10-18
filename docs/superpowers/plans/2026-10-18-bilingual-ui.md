# Bilingual interface implementation plan

> **For agentic workers:** Use executing-plans for inline execution. The user approved implementation of batches one and two in this session.

**Goal:** Ship English / Traditional Chinese interface switching while preserving M8 and legacy project data.

**Architecture:** Bundled i18next resources and a validated browser preference drive presentation. Persisted status values and API contracts stay independent of translated labels. Server sign-in and structured API errors share the same locale conventions.

**Tech Stack:** React 19, i18next, react-i18next, Python, PostgreSQL, existing Node test runner / unittest.

**Spec:** `docs/superpowers/specs/2026-10-18-bilingual-ui-design.md`

## Global constraints

- Supported locales: `en`, `zh-TW`; default and fallback: `en`.
- Keep existing English and legacy Chinese status wire values and all M8 / ACP tool keys.
- Preserve user-authored content, custom names, editor state and stored workflow definitions.
- Defer video features, translated project templates and AI output-language settings.
- Rebuild `static/projects/` after frontend edits.

## Review focus

- Unsupported / unavailable browser preferences must resolve to English without crashing.
- Switching languages while an editor is dirty must retain its contents and selection.
- Legacy Chinese statuses must remain valid for completion, grouping and edits in both locales.
- Cached label tables and TipTap node views must refresh when language changes.
- Errors must preserve old clients' `error` field; unknown codes retain a readable fallback.

## Task 1: Locale foundation and status separation

Files: `ui/src/i18n/`, `ui/src/main.jsx`, `ui/src/format.js`, status consumers, `ui/tests/i18n.test.mjs`.

Produces: `t(key, params)`, locale preference helpers, `normalizeStatus(value)`, translated `statusLabel(value)`, React language switch control.

- [x] Write and run failing tests for defaults, fallback, locale validation and language-independent status behavior.
- [x] Add dependencies and bundled dictionaries; separate all status logic consumers from display helpers.
- [x] Add an always-accessible language control and document language updates without remounting the application.
- [x] Verify focused tests.

## Task 2: Workspace and M8 interface messages

Files: existing `ui/src/*.jsx`, `ui/src/assistant/`, formatting and editor extensions, locale dictionaries.

Consumes: Task 1 translation and normalized status interfaces.

- [x] Extract product-owned messages with semantic keys and complete-message interpolation.
- [x] Translate built-in role labels, editor menus / placeholders, table / review / pipeline surfaces, M8 settings / board / races, tooltips and accessibility labels.
- [x] Verify dictionary parity / placeholders and pure frontend regressions; inspect both locales with unsaved input.

## Task 3: Sign-in, API errors and release verification

Files: sign-in rendering, `project_docs/` / `project_assistant/` error responses, `ui/src/api.js`, backend locale tests, README / guardrails / validation receipt, compiled frontend assets.

Consumes: same cookie / supported locale values and frontend error translation keys.

- [x] Add regression tests for localized sign-in, English default, invalid locale and backward-compatible errors.
- [x] Implement localized sign-in and additive error codes / parameters; translate known errors at presentation.
- [x] Run full frontend and PostgreSQL backend suites and frontend build; validate packaged assets.
- [x] Perform isolated desktop checks for both languages and M8 / old statuses. Stop temporary services and record evidence.

## Execution ledger

- User authorization: direct implementation request following the architecture proposal; no extra approval stage needed.
- Branch: `codex/bilingual-ui`, based on `ce80b944526e04b8e9a3d195d1891f632bbf327b`.

- Verification complete: backend 245/245, frontend 83/83, build and wheel resources passed; see `docs/bilingual-baseline.json`.
- Ruling: approved batches are implemented inline; template / AI output languages and video remain deferred. Unrelated product documents are excluded from this delivery.
