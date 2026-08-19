/**
 * Strava client — talks to the Cloudflare Worker relay, never to Strava
 * directly (except the OAuth authorize redirect, which is a full page
 * navigation and doesn't need CORS). All tokens/config live in
 * localStorage; this module has no server-side state of its own.
 */

const STORAGE_KEY = 'rc_strava_v1';
const SCOPES = 'read,activity:read_all,profile:read_all';

function load() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function save(patch) {
  const current = load();
  const next = { ...current, ...patch };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  return next;
}

export function getConfig() {
  const s = load();
  return { clientId: s.clientId || '', workerUrl: (s.workerUrl || '').replace(/\/+$/, '') };
}

export function saveConfig({ clientId, workerUrl }) {
  save({ clientId: clientId.trim(), workerUrl: workerUrl.trim().replace(/\/+$/, '') });
}

export function isConfigured() {
  const { clientId, workerUrl } = getConfig();
  return Boolean(clientId && workerUrl);
}

export function isConnected() {
  const s = load();
  return Boolean(s.accessToken && s.refreshToken);
}

export function getAthlete() {
  return load().athlete || null;
}

function redirectUri() {
  const url = new URL(window.location.href);
  url.search = '';
  url.hash = '';
  return url.toString();
}

export function buildAuthorizeUrl() {
  const { clientId } = getConfig();
  const params = new URLSearchParams({
    client_id: clientId,
    redirect_uri: redirectUri(),
    response_type: 'code',
    approval_prompt: 'auto',
    scope: SCOPES,
  });
  return `https://www.strava.com/oauth/authorize?${params.toString()}`;
}

export function connect() {
  window.location.href = buildAuthorizeUrl();
}

export function disconnect() {
  const { clientId, workerUrl } = getConfig();
  localStorage.removeItem(STORAGE_KEY);
  save({ clientId, workerUrl });
}

/**
 * If the current URL carries a Strava OAuth ?code=, exchange it for tokens
 * via the worker and scrub the query string. Returns true if a callback was
 * handled (so the caller can re-render).
 */
export async function handleOAuthRedirect() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const error = params.get('error');

  if (error) {
    window.history.replaceState({}, '', window.location.pathname);
    throw new Error(`Strava authorization was denied (${error}).`);
  }
  if (!code) return false;

  const { workerUrl } = getConfig();
  if (!workerUrl) {
    window.history.replaceState({}, '', window.location.pathname);
    throw new Error('Missing Worker Base URL — set it up in Settings first.');
  }

  const res = await fetch(`${workerUrl}/exchange`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  });
  window.history.replaceState({}, '', window.location.pathname);

  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Strava token exchange failed: ${detail}`);
  }
  const data = await res.json();
  save({
    accessToken: data.access_token,
    refreshToken: data.refresh_token,
    expiresAt: data.expires_at,
    athlete: data.athlete || load().athlete,
  });
  return true;
}

async function ensureFreshToken() {
  const s = load();
  if (!s.accessToken) throw new Error('Not connected to Strava.');

  const bufferSeconds = 5 * 60;
  const nowSeconds = Math.floor(Date.now() / 1000);
  if (s.expiresAt && s.expiresAt - nowSeconds > bufferSeconds) {
    return s.accessToken;
  }

  const { workerUrl } = getConfig();
  const res = await fetch(`${workerUrl}/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: s.refreshToken }),
  });
  if (!res.ok) throw new Error('Failed to refresh Strava token — try reconnecting in Settings.');
  const data = await res.json();
  save({
    accessToken: data.access_token,
    refreshToken: data.refresh_token || s.refreshToken,
    expiresAt: data.expires_at,
  });
  return data.access_token;
}

async function apiGet(path, params = {}) {
  const { workerUrl } = getConfig();
  const token = await ensureFreshToken();
  const query = new URLSearchParams(params).toString();
  const url = `${workerUrl}/api${path}${query ? `?${query}` : ''}`;
  const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  if (!res.ok) throw new Error(`Strava API error (${res.status}) on ${path}`);
  return res.json();
}

export async function fetchAthlete() {
  const athlete = await apiGet('/athlete');
  save({ athlete });
  return athlete;
}

/**
 * Fetch running activities from the last `weeks` weeks (default 12), newest
 * first, filtered to Run / TrailRun / VirtualRun.
 */
export async function fetchRecentRuns(weeks = 12) {
  const after = Math.floor(Date.now() / 1000) - weeks * 7 * 24 * 3600;
  const perPage = 100;
  let page = 1;
  let all = [];

  while (page <= 5) {
    const batch = await apiGet('/athlete/activities', { after, per_page: perPage, page });
    all = all.concat(batch);
    if (batch.length < perPage) break;
    page += 1;
  }

  return all
    .filter((a) => ['Run', 'TrailRun', 'VirtualRun'].includes(a.sport_type || a.type))
    .sort((a, b) => new Date(b.start_date) - new Date(a.start_date));
}

/** Monday 00:00 (local time) of the week containing `date`. */
function weekStart(date) {
  const d = new Date(date);
  const day = (d.getDay() + 6) % 7; // 0 = Monday
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - day);
  return d;
}

/**
 * Bucket runs into ISO-week summaries: distance (km), moving time (min),
 * elevation gain (m), run count, average pace (min/km).
 */
export function summarizeByWeek(runs) {
  const weeks = new Map();

  for (const run of runs) {
    const key = weekStart(run.start_date_local || run.start_date).toISOString().slice(0, 10);
    if (!weeks.has(key)) {
      weeks.set(key, { weekStart: key, distanceKm: 0, movingMin: 0, elevationM: 0, runCount: 0 });
    }
    const w = weeks.get(key);
    w.distanceKm += (run.distance || 0) / 1000;
    w.movingMin += (run.moving_time || 0) / 60;
    w.elevationM += run.total_elevation_gain || 0;
    w.runCount += 1;
  }

  return [...weeks.values()]
    .map((w) => ({
      ...w,
      distanceKm: Math.round(w.distanceKm * 10) / 10,
      movingMin: Math.round(w.movingMin),
      avgPaceMinKm: w.distanceKm > 0 ? w.movingMin / w.distanceKm : null,
    }))
    .sort((a, b) => (a.weekStart < b.weekStart ? 1 : -1));
}

/**
 * Rough current-fitness estimate from recent runs: average weekly distance
 * (last `weeks` full weeks, excluding the current in-progress week),
 * longest single run, and an estimated threshold pace from the fastest
 * sustained effort (best pace over a run of at least 5km).
 */
export function estimateFitness(runs, weeks = 6) {
  const weekly = summarizeByWeek(runs).slice(1, weeks + 1); // skip current week in progress
  const avgWeeklyKm = weekly.length
    ? Math.round((weekly.reduce((s, w) => s + w.distanceKm, 0) / weekly.length) * 10) / 10
    : 0;

  const longRun = runs.reduce((max, r) => Math.max(max, (r.distance || 0) / 1000), 0);

  const qualifying = runs.filter((r) => (r.distance || 0) >= 5000 && r.moving_time);
  let bestPaceMinKm = null;
  for (const r of qualifying) {
    const pace = r.moving_time / 60 / (r.distance / 1000);
    if (bestPaceMinKm === null || pace < bestPaceMinKm) bestPaceMinKm = pace;
  }

  return {
    avgWeeklyKm,
    longestRunKm: Math.round(longRun * 10) / 10,
    thresholdPaceMinKm: bestPaceMinKm,
    weeksOfData: weekly.length,
  };
}
