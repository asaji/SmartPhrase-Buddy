# SmartPhrase Buddy

Private, single-user SmartPhrase library and temporary operative narrative editor. No Epic connection, public signup, automatic submission, or deployment. Development examples are synthetic; original screenshots were not supplied.

## Architecture

Django 5.2 LTS provides authentication, password hashing, database-backed sessions, CSRF protections, ORM/migrations, and server-side access control. SQLite fits a single user without another service. Tiptap/ProseMirror provides locally bundled rich-text editing and undo; DOMPurify and a server-side HTML allowlist sanitize content. Text diffs show additions/deletions; formatting is reviewed in the proposed rich-text editor. Django's [support schedule](https://www.djangoproject.com/download/) lists 5.2 LTS support through April 2028. Editor integration follows [Tiptap's vanilla JavaScript documentation](https://tiptap.dev/docs/editor/getting-started/install/vanilla-javascript).

Templates own independent content; no shared sections. Each save creates a full immutable revision snapshot, with optimistic version checks. Restore creates another revision. AI proposal requests do not write templates. Master approval requires a signed, user-bound, expiring selected-ID/version scope. Case proposals cannot be approved through the master endpoint. Browser case drafts never use a draft model, localStorage, sessionStorage, or analytics.

## Local setup

Python 3.12–3.14; Node 22+ only needed to rebuild the editor. The compiled editor bundle is included.

```sh
cd smartphrase
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8765 --noreload
```

Open http://127.0.0.1:8765 and sign in with the account you created. No default password or account is shipped. The superuser command is used for convenient initial provisioning; no Django admin endpoint is exposed. Do not create additional accounts for this single-user deployment.

For a synthetic walkthrough: New phrase → Load synthetic example → Use pasted source → Split at Indication for Procedure → inspect both editors → check review confirmation → Approve and save to library. To import your originals, paste them into the source editor and perform the same review, assign metadata/aliases, and adjust the header manually where necessary. Paragraphs, headings, emphasis and lists are supported; images, tables, links, arbitrary styling and active markup are deliberately not retained in editable content. Original source is stored separately as inert text.

Configuration is through environment variables. Copy `.env.example` to `.env` (git-ignored) and `manage.py` will load it for local runs — real environment variables still win, and `manage.py test` ignores `.env`. Production uses the systemd `EnvironmentFile` instead. The development secret is generated into the ignored `.local-secret`. SQLite defaults to ignored `private.sqlite3`. **This checkout is inside an iCloud folder: keep development synthetic, and set DATABASE_PATH to a private, approved, non-synchronized location before storing sensitive reusable content.** Backups/exports and original imports may contain sensitive information too.

Rebuild after frontend changes:

```sh
npm ci
npm run build
```

## Implemented workflows

- Persistent create/read/update/delete library; title, Epic name, type, tags, aliases, favorites, timestamp and revision metadata.
- Search all requested fields; type/exact-tag/favorite filters, previews, rich/plain copying without AI.
- Manual paste import review, preserved source, adjustable Epic header/narrative split, fixed-age flag.
- Epic SmartPhrase **PDF import**: upload an Epic "print SmartPhrases" export once; detected phrases are saved as a persistent, owner-scoped **import queue** you work through over multiple sessions. Each entry (name, extracted text, per-segment flags for letterhead / disclaimer / fixed age / missing tokens / bracket placeholders) stays an unapproved draft; approving a template from it or skipping it removes it from the queue. Re-uploading the same PDF adds nothing. The PDF file is parsed in memory and never stored or logged; nothing is silently repaired. See "PDF import" below.
- Master editing, full revision history, restore as a new revision, stale-save protection.
- Selected-template proposals, per-template text diff, manually editable proposal, explicit acceptance/rejection, scope enforcement and token-change review.
- Separate in-memory operative drafts, iterative free-text AI instructions, line-by-line case checklist, manual editing, undo/redo, copy approval checkbox, Finish and clear, navigation warning. A session-only **draft history** keeps every generated proposal and applied change (view / copy / restore); it lives in a JS array — no database, `localStorage` or `sessionStorage` — and is gone on Finish and clear or navigation. None of the case flow writes to the master template or its revisions (enforced server-side and covered by tests).
- JSON portable import/export with complete revision metadata and timestamps. Import adds independent copies; it never overwrites existing templates. Imports are atomic and capped at 500 templates / about 1.9 MB; use database restore for larger libraries.
- Login/logout, password change, no public signup, authenticated API, ownership checks, CSRF, no-store responses, strict content security policy, request size limits, login/AI rate limits.
- Configurable mock or HTTPS chat-completions-compatible AI provider, timeout and malformed-result handling, server-only secrets.

## Note types

Every phrase has a **type** (`kind`), set in the editor and used to route it to the right workflow. `clinic`, `operative`, `procedure`, `library`, `other` are the accepted values.

- **Operative template** (`operative`) — the full case workflow: **Customize this case** opens the in-memory case editor with a "Pick built-in options" panel, the line-by-line checklist, free-text AI instructions, modifier-22 tool, grammar-on-copy, and the Epic header boundary. The same `[[Label: option | option | option]]` marker used by procedure notes can be placed anywhere a fixed, template-defined set of choices belongs instead of a free-typed answer (e.g. `[[Extent: RALP without pelvic lymphadenectomy | RALP with standard pelvic lymphadenectomy | RALP with extended pelvic lymphadenectomy]]` in ASOPNRALP). Ticking an option and clicking **Fill selected options** substitutes it deterministically — no AI call, and the surgeon is never asked to free-type wording that is already fully specified. A variable's options are declared once (the first `[[Label: … ]]` for that label); anywhere the same value is needed again, write just `[[Label]]` and it is picked once and filled into every occurrence. A bare `[[Label]]` whose options are never declared shows as a free-text-only field with a warning, and the master editor flags undeclared or re-declared variables as you type. Every other placeholder (`***`, `@TOKEN@`, `{…}`) still goes through the AI checklist below, unaffected by markers.
- **Procedure note** (`procedure`) — for short, repetitive office procedures (cystoscopy, prostate biopsy). **Fill out this procedure** opens a structured editor: the template author marks findings up inline as `[[Label: option | option | *** free value]]` (e.g. `[[Bladder: normal | trabeculation | diverticulum | mass]]`, `[[EBL: minimal | *** mL]]`). The right panel renders one checkbox group per distinct variable plus a free-text slot; **Generate note** substitutes the ticked values deterministically (multiple picks are joined as a list). A label repeated in the note — its options declared once, then referenced as `[[Label]]` — is one control that fills every occurrence. Every generation uses the starting template and current selections, so partial filling, changing a selection, and clearing a selection keep the correct field mapping. If manual edits or AI changes have changed the generated note, regeneration requires confirmation and preserves a session checkpoint first. Deterministic fill is the whole feature and never touches a heading or an unmarked sentence. An **optional, off-by-default** grammar pass (*"ask AI to fix grammar line by line"*) then sends the filled text through `/api/propose/` (`mode:"case"`) with an instruction that permits only line-by-line grammar fixes — no deletion, merging, condensing, reordering, or invention — and the reviewed diff is gated by `guardShrink` (rejects a proposal that drops a heading, loses more than one paragraph, or shrinks the note past ~70%). Adding a new procedure needs no code change: add markers to the master template. The case-proposal endpoint accepts `operative` and `procedure` kinds only.
- **Library item** (`library`) — a risks/benefits/evidence SmartPhrase (e.g. `ASCLINICPLANTURP`). Keeps the master editor for now; the evidence workflow (paste-your-own by default, opt-in AI-suggested citations flagged *UNVERIFIED*) is not built yet.

## PDF import

Many Epic builds let a user print/export their SmartPhrases to PDF. In **New phrase / import → Import from an Epic SmartPhrase PDF export**, choose that file. The server (`library/pdfimport.py`, using `pypdf`) extracts the selectable text and splits it into segments: a line that is only an uppercase token (`ASOPNSPRALP`, `ASLIBTPVSTR`, …) and is preceded by a blank line starts a new segment; text before the first such line becomes an unnamed segment. Each segment carries the detected name, the extracted text, a conservative plain-text→HTML rendering (one paragraph per line, bullet lists preserved — no headings or emphasis inferred), and review flags (letterhead lines, patient-facing disclaimer blocks, a fixed patient age, no Epic tokens detected, `[ … ]` bracket placeholders).

**Import queue.** `POST /api/import/pdf/` stores every segment as a `PendingImport` row (owner-scoped), deduplicated by `(name, text)` against everything you have ever queued, so uploading the same PDF twice adds nothing. Its own page — nav **Import queue**, or the count banner on the library — lists the queue (`GET /api/imports/`, `?dismissed=1` for the skipped list) as one compact row per phrase (name, size, flag count), so a few hundred dotphrases stay scannable. No re-upload is needed on later visits. Clicking a row opens the **Add to your library** editor with that phrase's text already in the content and source editors and the title/Epic name prefilled; you set the type/tags, adjust the Epic header boundary, review, and **Approve and save to library** — which saves the template, revision, and imported queue status atomically (`POST /api/templates/` with `pending_import_id`), removes it from the queue, and returns you to the queue for the next one. A failed save leaves the entry pending; repeated saves of an already imported entry are rejected without creating duplicates. **Skip** marks an entry dismissed (`{action:"dismiss"}`, reversible with `restore`). **Clear imported & skipped** (`POST /api/imports/clear/ {scope:"resolved"}`) deletes resolved rows; templates you already saved are untouched.

The split is best effort: names stay editable, an over-split segment is just extra text you can move, and ALL-CAPS lines inside content (wrapped headings, `NOTES`, `MONITORING`) are deliberately not treated as new phrases when they are not preceded by a blank line.

Privacy: the uploaded PDF is held in memory only (`FILE_UPLOAD_HANDLERS` is memory-only, 25 MB cap), parsed, and discarded — the file bytes are never written to disk or logs, and `pypdf` logging is routed to a null handler. The extracted phrase text *is* persisted in the `PendingImport` table, because it is reusable-template import material (not a case draft): it is owner-scoped, excluded from the template JSON export/backup, and removed from the DB when you import, skip-and-clear, or clear the queue. Scanned image-only PDFs (no text layer) are rejected with guidance rather than OCR'd.

## AI configuration and limitations

Default `AI_PROVIDER=mock` is a deterministic demonstration, not a clinical editing model. It only appends the supplied synthetic inflammation/scarring statement for the matching demonstration instruction; otherwise returns unchanged content with a manual-review question. It performs no external requests and must not be used to evaluate clinical AI quality.

### OpenRouter (recommended)

[OpenRouter](https://openrouter.ai) is an HTTPS OpenAI-compatible gateway to many models. In the server environment (never in the browser or in source control):

```sh
export AI_PROVIDER=openrouter
export AI_MODEL=anthropic/claude-sonnet-4      # any slug from https://openrouter.ai/models
export AI_API_KEY=sk-or-...                    # create at https://openrouter.ai/keys, add credit
export AI_APP_TITLE="SmartPhrase Buddy"                 # optional, labels requests in your OpenRouter activity
export AI_APP_URL=https://your.domain          # optional
```

Restart the server and open **Settings → AI configuration**; it should read `Provider: openrouter`, `Endpoint: openrouter.ai`, `Status: Configured`. The key is held only on the server and never shown. `AI_BASE_URL` is not needed for OpenRouter (it defaults to `https://openrouter.ai/api/v1`); set it only to point at a different gateway.

### Google Gemini

Gemini exposes an OpenAI-compatible endpoint, so no adapter is needed. Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey), then:

```sh
export AI_PROVIDER=gemini
export AI_MODEL=gemini-2.5-flash          # or gemini-2.5-pro, gemini-2.0-flash, ...
export AI_API_KEY=...                     # server only
```

`AI_BASE_URL` defaults to `https://generativelanguage.googleapis.com/v1beta/openai`; set it only to route through a proxy. The same request shape (`temperature: 0`, lenient JSON parsing) is used. You can also reach Gemini through OpenRouter instead (`AI_PROVIDER=openrouter`, `AI_MODEL=google/gemini-2.5-flash`).

### Any other OpenAI-compatible endpoint

Set `AI_PROVIDER=compatible`, `AI_BASE_URL` (HTTPS, e.g. ending in `/v1`), `AI_MODEL`, and `AI_API_KEY`. The request is a standard `POST /chat/completions` with `temperature: 0` and a system prompt that demands a bare JSON object; the response is parsed leniently (markdown code fences and surrounding prose are tolerated), so `response_format` support is not required. Providers with a non-OpenAI API need an adapter in `library/services.py`. Endpoint compatibility and model quality have not been tested here without credentials.

### Reviewing a proposal

A proposal never changes anything on its own. The review card shows the change summary, any questions/warnings, and the **proposed narrative with additions highlighted and deletions struck through** (toggle **Show clean version** for the plain result). You can edit the proposed text inline before accepting. **Accept** applies it to the working draft (case) or saves it as a new master revision (selected-template update) only after you tick the review checkbox; **Reject** leaves saved content untouched. AI failure, timeout or a malformed/unsafe response returns a 502 with your text unchanged and manual editing still available.

### Epic header boundary

Epic imports only the **Date of Procedure** and **Patient/MRN** lines; everything from **`Surgeon:`** onward stays in the editable narrative so the AI can improve the whole note and a modifier-22 paragraph can sit above the indication. The master editor's boundary tools are **Split after Patient/MRN** (finds the first `Surgeon:` / `Attending` line) and **Split at Indication for Procedure** (the older behaviour); both editors stay hand-editable for other conventions. The excluded header never enters case AI requests or narrative copying.

### Modifier 22

The app is otherwise strict against inferred billing language — but a surgeon can deliberately add a **modifier-22 statement** for a specific case. In the case editor, *Modifier 22 statement* (collapsed by default) lets you:

- pick one of your own **MOD22 templates** (only templates with `MOD22` in the title or Epic name are listed, e.g. `ASMOD22RALP`) — its full cleaned text is sent as `template_wording`, carrying the payer-mandated "unusual procedural services / substantially greater than typically required" phrasing the model must follow;
- **tick the `[bracketed]` reason options** from that template that apply to this case (a bracket written `[A / B / C]` becomes three checkboxes); each ticked reason must appear in the statement;
- add free-text **case-specific complexity factors**; each distinct point must appear.

`POST /api/mod22/` sends `template_wording`, `required_reasons` and `complexity_factors` together and requires all three to be integrated. `MOD22_CONTRACT` asks the model for **only the statement paragraph**; the server begins it with `Unusual Procedure:` (prepended if the model omits the mandated label — so it is present even with no template), **appends it, after a blank line, to the end of the note**, and shows the highlighted-diff review card. The contract forbids inventing time, blood loss, BMI or any figure (a figure you supply is used verbatim; an invented one is rejected in `_finish(..., allow_billing=True)`, comparing numeric values so wording differences don't false-trip) and forbids stating the case "qualifies for" the modifier — it lists the work and circumstances and leaves eligibility to the coder. A dedicated **Additional operative time** field feeds any `*** minutes` slot; left blank the `***` stays. Warnings flag any selected reason missing from the draft, a draft that never states the service was substantially greater than usual, and always that the tool does not determine coding eligibility. Nothing here touches the master template or is persisted.

### Ask AI to improve a master note

Editing an existing master shows **Ask AI to improve this note** (collapsed by default) below the narrative editor. Describe what should read better — clarity, flow, redundancy, structure, consistent tense — and `POST /api/propose/` (`mode:"master"`, single template id, the same `CONTRACT` used for case revisions) revises the **currently open editor content**, including any edits not yet saved, not the last-saved revision. The result is shown as the usual highlighted-diff review card; **Accept** applies it into the editor only — nothing is written to the database until you tick **I reviewed reusable content…** and click **Save new master revision** yourself, so an accepted improvement still goes through the normal grammar-check-on-save pass and the same protected-token confirmation as any other edit. **Reject** discards it. As with every other proposal, source content and the instruction are the only things sent to the provider, no wording or fact is invented, and a heading the response drops requires explicit confirmation (`guardHeadings`) before it can be applied.

### Grammar check on master save

When an AI provider is configured, **Save new master revision** / **Approve and save to library** first runs a mechanical copy-edit pass (`POST /api/grammar/`, `GRAMMAR_CONTRACT`): spelling, grammar, punctuation, capitalisation and spacing only — no wording, meaning, structure or Epic-token changes (the token/time/billing checks in `_finish` still run, and an unchanged token count is required). The fixes are shown in the highlighted-diff review card; **Accept** applies them and saves, **Save without these fixes** commits the text as-is. Grammar results in master, operative, and procedure editors are bound to their source text. If the narrative changes while the request is running or before acceptance, the app requires a new grammar check instead of overwriting those edits. Results from a page that has been left are discarded. With no provider configured, or on the mock provider, the save proceeds unchanged.

### Completing a case line by line

The case editor is organised around the way notes actually get finished: **1 · Pick built-in options** resolves any `[[Label: option | option]]` fields deterministically, before anything is sent to a model; **2 · Build the case checklist** is the primary action for everything else; **3 · Clean up leftovers** (Strip unresolved placeholders, with a live count spanning `[[ … ]]`, `@X@`, `{…}`, and `***`) comes after it; and **Free-text edit** is a collapsed backup for anything the checklist did not cover.

**Pick built-in options** lists every distinct `[[Label: option | option | option]]` variable in the template (the same marker procedure notes use) as a checkbox group, e.g. `[[Extent: RALP without pelvic lymphadenectomy | RALP with standard pelvic lymphadenectomy | RALP with extended pelvic lymphadenectomy]]`. Options are declared once per label; a value needed in more than one place is written `[[Extent]]` at the later spots and the one control fills them all (a `n×` badge shows the count). A `[[Label]]` never declared with options anywhere is shown as a free-text-only field with a warning. **Fill selected options** substitutes the ticked value(s) in place — a client-side, deterministic operation with no AI call, so a fixed set of surgeon-authored choices is never rephrased or guessed at. Every generation uses the starting template and current selections (so re-picking replaces the prior choice rather than stacking on it); if manual edits or checklist answers have since changed the narrative, regenerating asks for confirmation and snapshots a checkpoint first. Placeholders `[[ … ]]` leaves unticked are untouched and still count toward "unresolved placeholders" for Copy warnings and Strip.

**Build case checklist** (`POST /api/finalize/`) returns one ordered list of items:

1. **Review questions** first — defaults in the note that may not apply to this case (laterality, nerve-sparing, node-dissection extent, drains, specimens, estimated blood loss, implants) and routine items that look missing.
2. Then **one item per unresolved Epic placeholder** — `***`, a token like `@AGE@`, or a `{…}` — in document order. Placeholders are found deterministically (`TOKEN_RE`, client-side, each shown with its sentence and the token marked); the provider supplies a targeted question for each (e.g. *"Which specific hemostatic product was used in the lymph node bed?"*, *"What is the patient's age?"*). Because a finalised narrative is pasted into Epic as plain text, placeholders will not auto-fill — this pass is where they get resolved.

Answer whichever items apply. Each placeholder item also offers **Keep `@X@` as an Epic field**, **Remove this line** (confirmed and listed first), and a per-item **insert exactly as typed** toggle. A negative answer — `no`, `none`, `n/a`, `not placed`, `we did not`, … — is treated as a **deterministic line removal** (listed in the confirm), never turned into a "No drain was placed." sentence; the AI integration prompt is also told to delete rather than negate. **Apply answers** first does a deterministic pass — verbatim inserts for toggled items, line removals — with no model involvement, then sends every other answer through the same edit contract and shows the result in the highlighted-diff review card. A **Strip unresolved placeholders** button removes any remaining tokens in one go (confirmed, snapshotted to draft history), and **Copy** warns when placeholders still remain. Nothing here touches the master template or is persisted; the same token/time/billing safety checks run on the AI pass. A checklist is bound to the narrative used to build it and can only be applied once. After applying answers or changing the narrative, rebuild the checklist before entering more answers. Responses built from a draft that changed while the request was running are discarded. If the AI checklist call fails, the placeholders are still listed for manual completion.

Only the source narrative and the supplied instruction are sent to the configured provider during case revision. For master updates, each selected master's narrative and the instruction are sent separately. Header, title, tags, original source and history are not included by the UI. The server accepts the current browser draft, so a user can still paste identifying content into it; removing the header does not guarantee de-identification.

The system contract demands source-based edits, no invented facts or clinical guidance, questions outside narrative, preservation of technique/style/tokens, and explicit handling of conflicts. Deterministic checks compare token counts (including unknown @tokens@, brace passages, and asterisk placeholders), warn about unresolved tokens/default no-complication statements, and reject newly introduced numeric time or modifier-22 claims unsupported by source/instructions. These checks are conservative and are **not a complete Epic grammar or a guarantee against fabrication**. Novel syntax may escape token detection. Read the entire proposal, questions, formatting and diff. Existing template defaults remain unverified.

No case prompts, drafts, or provider outputs are stored in the application database/session, browser storage, analytics or app error logs. They are transiently present in browser/server/provider memory. Navigation clears the UI; memory garbage collection, OS swap/crash reporting, browser extensions/session recovery, clipboard history, and hosting infrastructure are outside that guarantee. Copying does not clear a draft. Finish and clear does not clear your operating system clipboard. A completed AI request may outlive a closed page; it still has no application persistence path.

No universal provider retention promise can be made for a configurable endpoint. Before enabling real sensitive data, identify the provider/model, account retention controls and exceptions, contractual terms/BAA where applicable, approved hosting, access controls, backups and incident handling. Do not enable request-body tracing, session replay, proxy query/body logging or error-report capture. Login alone does not establish suitability for identifiable clinical data.

## Validation

```sh
source .venv/bin/activate
python manage.py test
python manage.py check
# With Google Chrome installed (each script starts its own isolated server):
python scripts/browser_smoke.py
python scripts/browser_regressions.py
```

Backend tests exercise search dimensions, authentication/ownership/CSRF, temporary cases leaving master/history unchanged, case header exclusion in UI-shaped requests, selected scope, rejection/no-save, approval/restore/stale checks, unfamiliar tokens and explicit removal review, AI failure and malformed response handling, conservative conflict/time checks, the line-by-line finalize endpoint (question build, answer integration, nothing persisted, validation/auth), export/import metadata equivalence/atomic rollback, safe rendering and rate limits, and PDF SmartPhrase extraction (segment splitting, false-positive ALL-CAPS lines, review flags, conservative HTML, non-PDF rejection) and the persistent import queue (dedup on re-upload, list/skip/import/restore/clear, owner scoping, banner count).

Both browser scripts create a disposable SQLite database and local server with the mock AI provider; they never open the working database or call an external AI provider. Browser smoke tests create and delete a random synthetic account. They exercise sign-in, import, narrative split, manual revision, plain/HTML clipboard, case customization, accepted proposal, draft clear, selected master approval, responsive width and settings, and assert no browser storage or JavaScript errors. Screenshots are written to `/private/tmp` for local review. The regression suite covers repeated procedure generation, manual-edit protection, operative `[[ … ]]` choice fields coexisting with the AI checklist, declare-once choice variables filling every `[[Label]]` reference from a single control (with undeclared-variable warnings in the fill panel and the master editor), the master editor's AI-improve proposal (staged into the editor, persisted only on save), stale/reused checklists, overlapping sentence removals and fills, formatted placeholders, and delayed grammar responses in every editor. Synthetic grammar responses exercise the review flow without an external AI call.

Automated mock/contract tests are application checks, not evaluations of variable real-model behavior. Real-model evaluation should include missing laterality/device details, conflicting complication assertions, difficult dissection without time estimates, unfamiliar tokens, intentional optional passage removal and malformed/timeout responses using synthetic content.

## Backups and restore

Portable JSON export includes templates, metadata, original source and every revision, but not accounts. Settings → Review a portable backup → Approve import adds copies under the logged-in account. It preserves timestamps and revision numbers with new local IDs.

For a complete consistent SQLite backup including authentication data:

```sh
python scripts/backup.py /private/approved-path/smartphrase-buddy-2026-09-05.sqlite3
```

Use an encrypted/private location and appropriate retention. For full restore, stop the app, preserve a backup of the current database, copy the selected backup to DATABASE_PATH with owner-only permissions, run migrations using the matching application version, then restart and verify login, template counts and revisions. Test recovery before relying on backups. The SQLite backup API avoids inconsistent copies of a live database.

## Deployment preparation (not deployed)

See `deploy/` for a single-host Gunicorn service and reverse-proxy example. Use an approved Linux host, private persistent disk, your domain's DNS, HTTPS, protected environment file and backups. Configure PRODUCTION=1, a strong DJANGO_SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS and DATABASE_PATH. Run migrations, collectstatic and `python manage.py check --deploy` under the production environment. Never expose runserver or Gunicorn directly to the public internet.

The example uses one Gunicorn worker with threads because the in-process login/AI limiter is shared only within one worker. A multi-worker deployment requires a shared limiter (or appropriately configured proxy rate limiting). Trust the proxy HTTPS header only behind the loopback-bound Gunicorn/proxy combination shown. Disable upstream request/query/body logging; rate limits here are basic single-user defenses, not a complete abuse-control platform. Follow the [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

Information needed at deployment: domain/DNS control, approved host, TLS termination arrangement, persistent/private backup locations, account provisioning, and—if enabled—approved AI provider/model/retention requirements. No hosting service, domain, account or deployment was created.

## Manual Epic paste checklist

Use synthetic material in your own Epic environment:

1. Copy plain and formatted paragraphs, headings, nested bullets and numbered lists; paste into the intended note field and compare line breaks/formatting.
2. Check literal @NAME@, @MRN@, @AGE@, @TD@, @ASOPNASSISTLINE@, {ASROBOASSIST:165493}, ***, duplicates and unfamiliar tokens. Determine whether they remain literal or activate; activation is unverified.
3. Confirm case output begins at the selected narrative boundary, excludes header and review commentary, and matches the text you approved.
4. Complete the Epic header separately; review the entire assembled note including unresolved defaults, contradictions and placeholders.
5. For changed reusable masters, manually update the intended Epic SmartPhrase and confirm the application has not altered another phrase. There is no automatic synchronization.

## Deferred

Screenshot/OCR extraction (image-only PDFs and screenshots; text-based Epic PDF export is implemented); saved case histories; reusable case-variation saving; shared-section propagation; Epic integration; MFA/SSO and formal production security review; real-provider integration/evaluation; domain deployment and actual Epic paste verification. No exact clinical contents were fabricated from missing screenshots.
