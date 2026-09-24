# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository shape

This repo hosts three **independent, unrelated single-page apps** under one GitHub Pages site — there is no shared build, no shared package.json, and no code shared between them (aside from copy-pasted CSS patterns). Each app is self-contained in its own directory and has no links to the others.

- `index.html` (repo root) — **PRD Assistant**: generates a Product Requirements Document from a short form.
- `job-analyzer/index.html` — **Job Offer Analyzer**: scores a job posting against an uploaded CV.
- `running-coach/` — **Running Coach**: Strava-linked adaptive training-plan app, split into modules (see Architecture below).

There is no `package.json`, no bundler, no linter, and no test suite anywhere in the repo.

## Commands

There is no build step. Each app is plain HTML/CSS/JS served as static files.

- **Develop/preview locally**: open the relevant `index.html` directly in a browser, or serve the repo root with any static file server, e.g. `python3 -m http.server` then visit `http://localhost:8000/`, `http://localhost:8000/job-analyzer/`, or `http://localhost:8000/running-coach/`.
- **Deploy**: pushing to `main` (or the `claude/inspiring-knuth-vnwryy` branch) triggers `.github/workflows/deploy.yml`, which uploads the entire repo root as-is to GitHub Pages. There is no build/compile step in CI — whatever is committed is what gets served.
- **Running Coach's Strava relay worker** (`running-coach/worker/`) is deployed separately via Cloudflare Wrangler, not GitHub Pages:
  ```bash
  cd running-coach/worker
  wrangler login
  wrangler secret put STRAVA_CLIENT_ID
  wrangler secret put STRAVA_CLIENT_SECRET
  wrangler deploy
  ```

## Architecture

### PRD Assistant (`index.html`) and Job Offer Analyzer (`job-analyzer/index.html`)

Both follow the same pattern, entirely client-side, single HTML file with inline `<style>` and `<script>`:

- The user supplies their own Anthropic API key via a banner input; it is kept only in `sessionStorage` (never sent anywhere but `api.anthropic.com`).
- Requests go **directly from the browser** to `https://api.anthropic.com/v1/messages` with `anthropic-dangerous-direct-browser-access: true` and `stream: true`; responses are consumed as SSE and rendered incrementally.
- Job Offer Analyzer additionally asks the model to return a single JSON object (parsed out of the streamed text with a regex once streaming completes) and renders it into scored/collapsible sections. It reads CVs client-side via `pdf.js` (loaded from a CDN) or plain text, and fetches job-posting URLs directly from the browser (best-effort; CORS failures fall back to "paste text").
- Generation history (and, for the analyzer, the parsed CV) persists in `localStorage`; there is no backend and no server-side storage anywhere in either app.

### Running Coach (`running-coach/`)

Unlike the other two apps, this one is split into ES modules loaded via `<script type="module">` from `index.html`:

- `app.js` — the entire UI: a hand-rolled router/state machine (`state`, `goto(route)`, `render()`) with view functions (`viewOnboardingStrava`, `viewGoalForm`, `viewDashboard`, `viewPlan`, `viewCheckin`, `viewSettings`) that render into `#app`. No framework.
- `plan-engine.js` — pure functions that generate and adapt a training plan (`generatePlan`, `buildWeekWorkouts`, `applyWeeklyCheckin`, `refreshPaceZones`, pace-zone math). No I/O; takes/returns plain data so it can reason about training weeks independent of the UI.
- `strava.js` — Strava OAuth + API client (`buildAuthorizeUrl`, `handleOAuthRedirect`, `fetchRecentRuns`, `summarizeByWeek`, `estimateFitness`). Talks to the relay worker, not Strava directly.
- `styles.css` — shared styles for the app shell.
- `worker/` — a separate Cloudflare Worker (`worker/src/index.js`) that exists solely to keep the Strava **Client Secret** out of the browser. It exposes `POST /exchange`, `POST /refresh`, and `GET /api/*` (a thin proxy to `https://www.strava.com/api/v3/*` that forwards the caller's `Authorization` header). It has no database and stores no per-user state — every request carries whatever token the front-end already holds.

All app state — goal, generated plan, weekly check-ins, and the Strava Client ID / worker URL entered in Settings — lives in the browser's `localStorage` (keys prefixed `rc_`). The worker's base URL is user-supplied per deployment, not hardcoded.
