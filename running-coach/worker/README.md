# Running Coach — Strava relay worker

This is a tiny [Cloudflare Worker](https://workers.cloudflare.com/) whose only
job is to keep your Strava **Client Secret** off the browser. Everything else
(the plan engine, the UI, your data) lives in the static app and your own
browser's `localStorage` — this worker never stores anything.

It's free: the Cloudflare Workers free plan gives you 100,000 requests/day
with no credit card required, which is far more than a personal training app
will ever use.

## 1. Create a Strava API application

1. Go to https://www.strava.com/settings/api and create an app (or use an
   existing one).
2. Set **Authorization Callback Domain** to the domain where you'll host the
   front-end (e.g. `yourname.github.io`).
3. Note your **Client ID** and **Client Secret**.

## 2. Deploy the worker

You need Node.js installed locally.

```bash
cd running-coach/worker
npm install -g wrangler   # if you don't have it yet
wrangler login             # opens a browser to authorize your free Cloudflare account

# Store your Strava credentials as encrypted secrets (never committed to git):
wrangler secret put STRAVA_CLIENT_ID
wrangler secret put STRAVA_CLIENT_SECRET

wrangler deploy
```

Wrangler prints a URL like:

```
https://running-coach-strava-relay.<your-subdomain>.workers.dev
```

That's your **Worker Base URL** — paste it into the app's Settings screen.

## 3. (Optional) Lock down CORS

By default the worker accepts requests from any origin. Once your app is
live on GitHub Pages, you can restrict it: uncomment the `[vars]` block in
`wrangler.toml`, set `ALLOWED_ORIGIN` to your Pages URL (e.g.
`https://yourname.github.io`), then run `wrangler deploy` again.

## What this worker does (and doesn't do)

- `POST /exchange` — exchanges a Strava OAuth `code` for tokens using your
  Client Secret, then returns the tokens to the app.
- `POST /refresh` — refreshes an expired access token the same way.
- `GET /api/*` — proxies read calls to Strava's REST API (e.g.
  `/api/athlete/activities`), forwarding the `Authorization` header the app
  already has, and adding the CORS headers browsers require.
- It does **not** have a database, does **not** log or store your tokens,
  and does **not** see your training plan or check-ins — those never leave
  your browser's `localStorage`.
