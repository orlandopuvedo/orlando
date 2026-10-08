# 🎯 AI Job Hunter

A personal job-search command center built for one goal: **get hired in a remote role paying $2,000+/month**, prioritizing **$2,500–$4,000+**.

**Strategy:** max volume + high relevance + personalization + follow-up. The app finds and normalizes jobs, removes duplicates across boards, scores each one against **your real Master Profile**, ranks an Apply Queue, prepares truthful application packages (tailored resume, cover letter, answers, video link), runs a recruiter CRM, tracks interviews and follow-ups, and measures the whole funnel.

> **Truthfulness principle:** the Master Profile is the single source of truth. The AI may reorganize, summarize and adapt your real information. It **never** invents experience, companies, titles, years, degrees, certifications, languages, skills, metrics, achievements or legal status. Every generated text goes through a *fabrication guard* that flags numbers, names and claims not found in your profile.

---

## Inicio rápido (ES)

```bash
make install          # backend (venv) + frontend (npm)
make start            # compila el frontend y abre http://127.0.0.1:8000
```
1. **Profile**: complete your profile, or use **Import from resume** and confirm each field.
2. **Resumes**: upload your CV (PDF/DOCX/TXT).
3. **Videos**: paste your Loom link into "General Professional Introduction" and turn it on.
4. **Answers**: write your own answers to the frequent questions.
5. **Jobs → + Add job**: paste a job from LinkedIn/Indeed/etc. It is scored automatically.
6. **Apply Queue → Prepare**: review the package, apply, and click **Mark as applied**.
7. **Contacts / Interviews / Follow-ups**: record every interaction. The **Dashboard** shows how close you are to an offer.

---

