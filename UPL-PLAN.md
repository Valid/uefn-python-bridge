# UPL — UEFN Python Library

**Website:** uefn.sh
**Full name:** UEFN Python Library
**Short name:** UPL

A community hub where UEFN developers share, discover, and download Python scripts for the Unreal Editor for Fortnite. Think of it as the place you go to find tools other creators have built — lighting setups, level generators, batch editors, automation scripts — anything that runs inside UEFN's Python environment.

---

## Why This Exists

Epic added Python scripting to UEFN but there's no ecosystem around it yet. No central place to find scripts, no way to know what other people have built, no trust layer for running someone else's code inside your editor. UPL fills that gap.

The [uefn-python-bridge](https://github.com/Valid/uefn-python-bridge) is the open-source foundation — it gives external tools (AI agents, scripts, automation) a way to talk to UEFN. UPL is the ecosystem layer on top: a curated, searchable library of Python scripts that the community builds and shares.

---

## What Gets Shared

**Python scripts** that run inside UEFN via **Tools → Execute Python Script**.

A script can be a single `.py` file or a folder with multiple files (UI modules, utilities, configs, etc.). Every script on UPL is source-available — no obfuscated code, no compiled binaries, no exceptions.

Examples of what people might publish:
- Lighting preset tools (one-click mood setups)
- Batch actor renaming / organization utilities
- Procedural placement tools (scatter objects, generate grids, create patterns)
- Level audit scripts (find broken references, count actors by type, performance checks)
- Material batch editors
- Asset import/export helpers
- Custom editor UI panels
- Testing and validation tools

### What UPL Is Not (MVP)

- Not a package manager with dependency resolution
- Not a place for bridge `@command` extensions (those go as PRs to the bridge repo)
- Not a place for AI agent rule files (may add later)
- Not a CLI tool (everything is web-based)

Contributors who want to add core capabilities to the bridge itself should submit PRs to [uefn-python-bridge](https://github.com/Valid/uefn-python-bridge). UPL is for standalone tools built on top.

---

## How It Works

### For Users (Downloading Scripts)

1. Browse or search uefn.sh
2. Find a script you want
3. Click **Download** → get a `.zip` file
4. Extract it somewhere on your machine
5. In UEFN: **Tools → Execute Python Script** → select the main `.py` file
6. Done

No CLI, no terminal commands, no package.json. Download, extract, run.

### For Authors (Sharing Scripts)

1. Log in with your **Epic Games account** (OAuth)
2. Click **Upload**
3. Fill in the form:
   - **Slug** — URL-friendly identifier (e.g. `lighting-presets`)
   - **Display Name** — human-readable name (e.g. "Lighting Presets Toolkit")
   - **Version** — starts at `1.0.0`, bump when you update
   - **Description** — what it does, how to use it (markdown, rendered on the page)
   - **Category** — pick from a list (Lighting, Materials, Level Design, Automation, UI Tools, Utilities, Other)
   - **Tags** — freeform tags for search (e.g. `lighting`, `presets`, `mood`, `one-click`)
   - **Screenshots** — optional, drag and drop images/gifs showing the tool in action
4. **Drop your files** — drag a folder or individual `.py` files into the upload area. We keep folder structure intact and flatten the outer wrapper automatically.
5. **Changelog** — describe what's in this version (required for updates, optional for first upload)
6. **License** — all scripts on UPL are published under **MIT-0** (free to use, modify, redistribute, no attribution required). Authors check a box confirming they have the rights and agree to publish under MIT-0.
7. Click **Submit**

The upload goes through automated security review. Clean scripts are published immediately. Flagged scripts go to manual review (usually < 24 hours).

### For Updates

Same upload form, but with "Upload New Version" on the existing script page. Version number is bumped, changelog is required, files go through security review again. Previous versions remain available in version history.

---

## Security

Scripts run inside the UEFN editor process with full `unreal.*` access. A malicious script could delete actors, corrupt files, or worse. Security is the foundation, not a feature.

### Supply Chain Protection

- **UPL hosts all code.** When an author uploads files, we store our own copy. Downloads always come from uefn.sh, never from an external repo.
- **No auto-sync from author repos.** If an author's GitHub gets compromised, it doesn't affect UPL. Updates require explicit re-upload through the website with a new security review.
- **Every version is immutable.** Once published, a version's files cannot be changed. Authors must publish a new version to make changes.

### Automated AI Code Review

Every upload is scanned by an AI reviewer that understands UEFN Python patterns. The scan looks for:

**Auto-reject (blocks publishing):**
- `os.system()`, `subprocess.run()`, `subprocess.Popen()` — arbitrary command execution
- `shutil.rmtree()` on paths outside the UEFN project directory
- Network calls to external hosts (`requests`, `urllib`, `http.client`, `socket` to non-localhost)
- `eval()` / `exec()` on external input or decoded data
- Base64-encoded strings that get decoded and executed
- Obfuscated or minified code
- Binary files disguised as `.py`

**Flagged for manual review:**
- `import os` / `import subprocess` (check context — many legitimate uses exist)
- File I/O (legitimate for configs, exports, saved presets — reviewer checks paths)
- Dynamic imports (`importlib`, `__import__`)
- Unusually large files with minimal documentation
- Code that modifies other scripts or the bridge itself

**Not flagged (normal UEFN patterns):**
- `import unreal` and all `unreal.*` API usage
- Reading/writing files within the UEFN project directory
- HTTP calls to `127.0.0.1` (bridge communication)
- `json`, `math`, `os.path` usage

### Safety Tiers

Every script gets a visible safety badge on its listing:

- 🟢 **Safe** — no file I/O, no imports beyond `unreal` and stdlib basics. Read-only operations.
- 🟡 **Standard** — modifies level data (spawns/deletes actors, changes properties). This is normal for most tools.
- 🟠 **Extended** — uses filesystem operations (saving configs, exporting data, reading files). Legitimate but users should understand the scope.

### Verified Authors

- Authors log in with Epic Games OAuth → verified Epic account
- Display name and avatar pulled from Epic profile
- Publishing history is public — you can see everything an author has shared
- Repeat authors with clean history build visible trust (download counts, ratings, time on platform)

### Community Reporting

- Any user can flag a script with a reason
- Flags trigger an AI deep-scan of the code + notification to the moderation queue
- **No auto-delist** — reports are reviewed by a human to prevent abuse (competitors flagging each other, grudge reports, etc.)
- If a script is confirmed malicious: removed immediately, author notified, repeat offenders banned

---

## Platform Features

### Script Pages

Each script gets a dedicated page with:
- Rendered README/description (markdown with image support)
- Screenshots / GIFs (carousel)
- Download button (latest version zip)
- Version history with changelogs
- Safety tier badge (🟢 🟡 🟠)
- Download count (total + per version)
- Star rating (1–5, averaged)
- Comments section
- Author info (Epic name, avatar, other scripts, join date)
- Tags and category
- "Last updated" timestamp
- File list preview (see what's in the zip before downloading)
- "Report" button

### Browse & Search

- **Categories:** Lighting, Materials, Level Design, Automation, UI Tools, Utilities, Gameplay, Other
- **Sort by:** Popular (downloads), Top Rated, Recently Updated, Newest
- **Filter by:** Category, Safety Tier, Minimum Rating
- **Search:** full-text across name, description, tags, author name
- **Trending:** scripts gaining downloads/stars faster than average

### Author Dashboard

- Upload new scripts / new versions
- View download stats (total, per version, over time)
- View ratings and read comments
- Respond to comments
- Edit script metadata (description, tags, screenshots — not files, those require a new version)

### User Features

- Star/rate scripts (requires Epic login)
- Comment on scripts (requires Epic login)
- Download history ("My Downloads" — track what you've grabbed)
- Follow authors (get notified of new scripts/updates)
- Collections/bookmarks ("My Favorites")

---

## Monetization

### MVP: Free Everything

- Free to upload
- Free to download
- No premium tiers
- No ads

### Future: Tips

- **Author tip jar** — each author can link a payment method (Stripe Connect, Ko-fi, or similar). Users can tip directly from the script page. UPL takes zero cut (or minimal processing fee).
- **Service tip jar** — "Support UPL" page/button. Voluntary contributions to keep the site running. Transparent about costs (hosting, storage, AI review API calls).

No paid listings, no premium features for authors, no paywalling downloads. Ever. The value is in the community, not in extracting money from it.

---

## Tech Stack

### Website
- **Framework:** Next.js (React/TypeScript)
- **Hosting:** Vercel
- **Domain:** uefn.sh

### Backend / Data
- **Database:** Supabase (PostgreSQL) — users, scripts, versions, ratings, comments
- **File storage:** Cloudflare R2 or AWS S3 — zip files, screenshots
- **Auth:** Epic Games OAuth2 (primary), optionally GitHub OAuth as secondary

### Security Pipeline
- **AI code review:** Claude API (Anthropic) — scans uploaded `.py` files on every submission
- **Static analysis:** Custom rules engine for hard-block patterns (regex + AST parsing)

### Search
- **Full-text search:** Supabase built-in (pg_trgm + ts_vector) for MVP
- **Upgrade path:** Algolia or Meilisearch if search volume demands it

---

## Relationship to uefn-python-bridge

UPL and the bridge are complementary but separate:

| | uefn-python-bridge | UPL (uefn.sh) |
|---|---|---|
| **What** | Open-source HTTP bridge server | Community script library |
| **Repo** | github.com/Valid/uefn-python-bridge | Private (uefn.sh website) |
| **Content** | Core bridge commands, client library | User-contributed Python scripts |
| **Contributions** | PRs to add `@command` extensions | Upload scripts through the website |
| **License** | MIT | MIT-0 for all published scripts |
| **Who runs it** | Community (open source) | Jon / FCHQ team |

Scripts on UPL may or may not use the bridge. Some scripts work standalone (run directly in UEFN via Execute Python Script). Others might use the bridge for external automation. Both are welcome.

The bridge README links to UPL for discovering community tools. UPL links to the bridge for people who want programmatic access.

---

## MVP Scope

### Must Have (Launch)
- [ ] Epic OAuth login
- [ ] Upload form (drag-drop files, metadata fields, screenshots)
- [ ] AI code review pipeline (auto-publish clean, queue flagged)
- [ ] Script pages with README, download, version history
- [ ] Browse with categories, sort, search
- [ ] Download counter
- [ ] Star ratings
- [ ] Comments
- [ ] Safety tier badges
- [ ] Community report button → moderation queue
- [ ] Author dashboard (upload, stats, respond to comments)
- [ ] Immutable versions (no editing published files)
- [ ] All code stored on our infrastructure

### Nice to Have (Post-Launch)
- [ ] Author tip jar (Stripe Connect)
- [ ] Service tip jar
- [ ] Follow authors / notifications
- [ ] Collections / bookmarks
- [ ] Trending algorithm
- [ ] "My Downloads" history
- [ ] File preview (view code before downloading)
- [ ] Integration with UEFN Copilot (browse/install from within the overlay)
- [ ] AI agent rule files as a category
- [ ] Bridge `@command` extension packages
- [ ] Discord bot (new script notifications, search from Discord)
- [ ] API for programmatic access to the registry

---

## Open Questions

1. **Moderation staffing** — who reviews flagged scripts beyond Jon? Community moderators? Trusted authors?
2. **Content guidelines** — beyond security, are there quality standards? (e.g., must include a description, must actually run, etc.)
3. **Namespace conflicts** — first-come-first-serve on slugs? Or reserve common terms?
4. **DMCA / IP claims** — process for "this script copies my code" disputes
5. **Epic's stance** — any terms of service implications for a third-party UEFN tool registry? Worth a preemptive conversation?
6. **Analytics** — beyond download counts, do we track anything else? (referrers, popular search terms, etc.)
7. **Branding** — logo, color palette, visual identity. Lean into the UEFN aesthetic or build a distinct brand?

---

## Timeline (Rough)

**Phase 1 — Foundation (2-3 weeks)**
- Set up Next.js project, Supabase, R2 storage
- Epic OAuth integration
- Upload form + file storage
- Basic script pages

**Phase 2 — Security (1-2 weeks)**
- AI code review pipeline
- Safety tier classification
- Moderation queue UI

**Phase 3 — Community (1-2 weeks)**
- Ratings, comments, download counts
- Browse/search/filter
- Author dashboard

**Phase 4 — Polish & Launch (1 week)**
- Design pass, responsive, performance
- Seed with 5-10 example scripts
- Announce to UEFN community

**Total: ~6-8 weeks to MVP launch**
