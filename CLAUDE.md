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

### Product

- [ ] **Screenshot / OCR extraction** for image-only PDFs and screenshots
  (text-based Epic PDF export is done).
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
- [ ] **Shared-section propagation** — edit a shared *content block* once and
  propagate to every template that includes it (distinct from the shared
  *choice variables* above, which are option lists, not prose).
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
