# English and Traditional Chinese interface

The user approved batches one and two: a complete English / Traditional Chinese interface, English by default, retaining M8 / ACP / E1 and all existing project data. Video integration and translated project templates / AI output language are outside this change.

## Design

- Use i18next with bundled `en` and `zh-TW` dictionaries. Semantic keys identify messages; interpolate complete sentences rather than translating sentence fragments.
- A validated `zerofield_locale` preference cookie joins the React workspace and server-rendered sign-in page. Unsupported preferences resolve to English. Switching language changes presentation without remounting editors or rewriting documents.
- Separate persisted status normalization from translated labels. English and legacy Chinese wire values retain their existing validation and storage behavior. Completion, grouping, filters, color and permissions depend only on fixed values.
- Translate product-owned controls, accessibility labels, built-in role labels, M8 controls, error messages, dates and numbers. User documents, project / page titles, custom agent names, prompts, workflow configurations and conversation history retain their content.
- Add structured error codes and parameters alongside the legacy English `error` field for existing clients. Do not localize shared backend state or change orchestration contracts.
- The sign-in page uses the same locale allowlist and preference as the workspace. No automatic browser-language detection: first use is English.

## Acceptance

Both locales cover the same message keys and interpolation parameters. A missing translation falls back to English. Switching language preserves unsaved input and selection, existing Chinese statuses still display and save correctly, and M8 profiles / task policies remain unchanged. English and Chinese desktop UI checks, the frontend suite, the full PostgreSQL backend suite, and `npm run build --prefix ui` must pass. Rebuild distributable frontend assets and validate wheel resources.
