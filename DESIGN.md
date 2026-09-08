# OntologyLab Design System

## 1. Atmosphere & Identity

OntologyLab is a dense scientific review terminal: quiet charcoal surfaces,
precise grids, and semantic color reserved for decisions. Its signature is the
separation between operator actions (terracotta/white) and evidence state
(green verified, amber pending, red rejected).

## 2. Color

The source of truth is `web/style.css :root`; this table names its roles.

| Role | Token | Value | Usage |
|---|---|---|---|
| Canvas | `--background` | `#262624` | Main workspace |
| Surface | `--card` | `#30302e` | Cards and controls |
| Elevated | `--popover` | `#3a3a37` | Menus and overlays |
| Text | `--foreground` | `#ecebe6` | Primary copy |
| Muted text | `--muted-foreground` | `#a3a29c` | Hints and metadata |
| Divider | `--border` | `#3f3f3b` | Hairlines |
| Action | `--primary` | `#b54d30` | Primary actions; white text contrast is approximately 5.16:1 |
| Focus | `--ring` | `#f2f5f2` | Keyboard focus |
| Verified | `--ok` | `#7fb069` | Approved evidence |
| Pending | `--warn` | `#d9a441` | Human review required |
| Rejected | `--destructive` | `#e5787a` | Errors and rejection |

Rules:
- Semantic colors never decorate.
- New colors require a named role here and a `:root` token first.
- Dark mode is the only supported theme so evidence-state contrast is stable.

## 3. Typography

- Primary: `--font` (`Pretendard Variable`, then system UI fallbacks).
- Mono: `--mono` for identifiers, code, and machine values.
- Scale: `--fs-display` 22px, `--fs-lg` 17px, `--fs-md` 15px,
  `--fs-base` 14px, `--fs-sm` 13px, `--fs-xs` 12px,
  `--fs-label` 11px.
- Weights: `--fw-normal` 400, `--fw-medium` 550, `--fw-bold` 600.
- Body copy is never smaller than `--fs-base`; labels and metadata may use
  the smaller declared tokens.

## 4. Spacing & Layout

- Base unit: 4px.
- Scale: `--sp-1` 4px, `--sp-2` 8px, `--sp-3` 12px,
  `--sp-4` 16px, `--sp-5` 24px, `--sp-6` 32px,
  `--sp-7` 48px.
- Content width: `--content-max` 1080px; prose measure: `--measure` 72ch.
- Shell: fixed header and status bar, resizable left rail, independently
  scrolling main canvas. The active panel owns document scrolling.
- Controls use `--h-control` 28px unless content requires intrinsic height.

## 5. Components

### App shell
- **Structure**: header / navigation rail / main panel / status bar.
- **States**: active tab, inspector open, running job.
- **Accessibility**: landmarks, keyboard tab order, visible focus ring.
- **Layout**: shell grid; rail and main own their scrolling.
- **Identity asset**: a bundled monochrome SVG favicon uses the primary action
  mark, is manifest-pinned, and never makes an external request.

### Composer
- **Structure**: prompt input + primary submit + cancel + plan/options row.
- **Variants**: research, chat.
- **Spacing**: `--sp-1` through `--sp-4`.
- **States**: default, focus, running/disabled, validation error.
- **Accessibility**: every control has a visible label or `aria-label`;
  status output uses `aria-live`.
- **Motion**: none beyond declared control transitions.

### Option control
- **Structure**: `.opt` label, `.opt-l` caption, native input/select.
- **Variants**: numeric, select, checkbox.
- **States**: default, hover, focus, disabled, checked.
- **Accessibility**: native label association and bounded numeric inputs.

### Validated engine/model picker
- **Structure**: native engine and model selects populated from the server catalogue.
- **States**: available values only; model options follow the selected engine; an
  absent model means the engine default. A stale or malformed saved engine falls
  back visibly to an available value instead of remaining as an invalid free-form
  string.
- **Accessibility**: both selects have persistent labels and one shared help text.
- **Boundary**: the API rejects unregistered engines and enforces registered API
  provider model lists. CLI versions can accept newer models, so their server
  boundary remains forward-compatible. Display labels never replace machine values.

### Relative timestamp
- **Structure**: visible Korean relative time in a semantic `time` element.
- **Details**: exact locale datetime is retained in `title`, and machine-readable
  ISO time is retained in `datetime`. Invalid or absent values render as an em dash.
- **Use**: lists and tables show relative time; provenance prose may include the
  exact value inline when hover-only disclosure would be insufficient.

### CopyableIdentifier
- **Structure**: shortened primary `code` text, full value in `title`, and an
  adjacent explicit copy button carrying the unchanged machine value.
