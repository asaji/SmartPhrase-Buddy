# CLAUDE.md

Project orientation and the forward roadmap for SmartPhrase Buddy. Committed to
the repo. Machine-specific local/deploy notes live in `CLAUDE.local.md`
(gitignored); architecture and current behaviour are in `README.md`.

## Working rules

- **Frontend build:** editing `frontend.js` requires `npm run build` (esbuild →
  `library/static/library/app.js`) and the regenerated bundle must be committed
  **in the same commit** — the production host has no Node.
- **Tests before pushing** anything under `frontend.js` / `library/` / `config/`:
  `.venv/bin/python manage.py test`, then `scripts/browser_smoke.py` and
  `scripts/browser_regressions.py` (need Chrome; they run isolated servers).
  Use `.venv/bin/python` directly, not `activate`.
- **Deploy** (charon, see `CLAUDE.local.md`): `git pull --ff-only` →
  `collectstatic` → restart `spb` only when Python/settings/templates changed
  (`sudo` there needs a password — hand the restart to the user). charon runs
  Python 3.10; keep syntax compatible.
- No case text, drafts, or AI output is persisted **except** the one opt-in
  resumable copy per operative/procedure master that the surgeon explicitly
  saves via **Save to my account** (`CaseDraft`): owner-scoped, current working
  narrative only (never AI output, instructions, or the session draft-history
  checkpoints), one row per template that an explicit save overwrites, auto-
  deleted after `CaseDraft.TTL` (7 days), and excluded from the portable JSON
  export/backup. Nothing else — no autosave, no browser storage, no case
  logging. Keep it that way — see the privacy boundary in `README.md`.

## Roadmap — future features

### Near-term / cleanup

- [ ] **Hashed static filenames.** Gate `ManifestStaticFilesStorage` on
  `PRODUCTION` in `config/settings.py` so `collectstatic` emits `app.<hash>.js`
  and `{% static %}` points at it. Kills the nginx `immutable` cache wart —
  today every frontend deploy needs a manual hard-reload. Keep it
  `PRODUCTION`-gated so the browser-test harness (insecure finder route, no
  manifest) still works; update the deploy `collectstatic` step to source
  `.env` first.
- [ ] **Reflow hyphen rejoin.** In `reflowWrapped` / `text_to_html`, when the
  previous fragment ends with `-`, join the next fragment with no space
  (`figure-\nof-eight` → `figure-of-eight`), not `figure- of-eight`.
- [ ] **Surface reflow on import review.** When an import row / pasted content
  has many one-line `<p>` fragments, prompt the reviewer to run **Reflow
  wrapped lines** instead of relying on them knowing to click it. (Post-fix
  imports are already reflowed server-side; this is for pre-fix queue rows and
  manual pastes.)
- [x] **Copy formatting help + live preview.** Settings has a new "Copy &
  paste formatting" panel documenting the Epic-paste rules discovered above
  (plain-text-only, no bold, reflow-then-spacing, tight vs. blank-line label
  rules, manual blank-paragraph cleanup). Every editor with copy buttons
  (library preview, master, case, procedure) now also has a **Preview Epic
  paste** toggle showing exactly what `Copy plain text` will produce —
  `text(reflowWrapped(html))`, the same pipeline `copy()` runs — via a shared
  `previewButton()`/`previewBody()`/`wirePreviewToggle()` in `frontend.js`.
  Live editors use `wirePreviewEditor(editor)`, which refreshes on a
  `MutationObserver` over `editor.view.dom` rather than Tiptap's `onUpdate` —
  `commands.setContent()` (Reflow, AI-improve accept, option fill, checklist
  apply, etc.) doesn't fire `onUpdate` in this codebase (existing call sites
  already manually re-derive state after it), but it does mutate the DOM, so
  the observer catches every content change, typed or programmatic, without
  needing to track down each `setContent` call site individually. The static
  library-preview page uses the simpler `wirePreviewCopy(get)` (no live
  editor to observe).
