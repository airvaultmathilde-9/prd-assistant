/**
 * Running Coach - Strava relay worker.
 *
 * The only job of this worker is to keep the Strava CLIENT_SECRET off the
 * browser and to give the static front-end a CORS-friendly way to talk to
 * the Strava API. It holds no database and no per-user state: every request
 * carries whatever token the front-end already has in localStorage.
 *
 * Routes:
 *   POST /exchange   { code }                -> Strava token exchange (authorization_code)
 *   POST /refresh     { refresh_token }        -> Strava token refresh
 *   GET  /api/*                                 -> proxied to https://www.strava.com/api/v3/*
 *                                                  (Authorization header forwarded as-is)
 *
 * Required secrets (wrangler secret put ...):
 *   STRAVA_CLIENT_ID
 *   STRAVA_CLIENT_SECRET
 *
 * Optional var (wrangler.toml [vars] or secret):
 *   ALLOWED_ORIGIN   e.g. "https://yourname.github.io"  (defaults to "*")
 */

const STRAVA_TOKEN_URL = 'https://www.strava.com/oauth/token';
const STRAVA_API_BASE = 'https://www.strava.com/api/v3';

function corsHeaders(env) {
  const origin = env.ALLOWED_ORIGIN || '*';
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Max-Age': '86400',
  };
}

function json(data, status, env) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      ...corsHeaders(env),
    },
  });
}

async function handleExchange(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'invalid_json' }, 400, env);
  }
  const { code } = body || {};
  if (!code) return json({ error: 'missing_code' }, 400, env);

  const params = new URLSearchParams({
    client_id: env.STRAVA_CLIENT_ID,
    client_secret: env.STRAVA_CLIENT_SECRET,
    code,
    grant_type: 'authorization_code',
  });

  const stravaRes = await fetch(`${STRAVA_TOKEN_URL}?${params.toString()}`, { method: 'POST' });
  const data = await stravaRes.json();
  if (!stravaRes.ok) return json({ error: 'strava_error', detail: data }, stravaRes.status, env);

  return json(
    {
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      expires_at: data.expires_at,
      athlete: data.athlete,
    },
    200,
    env
  );
}

async function handleRefresh(request, env) {
  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'invalid_json' }, 400, env);
  }
  const { refresh_token } = body || {};
  if (!refresh_token) return json({ error: 'missing_refresh_token' }, 400, env);

  const params = new URLSearchParams({
    client_id: env.STRAVA_CLIENT_ID,
    client_secret: env.STRAVA_CLIENT_SECRET,
    refresh_token,
    grant_type: 'refresh_token',
  });

  const stravaRes = await fetch(`${STRAVA_TOKEN_URL}?${params.toString()}`, { method: 'POST' });
  const data = await stravaRes.json();
  if (!stravaRes.ok) return json({ error: 'strava_error', detail: data }, stravaRes.status, env);

  return json(
    {
      access_token: data.access_token,
      refresh_token: data.refresh_token,
      expires_at: data.expires_at,
    },
    200,
    env
  );
}

async function handleApiProxy(request, env, pathname, search) {
  const auth = request.headers.get('Authorization');
  if (!auth) return json({ error: 'missing_authorization' }, 401, env);

  const upstreamPath = pathname.replace(/^\/api/, '');
  const upstreamUrl = `${STRAVA_API_BASE}${upstreamPath}${search}`;

  const stravaRes = await fetch(upstreamUrl, {
    method: request.method,
    headers: { Authorization: auth },
  });

  const body = await stravaRes.text();
  return new Response(body, {
    status: stravaRes.status,
    headers: {
      'Content-Type': stravaRes.headers.get('Content-Type') || 'application/json',
      ...corsHeaders(env),
    },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: corsHeaders(env) });
    }

    if (url.pathname === '/exchange' && request.method === 'POST') {
      return handleExchange(request, env);
    }
    if (url.pathname === '/refresh' && request.method === 'POST') {
      return handleRefresh(request, env);
    }
    if (url.pathname.startsWith('/api/')) {
      return handleApiProxy(request, env, url.pathname, url.search);
    }

    return json({ error: 'not_found' }, 404, env);
  },
};
