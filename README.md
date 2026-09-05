# Phrasebook

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

For a synthetic walkthrough: New phrase / import → Load synthetic example → Use pasted source → Suggest split → inspect both editors → check review confirmation → Approve import. To import your originals, paste them into the source editor and perform the same review, assign metadata/aliases, and adjust the header manually where necessary. Paragraphs, headings, emphasis and lists are supported; images, tables, links, arbitrary styling and active markup are deliberately not retained in editable content. Original source is stored separately as inert text.

Configuration is through environment variables (see `.env.example`; it is not loaded automatically). The development secret is generated into the ignored `.local-secret`. SQLite defaults to ignored `private.sqlite3`. **This checkout is inside an iCloud folder: keep development synthetic, and set DATABASE_PATH to a private, approved, non-synchronized location before storing sensitive reusable content.** Backups/exports and original imports may contain sensitive information too.

Rebuild after frontend changes:

```sh
npm ci
npm run build
```

## Implemented workflows

- Persistent create/read/update/delete library; title, Epic name, type, tags, aliases, favorites, timestamp and revision metadata.
- Search all requested fields; type/exact-tag/favorite filters, previews, rich/plain copying without AI.
- Manual paste import review, preserved source, adjustable Epic header/narrative split, fixed-age flag.
- Epic SmartPhrase **PDF import**: upload an Epic "print SmartPhrases" export, get one unapproved draft per detected phrase (name, extracted text, per-segment flags for letterhead / disclaimer / fixed age / missing tokens / bracket placeholders), then review and approve each through the normal flow. The PDF is parsed in memory and never stored or logged; nothing is silently repaired. See "PDF import" below.
- Master editing, full revision history, restore as a new revision, stale-save protection.
- Selected-template proposals, per-template text diff, manually editable proposal, explicit acceptance/rejection, scope enforcement and token-change review.
- Separate in-memory operative drafts, iterative free-text AI instructions, manual editing, undo/redo, copy approval checkbox, Finish and clear, navigation warning.
- JSON portable import/export with complete revision metadata and timestamps. Import adds independent copies; it never overwrites existing templates. Imports are atomic and capped at 500 templates / about 1.9 MB; use database restore for larger libraries.
- Login/logout, password change, no public signup, authenticated API, ownership checks, CSRF, no-store responses, strict content security policy, request size limits, login/AI rate limits.
- Configurable mock or HTTPS chat-completions-compatible AI provider, timeout and malformed-result handling, server-only secrets.

## PDF import

Many Epic builds let a user print/export their SmartPhrases to PDF. In **New phrase / import → Import from an Epic SmartPhrase PDF export**, choose that file. The server (`library/pdfimport.py`, using `pypdf`) extracts the selectable text and splits it into segments: a line that is only an uppercase token (`ASOPNSPRALP`, `ASLIBTPVSTR`, …) and is preceded by a blank line starts a new segment; text before the first such line becomes an unnamed segment. Each segment is returned with the detected name, the extracted text, a conservative plain-text→HTML rendering (one paragraph per line, bullet lists preserved — no headings or emphasis inferred), and review flags (letterhead lines, patient-facing disclaimer blocks, a fixed patient age, no Epic tokens detected, `[ … ]` bracket placeholders).

"Load this phrase for review" drops one segment into the import source editor and prefills the title/Epic name; you then set type/tags, click **Use pasted source**, adjust the Epic header boundary, and **Approve** — exactly as for pasted text. The split is best effort: names stay editable, an over-split segment is just extra text you can move, and ALL-CAPS lines inside content (wrapped headings, `NOTES`, `MONITORING`) are deliberately not treated as new phrases when they are not preceded by a blank line.

Privacy: the upload is held in memory only (`FILE_UPLOAD_HANDLERS` is memory-only, 25 MB cap), parsed, and discarded — no PDF, extracted text, or segment list is written to the database, session, browser storage, or logs. `pypdf` logging is routed to a null handler. Scanned image-only PDFs (no text layer) are rejected with guidance rather than OCR'd.

## AI configuration and limitations