- [x] **Color-coded status bar.** `notify(msg, kind)` in `frontend.js` now
  takes a `kind` (`'neutral'` default, `'success'`, `'error'`) and sets
  `#notice`'s class instead of always rendering the same green regardless of
  what happened. Green is reserved for **Copied** — the one moment the
  narrative is actually ready to paste; every failure path (the generic
  `action()` catch, `api()`'s 401, and the handful of standalone
  `catch`/`.catch()` sites that weren't routed through `action()`) is red;
  everything else (in-progress, "review before copying", MOCK-provider
  notices, save confirmations) stays the neutral slate color. Surfaced from
  real-world feedback (2026-09-18): the bar read as the same reassuring green
  whether or not the note was actually safe to paste.
- [x] **Arial for note text.** `.tiptap` (the live editor), `.document`
  (read-only preview/history/diff), and `.check-ctx` (checklist context)
  switched from Georgia to `Arial,Helvetica,sans-serif` in `style.css` — Epic's
  own default note font, requested 2026-09-25 so what's edited/previewed
  visually matches what lands in Epic. App chrome (Inter) is unaffected.
- [x] **Denser library rows.** `.item` in `style.css` + the row template in
  `library()` (`frontend.js`) — title and type now share one line instead of
  stacking, tag badges cap at 3 with a "+N" overflow badge instead of wrapping
  freely, and padding/margin tightened. Addresses "10+ notes gets cumbersome"
  (2026-09-25) without adding grouping/pagination, since search/filter already
  covers finding a specific phrase.

### Product

- [ ] **Screenshot / OCR extraction** for image-only PDFs and screenshots
  (text-based Epic PDF export is done).
- [ ] **Final narrative consistency check.** Real-world feedback (2026-09-18):
  the existing grammar check reads the note line-by-line and won't catch
  whole-note internal contradictions — the flagship example is a stent-
  placement note in a female patient still referencing a prostatic urethra
  (anatomy that's male-only), left over from a template originally written for
  a male case. Needs a new AI call, separate from grammar, that reads the
  *entire* finished narrative for self-consistency (sex/anatomy mismatches,
  contradictory assertions elsewhere in the note, stale template leftovers)
  and flags — never silently edits — what it finds, the same reviewed-diff-or-
  list pattern as the rest of the app. Design decisions still open before
  building: on-demand button (next to Grammar check) vs. required gate before
  Copy is enabled; whether it reuses `finalize/`'s checklist plumbing or is a
  new endpoint; cost/latency of a second full-note LLM call per copy; how
  findings are surfaced (inline flags vs. a review list) without training
  the surgeon to rubber-stamp yet another AI panel.
- [ ] **Library-item evidence workflow.** `library` kind still just uses the
  master editor. Build: paste-your-own citations by default; opt-in
  AI-suggested citations, every one flagged *UNVERIFIED*.
- [x] **Resumable case drafts** — **Save to my account** keeps one opt-in
  working copy per operative/procedure master (`CaseDraft`, 7-day expiry) so a
  case can be finished on another computer. Still open: keeping *finished*
  cases, and more than one saved variant per template.
- [x] **Shared choice variables** — account-level named option lists
  (`SharedChoice`, Settings editor), referenced from any template as
  `[[@Label]]`; edit the list once and every template follows. Deterministic
  client-side fill; in the JSON export/import. A local `[[Label: … ]]` still
  overrides; an unresolved `[[@Label]]` degrades to a free-text field + warning.
- [ ] **Reusable case-variation saving** — save a filled-in set of `[[ … ]]` /
  checklist answers as a named variant of a master.
- [x] **Phrase-insert markers** — `[[#Title or Epic name]]` in a master
  template, resolved by a new **Insert referenced phrases** button (next to
  Reflow) that copies a *one-time snapshot* of another saved phrase's current
  content in place of the marker (rich HTML when the marker is a whole
  paragraph, plain text inline). Deliberately the simpler of the two options
  discussed for "import phrases" (2026-09-25) — not a live link, so editing
  the source afterward doesn't change notes that already inserted it.
  Master-template editing only, purely client-side. See [[phrase-insert-markers]].
- [ ] **Shared-section propagation** — the other, harder option from that
  same discussion: edit a shared *content block* once and have it propagate
  live to every template that includes it (distinct from the shared *choice
  variables* above, which are option lists, not prose, and from the one-time
  phrase-insert markers above, which snapshot rather than stay linked). Still
  open — would need versioning/recursion-limit decisions before building.
- [ ] **Epic integration** — beyond manual copy/paste (token activation is
  currently unverified on paste).

### Security & ops

- [ ] **MFA / SSO** for login.
- [ ] **Formal production security review** before identifiable clinical data.
- [ ] **Real-provider evaluation** — run the model against missing
  laterality/device detail, conflicting complication assertions, difficult
  dissection without a time figure, unfamiliar tokens, intentional optional-
  passage removal, and malformed/timeout responses, all on synthetic content.
- [x] **End-to-end Epic paste verification (partial)** — real hospital testing
  (2026-09-10) confirmed Epic's Op Note free-text field strips *all* inbound
  clipboard formatting on paste, even from `text/html` written by **Copy
  formatted** — bold and CSS/paragraph spacing both vanish; only `text/plain`
  content actually survives. Fixed in response, in two passes:
  1. `text()` in `frontend.js` now inserts a blank line after every block
     element (`p`/`div`/`h1-4`/`blockquote`/`ul`/`ol`), not just where an
     author happened to leave an empty paragraph, so section spacing survives
     a plain-text-only paste; **Copy plain text** is now the primary/
     emphasized button.
  2. That first pass over-separated content: this surgeon's master narratives
     were pasted in with one `<p>` per Epic hard-wrapped line, never run
     through **Reflow wrapped lines**, so every wrapped fragment got its own
     forced blank line, breaking sentences apart. `copy()` now runs the same
     `reflowWrapped()` merge (already used by the manual button and PDF
     import) automatically before generating clipboard content, so wrapped
     fragments merge into flowing paragraphs regardless of whether a
     template was ever manually reflowed — self-healing for existing
     templates, no per-template action needed.
  Bold itself has no plain-text equivalent and is not being faked with a
  marker (would collide with the `***` placeholder convention) — remains
  unresolved by design.
  3. Pass 2 over-corrected in the other direction: the surgeon's own header
     block (Surgeon/Assistant(s)/Anesthesia/Antibiotics/Fluids/Blood Loss/
     Drains/Tubes/Grafts/Implants/Specimens, one `Label:` per line) also got a
     blank line after every line, which he didn't want — Epic's own
     administrative field block is meant to read tight. `text()` now
     classifies each paragraph: a short `Label:` (≤2 words, e.g. `Procedure:`,
     `Antibiotics:`) stays tight against its neighbors and against a bare
     label's continuation line(s) (e.g. `Procedure:` + the CPT description
     line(s), chained through further unlabeled lines until the next
     label/heading closes it); a longer label (e.g. `Indication for
     Procedure:`, `Description of Procedure:`, ≥3 words) is treated as a
     section heading and always keeps blank-line spacing on both sides, same
     as an actual heading tag. Confirmed against the surgeon's real header
     block and the `Indication for Procedure:` transition — verified via a
     standalone DOMPurify-only Playwright harness, not the full app UI.
  Still open: verification of token/SmartList activation on paste, and
  testing in any other Epic field types (SmartPhrase editor, other note
  sections) that might behave differently.
- [ ] **Multi-worker deployment** needs a shared login/AI rate limiter; the
  current in-process limiter only covers one Gunicorn worker.