- **Use**: long URLs, IRIs, UUIDs, hashes, and job IDs must not determine layout
  width or appear as the primary display value.

### Data table
- **Structure**: header, compact rows, status/action cells.
- **States**: focused, selected, pending, empty, error.
- **Accessibility**: semantic table markup and keyboard-reachable row actions.
- **Overflow**: every constrained table wrapper owns horizontal scrolling at
  desktop-inspector and narrow widths; the right-edge fade remains visible
  until the scroll position reaches the final action column. Review tables
  never override their wrapper with `overflow: visible`.

### TabPanel
- **Structure**: `nav.tabs` tab buttons (`role=tab`, `aria-selected`)
  plus `section.tab-panel` panels (`data-tab-panel`); one panel `.active`.
- **States**: active, inactive (hidden via `display:none` — the graph rAF
  loop reads panel width and must see 0), entering, busy
  (`data-load-state`, `aria-busy`).
- **Motion**: entering panel animates `tab-enter` — `opacity` 0→1 with
  `translateY(4px)→0`, `--t-tab` 140ms ease-out. Only `opacity`/`transform`
  animate; the shell never transitions `all`.
- **Accessibility**: `aria-selected` flips with the active class; inactive
  panels keep their DOM (scroll positions and loaded state survive tab
  moves); `prefers-reduced-motion` makes the enter transform instant.

### ConfirmDialog
- **Structure**: one native `<dialog id="confirm-dialog">` (title,
  message, optional reason input, 취소/실행 buttons) reused by every
  destructive action.
- **Variants**: plain confirm; danger (destructive color on 실행);
  reason-required (실행 stays disabled until the reason input is
  non-empty).
- **States**: closed, open, confirm-disabled, submitting.
- **Accessibility**: `showModal()` native focus trap; Esc and 취소 resolve
  as cancel; focus returns to the invoking control; the dialog is labeled
  by its title (`aria-labelledby`). No `window.confirm`/`window.alert`.

### ErrorSurface
- **Structure**: one sentence + action row + collapsed detail —
  ① Korean sentence typed by variant, ② `[다시 시도]` (or `[화면 새로고침]`
  for auth) wired to the failed loader, ③ `<details>` with sanitized
  status/detail text and a copy button.
- **Variants**: `network`, `auth` (401), `forbidden` (403), `server` (500),
  `busy` (503 / Retry-After), `request` (422/validation).
- **States**: pending (retry button disabled, label "다시 시도 중…"),
  failed (sentence re-rendered, button re-enabled), recovered (surface
  hidden).
- **Accessibility**: the paragraph is a live status the reader can act on;
  identical failures within one tab panel render once (section errors
  dedupe to a single surface); raw `unknown`, `Failed to fetch`, and
  untranslated detail strings never render as the first layer.

### LiveRunTrace
- **Structure**: running steps as live tool chips (tool + action, status
  color + glyph) above an open `<details>` step list; elapsed seconds
  counter while a run is in flight.
- **Variants**: request-pending (생각 중 + N초), job-running (chips +
  phase + elapsed), settled summary (도구 N개 · 단계 N · 실패 N).
- **States**: running, ok, failed, skipped.
- **Accessibility**: each chip carries an `aria-label` sentence; the
  counter is honest elapsed time, never a fake percentage; classify
  failure answers with a Korean action sentence + retry, never an English
  tool dump.

### Status box
- **Structure**: inline status badge plus human-readable detail.
- **Variants**: neutral, success, warning, error.
- **Accessibility**: typed failures pass through `errorText()`; never render
  raw objects.

### CTA EmptyState
- **Structure**: semantic icon, formal title, one-sentence description, and a
  real button or link that performs the next action.
- **Variants**: compact list, panel, and terminal success. Decorative emoji are
  prohibited; inline SVG uses the same stroke vocabulary as navigation.
- **Accessibility**: the title names the absence, the CTA names its destination
  or operation, and the component never instructs users to find a remote
  control elsewhere.

### CredentialVerification
- **Structure**: format hint, official issuance link, expected environment
  variable, submit action, and a post-connect verification badge.
- **States**: unverified, checking, verified (`200`), unauthorized (`401`), and
  throttled (`429`). Status is always icon plus text, never color alone.
- **Security**: credential values are write-only and never re-rendered, copied,
  logged, or included in verification detail.

### Progressive ReviewList
- **Structure**: first cursor page, explicit `더 보기` action, loaded/total
  count, and relation/concept detail actions.
- **States**: initial loading, page loading, partial list, complete list, empty,
  and typed error. No time-based polling or scroll-triggered fetch.