Default `AI_PROVIDER=mock` is a deterministic demonstration, not a clinical editing model. It only appends the supplied synthetic inflammation/scarring statement for the matching demonstration instruction; otherwise returns unchanged content with a manual-review question. It performs no external requests and must not be used to evaluate clinical AI quality.

For a provider with a compatible `/chat/completions` API accepting JSON-object response format, set `AI_PROVIDER=compatible`, `AI_BASE_URL` (HTTPS URL ending in `/v1`), `AI_MODEL`, and `AI_API_KEY` in the server environment. No provider is chosen or paid account provisioned. Providers with other APIs need an adapter in `library/services.py`. Credentials are never sent to the browser. Real endpoint compatibility and model quality have not been tested without credentials.

Only the source narrative and the supplied instruction are sent to the configured provider during case revision. For master updates, each selected master's narrative and the instruction are sent separately. Header, title, tags, original source and history are not included by the UI. The server accepts the current browser draft, so a user can still paste identifying content into it; removing the header does not guarantee de-identification.

The system contract demands source-based edits, no invented facts or clinical guidance, questions outside narrative, preservation of technique/style/tokens, and explicit handling of conflicts. Deterministic checks compare token counts (including unknown @tokens@, brace passages, and asterisk placeholders), warn about unresolved tokens/default no-complication statements, and reject newly introduced numeric time or modifier-22 claims unsupported by source/instructions. These checks are conservative and are **not a complete Epic grammar or a guarantee against fabrication**. Novel syntax may escape token detection. Read the entire proposal, questions, formatting and diff. Existing template defaults remain unverified.

No case prompts, drafts, or provider outputs are stored in the application database/session, browser storage, analytics or app error logs. They are transiently present in browser/server/provider memory. Navigation clears the UI; memory garbage collection, OS swap/crash reporting, browser extensions/session recovery, clipboard history, and hosting infrastructure are outside that guarantee. Copying does not clear a draft. Finish and clear does not clear your operating system clipboard. A completed AI request may outlive a closed page; it still has no application persistence path.

No universal provider retention promise can be made for a configurable endpoint. Before enabling real sensitive data, identify the provider/model, account retention controls and exceptions, contractual terms/BAA where applicable, approved hosting, access controls, backups and incident handling. Do not enable request-body tracing, session replay, proxy query/body logging or error-report capture. Login alone does not establish suitability for identifiable clinical data.

## Validation

```sh
source .venv/bin/activate
python manage.py test
python manage.py check
# With the local server running on port 8765 and Google Chrome installed:
python scripts/browser_smoke.py
```

Backend tests exercise search dimensions, authentication/ownership/CSRF, temporary cases leaving master/history unchanged, case header exclusion in UI-shaped requests, selected scope, rejection/no-save, approval/restore/stale checks, unfamiliar tokens and explicit removal review, AI failure and malformed response handling, conservative conflict/time checks, export/import metadata equivalence/atomic rollback, safe rendering and rate limits, and PDF SmartPhrase extraction (segment splitting, false-positive ALL-CAPS lines, review flags, conservative HTML, endpoint auth/method/no-persistence, non-PDF rejection).

Browser smoke tests create and delete a random synthetic account. They exercise sign-in, import, narrative split, manual revision, plain/HTML clipboard, case customization, accepted proposal, draft clear, selected master approval, responsive width and settings, and assert no browser storage or JavaScript errors. Screenshots are written to `/private/tmp` for local review. Run against a development database only.

Automated mock/contract tests are application checks, not evaluations of variable real-model behavior. Real-model evaluation should include missing laterality/device details, conflicting complication assertions, difficult dissection without time estimates, unfamiliar tokens, intentional optional passage removal and malformed/timeout responses using synthetic content.

## Backups and restore

Portable JSON export includes templates, metadata, original source and every revision, but not accounts. Settings → Review a portable backup → Approve import adds copies under the logged-in account. It preserves timestamps and revision numbers with new local IDs.

For a complete consistent SQLite backup including authentication data:

```sh
python scripts/backup.py /private/approved-path/phrasebook-2026-09-05.sqlite3
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