## Table of contents
- [Architecture](#architecture)
- [Installation](#installation)
- [Environment variables](#environment-variables)
- [Database setup](#database-setup)
- [AI setup](#ai-setup)
- [Development](#development)
- [Production](#production)
- [Testing](#testing)
- [Using the app](#using-the-app)
- [Job sources & adding a new source](#job-sources)
- [Adding a new AI provider](#adding-a-new-ai-provider)
- [Browser agent configuration](#browser-agent-configuration)
- [Video library & Loom integration](#video-library)
- [Security](#security)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)

---

## Architecture

```
backend/                      FastAPI + SQLAlchemy 2 + Alembic (SQLite → PostgreSQL-ready)
  app/
    main.py                   app factory, migrations on startup, optional Basic auth, serves frontend/dist
    config.py                 env-based settings (.env)
    models/                   profile · jobs · applications · crm · system  (23 tables)
    api/                      REST routers: profile, resumes, library (videos/answers), jobs, applications, crm, system
    services/
      normalization.py        any raw job → canonical schema (salary, remote type, category, seniority, video, questions)
      salary.py               salary parsing + monthly-USD normalization
      detection.py            rule-based detectors (category, seniority, location limits, years, degree, languages, VIDEO, requirements)
      dedupe.py               cross-source duplicate detection → one canonical Job + many JobSourceRefs
      scoring.py              Job Match Score 0–100 (9 weighted components, hard caps, reasons & concerns)
      priority.py             Application Priority Score → Apply Queue order
      jobs_service.py         ingest (normalize → dedupe → store → score → queue), rescoring
      application_engine.py   APPLICATION PACKAGE builder + approval requests
      resume_parser.py        PDF/DOCX/TXT extraction + heuristic / AI structured parsing
      resume_tailor.py        tailored resume (reorder/select, never invent) + DOCX/TXT/MD export
      generation.py           cover letters, recruiter messages, follow-ups, answers (AI or templates)
      guardrails.py           fabrication guard
      pipeline.py             application statuses, allowed transitions, side effects
      crm.py                  contact status progression, timeline, interviews, profile views
      followups.py            follow-up recommendations, message generation, sent/postpone, due notifications
      analytics.py            funnel, rates, breakdowns, time series, learning-based recommendations, dashboard
      job_hunt.py             daily cycle (search → normalize → dedupe → score → filter → package → queue → video → reminders)
      scheduler.py            in-process scheduler (times set in Settings)
      loom.py                 Loom URL handling + public oEmbed metadata
      url_import.py           single-URL import (ATS APIs / schema.org JobPosting; blocked for prohibited sites)
    ai/                       AIProvider abstraction: anthropic, openai, google, ollama, none
    sources/                  JobSourceAdapter interface + adapters + registry (automation_status per source)
    browser/                  BrowserAgent abstraction, HTML detectors, Playwright agent, supervised runner
  migrations/                 Alembic migrations
  tests/                      pytest suite (76 tests)
frontend/                     React 18 + TypeScript + Vite (dark UI, no UI framework)
  src/pages/                  Dashboard, Jobs, JobDetail, ApplyQueue, Applications (Kanban), ApplicationDetail,
                              Approvals, Contacts (Kanban + profile views), ContactDetail (timeline), Interviews,
                              FollowUps, Resumes, Videos, Answers, Profile, Analytics, Settings
```

**Design decisions**
- **Deterministic scoring.** The match score is computed by rules, not by an LLM, so it is reproducible, explainable and cannot "hallucinate" a fit. AI is used only for wording, and only from profile facts.
- **Works without AI.** Every generator has a template fallback, so the app is fully usable with no API key.
- **Canonical jobs.** The same job seen on LinkedIn, Indeed and the company site becomes one `Job` with several `JobSourceRef`s, so you never apply twice.
- **Human-in-the-loop.** Salary, legal, demographic and uncertain answers, video requirements, blockers (CAPTCHA/login/2FA) and final submission all go through the **Approval queue**.

---

## Installation

Requirements: **Python 3.11+**, **Node 18+**.

```bash
git clone <this repo> && cd orlando
cp .env.example .env            # optional: add an AI key
make install                    # creates backend/.venv and installs frontend deps
make start                      # builds the frontend and serves everything on http://127.0.0.1:8000
```

Without `make`:
```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cd ../frontend && npm install && npm run build
cd ../backend && .venv/bin/uvicorn app.main:app --port 8000
```

The database is created and migrated automatically on first start (`RUN_MIGRATIONS_ON_STARTUP=true`).
First run also seeds: the job-source registry, 5 Video Library placeholders (no URLs, inactive) and 9 common application questions **with empty answers**. Only you can write truthful answers.

## Environment variables

See [`.env.example`](.env.example). Main ones:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///backend/data/jobhunter.db` | SQLAlchemy URL (PostgreSQL supported) |
| `DATA_DIR` | `backend/data` | uploads, exports, browser profile |
| `APP_HOST` / `APP_PORT` | `127.0.0.1` / `8000` | server bind |
| `APP_USERNAME` / `APP_PASSWORD` | – | enables HTTP Basic auth for the whole app |
| `AI_PROVIDER` | `auto` | `auto`, `anthropic`, `openai`, `google`, `ollama`, `none` |
| `AI_MODEL` | provider default | e.g. `claude-opus-5-5` |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` | – | provider keys (env only, never stored in DB) |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | local models |
| `SCHEDULER_ENABLED` | `true` | starts the in-process scheduler thread (the schedule itself is off until enabled in Settings) |
| `RUN_MIGRATIONS_ON_STARTUP` | `true` | run `alembic upgrade head` at boot |
| `BROWSER_HEADLESS` | `false` | Playwright agent visibility |
| `BROWSER_USER_DATA_DIR` | `backend/data/browser-profile` | persistent browser profile (you log in yourself) |
| `CORS_ORIGINS` | `http://localhost:5173,...` | dev frontend origins |

## Database setup

- **SQLite** (default) needs no setup. The file lives in `backend/data/` (git-ignored).
- **Migrations** (Alembic): `make migrate` or `cd backend && .venv/bin/alembic upgrade head`.
  New migration after changing models: `.venv/bin/alembic revision --autogenerate -m "describe change"`.
- **PostgreSQL**: `pip install "psycopg[binary]"`, then set `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/jobhunter` and run the migrations.
  The schema uses only portable types (JSON, timezone-aware DateTime, no SQLite-specific SQL). Batch mode is enabled for SQLite only.
- **Entities:** UserProfile, Resume, ResumeVersion, Video, ApplicationAnswer, Company, JobSource, Job, JobSourceRef, JobSearch, JobSearchRun, Application, ApplicationStatusHistory, GeneratedDocument, ApprovalRequest, Contact, ContactActivity, ProfileView, Interview, FollowUp, Notification, Setting, AutomationRule.
- **Backup:** copy `backend/data/` (DB + uploaded resumes).

## AI setup

1. Put a key in `.env` (e.g. `ANTHROPIC_API_KEY=...`) and restart.
2. Settings → **AI provider**: choose `auto` (first configured of Anthropic → OpenAI → Google) or a specific provider, and optionally a model.
3. The top bar shows the active provider. With no provider, deterministic templates are used.

The AI is used for: resume parsing (structured extraction), tailored resume summaries, cover letters, recruiter messages, screening-answer personalization and follow-up messages. Every prompt includes strict no-fabrication rules, and every output is checked by `guardrails.check_fabrication`. Warnings appear in the UI as **"Verify before sending"**.

Anthropic calls use the official `anthropic` SDK with server-side refusal fallback enabled (`fallbacks="default"`) and `effort: medium`.

## Development

```bash
make backend     # FastAPI with --reload on :8000
make frontend    # Vite dev server on :5173 (proxies /api → :8000)
```
API docs: http://127.0.0.1:8000/docs (OpenAPI).

## Production

Single process, single user, typically on your own machine or a small VPS:
```bash
make build                                   # frontend → frontend/dist (served by FastAPI)
APP_USERNAME=me APP_PASSWORD=strong-pass \
  backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```
- Put it behind HTTPS (Caddy/nginx) if it is reachable from the internet, and **always** set `APP_USERNAME`/`APP_PASSWORD`.
- Use one worker, because the scheduler runs in-process. For several workers, set `SCHEDULER_ENABLED=false` and trigger `POST /api/automation/run` from cron.

## Testing

```bash
make test        # backend: 76 pytest tests
make typecheck   # frontend: TypeScript strict
```
Coverage by area: profile, resume parsing (TXT/DOCX, import confirmation), job normalization, salary parsing, duplicate detection, job scoring (strong match, deal-breakers, custom weights), apply queue, application package generation, fabrication guard, approvals, video detection (phrases, false positives, submission type) and recommendation, contacts, contact activities and timeline progression, profile views, interview tracking and completion, follow-up lifecycle and recommendations, analytics and recommendations, dashboard funnel, notifications, settings, status transitions, source adapters (with recorded payloads), job-hunt cycle, URL import rules, browser detectors and the supervised agent (CAPTCHA/login/2FA stops, approvals, final submit), and the AI provider fallback.

## Using the app

| Page | What you do there |
|---|---|
| **Dashboard** | "How close am I?": current stage, progress bar, today vs daily target, offer value vs $2,000 target, KPIs, funnel, top of queue, interviews, follow-ups, recommendations |
| **Jobs** | Add jobs (paste / URL / source search), filter, re-score. Job detail shows *why it matches*, *potential concerns*, score breakdown, video recommendation, duplicates across sources, contacts |
| **Apply Queue** | Qualified jobs sorted by Priority Score. **Prepare** builds the package |
| **Applications** | Pipeline Kanban (DISCOVERED → QUALIFIED → READY → APPLYING → APPLIED → FOLLOW-UP → INTERVIEW → OFFER → REJECTED, drag & drop) and the list |
| **Application detail** | Tailored resume (DOCX/TXT/MD), cover letter (edit/regenerate/copy), screening answers, salary/availability, recruiter message, video link, checklist, mode, supervised agent, history, **Mark as applied** |
| **Approvals** | APPROVE / EDIT / SKIP for salary, legal, demographic, uncertain, video, blocked and final-submit items |
| **Contacts** | CRM Kanban (NEW → CONTACTED → REPLIED → SCREENING → INTERVIEW → FINAL → OFFER → HIRED), list, **Profile views** |
| **Contact detail** | Timeline (profile view, messages, email, call, screening, interview, follow-up, offer, rejection, note). Logging an activity updates the status and the linked application |
| **Interviews** | Schedule, edit, **Mark completed** (notes, questions asked, lessons, next steps). Thank-you and follow-up reminders are created automatically |
| **Follow-ups** | Recommended and custom reminders: generate message, copy, open email/LinkedIn, mark sent, postpone. Nothing is ever sent automatically |
| **Resumes / Videos / Answers** | Your libraries |
| **Profile** | Master Profile + resume import with field-by-field confirmation |
| **Analytics** | Rates, applications per day/week/month, breakdowns (source, category, company, salary range, resume version, application type, contact source) and "what's working" recommendations |
| **Settings** | Thresholds, daily target, per-company/per-source limits, follow-up timing, cover-letter policy, **score & priority weights**, application mode, scheduler times, sources, company boards, AI provider |

**Scoring.** Default weights: salary 20, skills 20, experience 15, role relevance 15, remote/location 10, education/certifications 5, language 5, seniority 5, application difficulty 5. Bands: 90–100 EXCELLENT · 80–89 STRONG · 70–79 GOOD · 60–69 MAYBE · 0–59 SKIP. Hard caps stop deal-breakers from being averaged away: below-minimum salary → max 55, incompatible location/arrangement → max 50, excluded industry/category → max 40, non-preferred employment type → max 65.

**Priority.** Match 35, salary 15, recency 10, ease 10, competition 5, recruiter contact 5, video readiness 5, tailored resume 5, quick apply 5, historical interview rate of the category 5. It updates as you get results.

<a id="job-sources"></a>
## Job sources & adding a new source

Every source implements `JobSourceAdapter` (`backend/app/sources/base.py`):

```python
class JobSourceAdapter(ABC):
    key, name, base_url
    automation_status: "allowed" | "review_required" | "manual_only" | "unknown"   # searching
    apply_automation_status: same values                                           # applying
    def search_jobs(self, q: SearchQuery) -> list[dict]
    def get_job(self, external_id, config=None) -> dict | None
    def normalize_job(self, raw, usd_rates=None) -> NormalizedJob
    def detect_duplicate(self, db, nj) -> DuplicateMatch | None
```

| Source | Search | How |
|---|---|---|
| Remotive | allowed | official public API (`/api/remote-jobs`), rate-limited, attribution |
| Remote OK | allowed | public JSON API (`/api`), attribution |
| Himalayas | allowed | public jobs API (`/jobs/api`) |
| We Work Remotely | allowed | official RSS feeds |
| Company career pages | allowed | Greenhouse Job Board API, Lever Postings API, Ashby Posting API (read-only; set board names in Settings) |
| LinkedIn, Indeed, Wellfound, Remote.co, JustRemote, Dynamite Jobs, Built In, FlexJobs | manual_only | no permitted public API → paste the job (title + description + URL) |
| Working Nomads | unknown | no confirmed public API → manual |
| Upwork | review_required | official GraphQL API needs an approved OAuth app; not connected → manual |

**Add a source:**
1. Create a class in `backend/app/sources/` that subclasses `JobSourceAdapter`, sets `key/name/automation_status`, and maps the source's documented API fields to the loose keys used by `normalize_job` (`title, company, description, source_url, apply_url, location, salary_min/max/currency/period or salary_text, posted_at, job_id_external, ...`).
2. Register it in `all_adapters()` (`sources/registry.py`).
3. Add a test with a recorded payload using `httpx.MockTransport` (see `tests/test_sources.py`).
4. Enable it in **Settings → Sources**. Only `allowed` sources can be enabled.

**Never** scrape sites that forbid it or bypass protections. If there is no permitted mechanism, the adapter must stay `manual_only`.

## Adding a new AI provider

1. Subclass `AIProvider` (`backend/app/ai/base.py`) and implement `is_available()` and `complete(system, prompt, max_tokens) -> str` (raise `AIProviderError` on failure).
2. Add it to `build_provider()` and `PROVIDERS` in `backend/app/ai/registry.py`, reading its key from `config.Settings` (env).
3. That's it: all generators call the provider through the interface and fall back to templates if it fails.

## Browser agent configuration

Modes: **Copilot** (default: AI prepares, you submit), **Supervised** (agent fills forms, asks before anything sensitive and before submitting) and **Auto** (only where a source's apply automation is `allowed` *and* you enabled it. None of the built-in boards qualify).

```bash
make install-browser            # pip install playwright + browser
# .env
BROWSER_HEADLESS=false           # visible window: you log in / solve challenges yourself
BROWSER_USER_DATA_DIR=./backend/data/browser-profile
```
Use it from an application page: set the mode to *Supervised*, then **Run supervised agent**. The agent (`backend/app/browser/`):
- refuses domains that prohibit automation (LinkedIn, Indeed, …) and sources with `manual_only`/`unknown` apply status;
- opens the apply URL, inspects the page, and **stops** on CAPTCHA, login or 2FA. It creates a "blocked" approval and notification, and you take over;
- fills only safe profile fields (name, email, phone, LinkedIn, portfolio, location), uploads the tailored resume, and uses approved answers;
- sends salary, legal, demographic, video and uncertain fields to the Approval queue;
- clicks submit **only** after you approve "Application is ready to submit" and re-run it.

`BrowserAgent` methods: `open_page, navigate, inspect_page, extract_text, click, type, select, upload_file, detect_captcha, detect_login, detect_2fa, detect_video_requirement, detect_file_upload, request_human_approval, submit`. No anti-bot bypassing is implemented, and none should be.

<a id="video-library"></a>
## Video library & Loom integration

- Store each video's name, description, URL, platform, duration, tags, transcript, date and active flag. Five placeholders are seeded (General / Sales / Operations / Customer Support / AI-Automation Introduction): add your URL and activate them.
- **Video detection** (`detection.detect_video_requirement`) covers phrases like "record a video", "submit a video", "5 minute video", "video introduction", "video interview", "Loom", "record yourself", "tell us … on video", one-way interview platforms, and Spanish variants. It extracts the duration and the submission type (`url` / `file` / `platform`). Tool lists such as "Slack, Loom, Notion" are not counted.
- **Recommendation** (`video_matching.py`) matches job category and title against tags and name, prefers active videos with URLs and a matching duration, and falls back to your general introduction. SDR → Sales Introduction, Operations → Operations Introduction, AI Automation → AI/Automation Introduction, anything else → General.
- The package shows the recommended video and URL, and creates a **video approval**. If the application needs a video **file** or a proprietary platform (HireVue, Willo, …), you're asked to do it yourself.
- **Loom:** Loom's official developer products (record/embed SDKs) are for embedding recording in your own app. They don't let a third-party app submit your videos to job applications. So the "adapter" here only normalizes share URLs and reads public metadata through Loom's **oEmbed** endpoint (Videos → *Fetch Loom info*). No private APIs, no scraping.

## Security

- **No platform passwords are stored.** For the browser agent you log in yourself in a persistent local browser profile.
- **No banking/payment data** is collected anywhere.
- **API keys only via environment variables.** They are never written to the database or returned by the API (the API only reports whether a key is set).
- Personal data (DB, resumes, exports, browser profile) lives in `backend/data/`, which is git-ignored. Back it up and keep it private.
- Binds to `127.0.0.1` by default. Set `APP_USERNAME`/`APP_PASSWORD` (constant-time compared) and use HTTPS before exposing it.
- Uploads are limited to PDF/DOCX/TXT/MD, max 10 MB, and stored under random names.
- No credential harvesting, no CAPTCHA/anti-bot/2FA/rate-limit bypass, and no automatic sending of messages.

## Known limitations

- **Job boards without permitted APIs** (LinkedIn, Indeed, Wellfound, FlexJobs, …) are manual import only, by design.
- Public APIs change. The adapters are tested against recorded payloads, but the live endpoints could not be called from the build environment, so verify them on first use (errors are shown per source in Settings → Sources).
- Heuristic resume parsing (no AI key) handles common layouts. Unusual layouts or scanned PDFs (no text layer) need manual entry or an AI provider. Import always asks you to confirm.
- The fabrication guard is conservative and lexical: it flags unverified numbers, proper nouns and claim words, but cannot prove semantic truth. Always read before sending.
- The supervised agent handles single-page forms. Multi-step wizards may need several runs or manual completion. Custom widgets (React selects, iframes) may not be fillable.
- Currency conversion uses static rates (override them with the `usd_rates` setting via `PUT /api/settings`).
- Single-user app. One uvicorn worker if you use the in-process scheduler.
- Profile views can only be recorded manually unless an official integration exposes them. The app never guesses viewers.

## Roadmap

- **Phase 1 (done):** architecture, database & migrations, Master Profile, resume system, Video Library, job model, scoring, applications & packages, approvals, contacts CRM, interviews, follow-ups, dashboard, analytics, Apply Queue, notifications, settings.
- **Phase 2 (started):** official-API sources (Remotive, Remote OK, Himalayas, WWR RSS, Greenhouse/Lever/Ashby), scheduler, supervised browser agent. Next: more ATS boards (Workable, SmartRecruiters, Recruitee), multi-step form support, email (IMAP/Gmail API) import of recruiter replies.
- **Phase 3:** advanced analytics (A/B of resume versions, time-to-response), optimization of weights from outcomes, calendar integration for interviews.