- **Performance**: only fetched pages exist in the DOM; one user action maps to
  one cursor request, preserving row order and focus.

### ReasonTooltip
- **Structure**: a disabled control wrapped by a keyboard-focusable reason
  trigger with `aria-describedby`; the tooltip is adjacent and uses
  `role=tooltip`.
- **States**: hidden, hover/focus visible, and removed when the control becomes
  available. It explains the blocking condition rather than repeating
  “disabled.”

### Reduced LiveRegion
- **Structure**: one dedicated activity region plus atomic, appended chat
  announcement nodes.
- **Rules**: navigation location, whole logs, tables, and the entire status bar
  are not live. Only new chat output and current long-running activity announce.

### Terminology map
- Machine action values map through one shared UI dictionary: `enrich` =
  `강화`, `research` = `리서치`, `classify` = `의도 파악`, `build_pack` =
  `팩 빌드`, `approve` = `승인`, `reject` = `거부`, `search` = `검색`.
- New visible Korean uses formal `~합니다`; section headings are concise nouns,
  not first-person or conversational questions.

### JobResultLegend
- **Structure**: visible `신규 N · 병합 N` values for concepts and relations,
  plus a status glyph and localized text.
- **Accessibility**: glyphs are decorative; status text remains in the
  accessibility name. Raw `+N/~N` notation is not user-facing.

### CopyableIdentifier
- **Structure**: shortened, overflow-safe visible value, full value in an
  accessible label/title, and a copy action with terminal feedback.
- **Variants**: job ID, document URL, ontology IRI, and hash. URLs retain a
  recognizable host and tail; copying always writes the exact full value.

### KeyboardGraphNode
- **Structure**: one SVG group containing circle and label in a shared hit
  target; `role=button`, `tabindex=0`, and a target-specific accessible name.
- **Interaction**: click, Enter, and Space select/expand identically; focus uses
  `--ring`; pointer and keyboard never bind to different geometry.

### SessionSwitcher
- **Structure**: persistent session list, active session title, rename action,
  switch action, and new-session action.
- **Persistence**: localStorage stores metadata only (ID, title, updated time);
  transcript content remains server-owned. Storage events synchronize windows.
- **States**: active, inactive, renaming, empty-first-session, and unavailable
  storage fallback. Automatic titles derive from the first user message and
  remain editable.

### Data-table overflow cue
- Horizontal table wrappers use an inset edge gradient derived from
  `--background`/`--border` to signal hidden columns without adding a new color.
  The cue is visual only and does not obscure focus rings or cell content.

## 6. Motion & Interaction

| Type | Duration | Easing | Usage |
|---|---|---|---|
| Micro | 150ms | ease | Hover/focus color |
| Tab | `--t-tab` 140ms | ease-out | Tab panel enter (opacity + 4px rise) |
| Standard | 200ms | ease-in-out | Panel or disclosure state |
| Live indicator | 1.6s | ease-in-out | Running status only |

- Animate only opacity, transform, and color.
- Every interactive element keeps visible hover, active, focus, and disabled
  states.
- `prefers-reduced-motion` makes transform/opacity motion instant but keeps
  semantic color transitions — state color is information, not decoration,
  and infinite indicator pulses stop (`animation-iteration-count: 1`).

## 7. Depth & Surface

Strategy: tonal shift plus hairline borders. Shadows are disabled through
`--shadow-float` and `--shadow-soft`; depth comes from the progression
`--sidebar` -> `--background` -> `--card` -> `--popover`.

## 8. Accessibility Constraints & Accepted Debt

Constraints:
- WCAG 2.2 AA target.
- Body contrast at least 4.5:1; large text and controls at least 3:1.
- Full keyboard reachability and persistent focus indication.
- Korean labels must preserve word boundaries; long identifiers may wrap.
- Primary content must remain usable at 375px without horizontal page scroll.
- ConfirmDialog: native `<dialog>` semantics, Esc = cancel, focus returns to
  the invoking control, destructive confirms stay disabled until any
  required reason is entered.
- ErrorSurface: the retry control is keyboard-reachable and announces its own
  pending/terminal state; the collapsed detail is reachable and copyable.
- LiveRunTrace: chat composer stays operable while a run is in flight —
  messages queue FIFO instead of locking the input.
- New visible copy uses the formal `~합니다` register.

Accepted debt:

| Item | Location | Why accepted | Owner / Exit |
|---|---|---|---|
| No light theme | `web/style.css` | Evidence-state colors are calibrated for the fixed dark review terminal | Revisit only with a separately tested semantic palette |
