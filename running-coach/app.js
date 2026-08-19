import * as strava from './strava.js';
import * as engine from './plan-engine.js';

const GOAL_KEY = 'rc_goal_v1';
const PLAN_KEY = 'rc_plan_v1';

const $app = document.getElementById('app');
const $topbar = document.getElementById('topbar-root');
const $toast = document.getElementById('toast-root');

const state = {
  route: 'loading',
  goal: loadJson(GOAL_KEY),
  plan: loadJson(PLAN_KEY),
  runs: null, // cached Strava runs for the session
  athlete: strava.getAthlete(),
  loading: false,
  error: null,
  checkinWeek: null,
  openWeek: null,
};

function loadJson(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}
function saveGoal(goal) { state.goal = goal; localStorage.setItem(GOAL_KEY, JSON.stringify(goal)); }
function savePlan(plan) { state.plan = plan; localStorage.setItem(PLAN_KEY, JSON.stringify(plan)); }

function toast(message, isError = false) {
  const div = document.createElement('div');
  div.className = `toast${isError ? ' error' : ''}`;
  div.textContent = message;
  $toast.appendChild(div);
  setTimeout(() => div.remove(), 4200);
}

// ── Formatting helpers ──────────────────────────────────────────────

function fmtKm(km) { return `${(km || 0).toFixed(1)} km`; }
function fmtDate(iso) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
}
function weekRangeLabel(startIso) {
  const start = new Date(`${startIso}T00:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 6);
  const fmt = (d) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  return `${fmt(start)} – ${fmt(end)}`;
}
function daysUntil(iso) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const target = new Date(`${iso}T00:00:00`);
  return Math.round((target - today) / 86400000);
}
function parseDuration(text) {
  if (!text || !text.trim()) return null;
  const parts = text.trim().split(':').map(Number);
  if (parts.some(Number.isNaN)) return null;
  if (parts.length === 3) return parts[0] * 60 + parts[1] + parts[2] / 60;
  if (parts.length === 2) return parts[0] + parts[1] / 60;
  return parts[0];
}
function tomorrowIso() {
  const d = new Date(); d.setDate(d.getDate() + 1);
  return d.toISOString().slice(0, 10);
}

// ── Topbar ───────────────────────────────────────────────────────────

function renderTopbar() {
  if (!state.plan) { $topbar.innerHTML = ''; return; }
  const athlete = state.athlete;
  $topbar.innerHTML = `
    <div class="topbar"><div class="topbar-inner">
      <div class="brand"><span class="brand-mark">🏃</span> Running Coach</div>
      <nav class="nav">
        <button class="nav-btn ${state.route === 'dashboard' ? 'active' : ''}" data-action="nav" data-route="dashboard">Dashboard</button>
        <button class="nav-btn ${state.route === 'plan' ? 'active' : ''}" data-action="nav" data-route="plan">Full Plan</button>
        <button class="nav-btn ${state.route === 'settings' ? 'active' : ''}" data-action="nav" data-route="settings">Settings</button>
      </nav>
      ${athlete ? `<div class="athlete-chip">
        ${athlete.profile ? `<img class="athlete-avatar" src="${athlete.profile}" alt="" />` : '<span class="athlete-avatar"></span>'}
        ${athlete.firstname || 'Athlete'}
      </div>` : ''}
    </div></div>`;
}

// ── Onboarding: Strava connect step ─────────────────────────────────

function viewOnboardingStrava() {
  const cfg = strava.getConfig();
  return `
    <div class="centered-page">
      <div class="step-indicator"><div class="step-dot active"></div><div class="step-dot"></div></div>
      <div class="page-header">
        <div class="page-title">Connect Strava</div>
        <div class="page-subtitle">Link your Strava account so your plan can adapt to your real training data. This is optional — you can skip and enter your mileage manually.</div>
      </div>
      <div class="card">
        <form id="strava-settings-form">
          <div class="field">
            <label for="clientId">Strava Client ID</label>
            <input type="text" id="clientId" value="${cfg.clientId}" placeholder="e.g. 123456" required />
            <div class="hint">From strava.com/settings/api</div>
          </div>
          <div class="field">
            <label for="workerUrl">Worker Base URL</label>
            <input type="url" id="workerUrl" value="${cfg.workerUrl}" placeholder="https://running-coach-strava-relay.you.workers.dev" required />
            <div class="hint">Your deployed Cloudflare Worker (see running-coach/worker/README.md)</div>
          </div>
          <div class="btn-row">
            <button type="submit" class="btn btn-primary">Save &amp; Connect to Strava</button>
            <button type="button" class="btn btn-secondary" data-action="skip-strava">Skip for now</button>
          </div>
        </form>
      </div>
    </div>`;
}

// ── Onboarding: race goal step ──────────────────────────────────────

function viewGoalForm(isEdit) {
  const g = state.goal || {};
  const races = engine.RACE_PRESETS;
  const connected = strava.isConnected();
  return `
    <div class="centered-page">
      ${isEdit ? '' : '<div class="step-indicator"><div class="step-dot done"></div><div class="step-dot active"></div></div>'}
      <div class="page-header">
        <div class="page-title">${isEdit ? 'Edit your race goal' : 'Set your race goal'}</div>
        <div class="page-subtitle">${isEdit ? 'This regenerates your full plan from today — past check-ins stay in your history.' : "We'll build a week-by-week plan and adjust it as you go."}</div>
      </div>
      <div class="card">
        <form id="goal-form">
          <div class="field">
            <label>Race distance</label>
            <div class="radio-group" data-group="raceType">
              ${Object.entries(races).map(([key, r]) => `<div class="radio-pill ${g.raceType === key || (!g.raceType && key === '10k') ? 'selected' : ''}" data-value="${key}">${r.label}</div>`).join('')}
              <div class="radio-pill ${g.raceType === 'custom' ? 'selected' : ''}" data-value="custom">Custom</div>
            </div>
          </div>
          <div class="field" id="customDistanceField" style="${g.raceType === 'custom' ? '' : 'display:none'}">
            <label for="customDistanceKm">Custom distance (km)</label>
            <input type="number" id="customDistanceKm" min="1" step="0.1" value="${g.customDistanceKm || ''}" />
          </div>
          <div class="grid-2">
            <div class="field">
              <label for="raceDate">Race date</label>
              <input type="date" id="raceDate" min="${tomorrowIso()}" value="${g.raceDate || ''}" required />
            </div>
            <div class="field">
              <label for="targetTime">Target time (optional)</label>
              <input type="text" id="targetTime" placeholder="1:45:00" value="${g.targetTimeText || ''}" />
              <div class="hint">h:mm:ss — used for pace targets if Strava has no recent race effort</div>
            </div>
          </div>
          <div class="grid-2">
            <div class="field">
              <label for="daysPerWeek">Training days / week</label>
              <select id="daysPerWeek">
                ${[3, 4, 5, 6].map((n) => `<option value="${n}" ${Number(g.daysPerWeek) === n ? 'selected' : ''}>${n} days</option>`).join('')}
              </select>
            </div>
            <div class="field">
              <label for="longRunDay">Long run day</label>
              <select id="longRunDay">
                ${['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d) => `<option value="${d}" ${(g.longRunDay || 'Sun') === d ? 'selected' : ''}>${d}</option>`).join('')}
              </select>
            </div>
          </div>
          <div class="field">
            <label>Experience level</label>
            <div class="radio-group" data-group="experience">
              ${['beginner', 'intermediate', 'advanced'].map((e) => `<div class="radio-pill ${(g.experience || 'intermediate') === e ? 'selected' : ''}" data-value="${e}">${e[0].toUpperCase() + e.slice(1)}</div>`).join('')}
            </div>
          </div>
          <div class="field">
            <label for="startingWeeklyKm">Current weekly mileage (km)${connected ? ' — auto-filled from Strava, override if needed' : ''}</label>
            <input type="number" id="startingWeeklyKm" min="0" step="0.5" value="${g.startingWeeklyKm || ''}" placeholder="e.g. 20" />
          </div>
          <div class="btn-row">
            <button type="submit" class="btn btn-primary" id="goal-submit-btn">${state.loading ? '<span class="spinner"></span> Building your plan…' : 'Generate my plan'}</button>
            ${isEdit ? '<button type="button" class="btn btn-secondary" data-action="nav" data-route="settings">Cancel</button>' : ''}
          </div>
        </form>
      </div>
    </div>`;
}

// ── Dashboard ────────────────────────────────────────────────────────

function computeActualKm(week) {
  if (!state.runs) return null;
  const summary = strava.summarizeByWeek(state.runs).find((w) => w.weekStart === week.startDate);
  return summary ? summary.distanceKm : 0;
}

function workoutDotClass(type) { return `workout-dot ${type}`; }

function renderWorkoutRow(w) {
  return `
    <div class="workout">
      <div class="workout-day">${w.day}</div>
      <div class="${workoutDotClass(w.type)}"></div>
      <div class="workout-body">
        <div class="workout-name">${w.name}</div>
        <div class="workout-desc">${w.description}</div>
      </div>
      <div class="workout-dist">${w.distanceKm > 0 ? fmtKm(w.distanceKm) : '—'}</div>
    </div>`;
}

function viewDashboard() {
  const plan = state.plan;
  const idx = engine.getCurrentWeekIndex(plan);
  const week = plan.weeks[idx];
  const actualKm = computeActualKm(week);
  const pct = week.targetDistanceKm > 0 ? Math.min(140, Math.round(((actualKm || 0) / week.targetDistanceKm) * 100)) : 0;
  const days = daysUntil(plan.raceDate);
  const hasCheckin = Boolean(week.checkin);
  const adjustment = week.adjustment;

  const activities = (state.runs || []).slice(0, 6);

  return `
    <div class="hero">
      <div>
        <div class="hero-label">Upcoming race</div>
        <div class="hero-race">${plan.raceLabel} — ${fmtDate(plan.raceDate)}</div>
      </div>
      <div class="hero-count">
        <div class="hero-count-num">${days >= 0 ? days : 0}</div>
        <div class="hero-count-unit">days to go</div>
      </div>
    </div>

    ${adjustment ? `<div class="checkin-banner">🏃 Coach note: ${adjustment}</div>` : ''}

    <div class="card">
      <div class="card-title">
        <span>This week · ${weekRangeLabel(week.startDate)} <span class="badge ${week.phase}">${week.phase}</span></span>
        ${state.runs ? `<button class="icon-btn" data-action="refresh-strava">Refresh</button>` : ''}
      </div>
      <div class="stat-row" style="margin-bottom:14px;">
        <div class="stat"><div class="stat-value">${fmtKm(week.targetDistanceKm)}</div><div class="stat-label">Planned</div></div>
        <div class="stat"><div class="stat-value">${actualKm != null ? fmtKm(actualKm) : '—'}</div><div class="stat-label">Actual (Strava)</div></div>
        <div class="stat"><div class="stat-value">${actualKm != null ? `${pct}%` : '—'}</div><div class="stat-label">Compliance</div></div>
      </div>
      ${actualKm != null ? `<div class="progress-track"><div class="progress-fill ${pct >= 100 ? 'over' : ''}" style="width:${Math.min(100, pct)}%"></div></div>` : ''}
      <div class="divider"></div>
      ${week.workouts.map(renderWorkoutRow).join('')}
      <div class="btn-row">
        <button class="btn btn-primary" data-action="open-checkin" data-week="${idx}">${hasCheckin ? 'Update this week’s check-in' : 'Log this week’s check-in'}</button>
      </div>
    </div>

    <div class="card">
      <div class="card-title">Recent activity</div>
      ${!strava.isConnected() ? `<p class="muted">Connect Strava in Settings to see your recent runs here.</p>` : ''}
      ${strava.isConnected() && activities.length === 0 ? `<p class="muted">No recent runs found yet.</p>` : ''}
      ${activities.map((a) => `
        <div class="activity">
          <div>
            <div class="activity-name">${a.name || 'Run'}</div>
            <div class="activity-meta">${new Date(a.start_date_local || a.start_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} · ${((a.distance || 0) / 1000).toFixed(1)} km · ${Math.round((a.moving_time || 0) / 60)} min</div>
          </div>
        </div>`).join('')}
    </div>`;
}

// ── Full plan view ──────────────────────────────────────────────────

function viewPlan() {
  const plan = state.plan;
  const currentIdx = engine.getCurrentWeekIndex(plan);
  return `
    <div class="page-header">
      <div class="page-title">Full Plan</div>
      <div class="page-subtitle">${plan.raceLabel} on ${fmtDate(plan.raceDate)} · ${plan.weeks.length} weeks · peak ~${fmtKm(plan.peakWeeklyKm)}/week</div>
    </div>
    <div class="card">
      ${plan.weeks.map((w, i) => `
        <div>
          <div class="week-accordion-header" data-action="toggle-week" data-week="${i}">
            <div class="week-meta">
              <span class="badge ${w.phase}">${w.phase}</span>
              <span class="week-title">Week ${i + 1} · ${weekRangeLabel(w.startDate)} ${i === currentIdx ? '· <em>current</em>' : ''}</span>
            </div>
            <span class="muted">${fmtKm(w.targetDistanceKm)} ${state.openWeek === i ? '▲' : '▼'}</span>
          </div>
          ${state.openWeek === i ? `<div style="padding: 0 4px 12px;">${w.workouts.map(renderWorkoutRow).join('')}${w.checkin ? `<div class="checkin-banner">Check-in: RPE ${w.checkin.rpe}/10, soreness ${w.checkin.soreness}/5, motivation ${w.checkin.motivation}/5${w.checkin.notes ? ` — “${w.checkin.notes}”` : ''}</div>` : ''}</div>` : ''}
          <div class="divider"></div>
        </div>`).join('')}
    </div>`;
}

// ── Check-in view ───────────────────────────────────────────────────

function viewCheckin() {
  const idx = state.checkinWeek;
  const week = state.plan.weeks[idx];
  const actualKm = computeActualKm(week);
  const existing = week.checkin || { rpe: 5, soreness: 2, motivation: 3, notes: '' };
  return `
    <div class="centered-page">
      <div class="page-header">
        <div class="page-title">Week ${idx + 1} check-in</div>
        <div class="page-subtitle">${weekRangeLabel(week.startDate)} — how did this week feel? Your answer shapes next week's plan.</div>
      </div>
      <div class="card">
        <form id="checkin-form">
          <div class="field">
            <label>Overall effort (RPE) — <span id="rpeVal">${existing.rpe}</span>/10</label>
            <div class="slider-row"><input type="range" id="rpe" min="1" max="10" value="${existing.rpe}" data-live="rpeVal" /></div>
          </div>
          <div class="field">
            <label>Soreness — <span id="sorenessVal">${existing.soreness}</span>/5</label>
            <div class="slider-row"><input type="range" id="soreness" min="1" max="5" value="${existing.soreness}" data-live="sorenessVal" /></div>
          </div>
          <div class="field">
            <label>Motivation — <span id="motivationVal">${existing.motivation}</span>/5</label>
            <div class="slider-row"><input type="range" id="motivation" min="1" max="5" value="${existing.motivation}" data-live="motivationVal" /></div>
          </div>
          <div class="field">
            <label for="notes">Notes (optional)</label>
            <textarea id="notes" placeholder="Tight calf on Tuesday's run, felt strong on the long run...">${existing.notes || ''}</textarea>
          </div>
          <div class="field">
            <label for="actualKm">Distance actually run this week (km)</label>
            <input type="number" id="actualKm" min="0" step="0.1" value="${actualKm != null ? actualKm : (existing.actualKm ?? '')}" ${state.runs ? 'readonly' : ''} />
            <div class="hint">${state.runs ? 'Pulled automatically from Strava.' : 'Connect Strava in Settings to fill this in automatically.'}</div>
          </div>
          <div class="btn-row">
            <button type="submit" class="btn btn-primary">Submit check-in</button>
            <button type="button" class="btn btn-secondary" data-action="nav" data-route="dashboard">Cancel</button>
          </div>
        </form>
      </div>
    </div>`;
}

// ── Settings view ───────────────────────────────────────────────────

function viewSettings() {
  const cfg = strava.getConfig();
  const connected = strava.isConnected();
  return `
    <div class="page-header">
      <div class="page-title">Settings</div>
    </div>

    <div class="card">
      <div class="card-title">Strava connection</div>
      <form id="strava-settings-form">
        <div class="field">
          <label for="clientId">Strava Client ID</label>
          <input type="text" id="clientId" value="${cfg.clientId}" required />
        </div>
        <div class="field">
          <label for="workerUrl">Worker Base URL</label>
          <input type="url" id="workerUrl" value="${cfg.workerUrl}" required />
        </div>
        <div class="btn-row">
          <button type="submit" class="btn btn-primary">Save</button>
          ${connected
            ? '<button type="button" class="btn btn-danger" data-action="disconnect-strava">Disconnect</button>'
            : '<button type="submit" class="btn btn-secondary" formnovalidate data-action="connect-after-save">Save &amp; Connect</button>'}
        </div>
      </form>
      ${connected ? `<p class="muted" style="margin-top:10px;">Connected as ${state.athlete ? `${state.athlete.firstname} ${state.athlete.lastname || ''}` : 'Strava athlete'}.</p>` : ''}
    </div>

    <div class="card">
      <div class="card-title">Race goal</div>
      <p class="muted" style="margin-bottom:14px;">${state.plan ? `${state.plan.raceLabel} on ${fmtDate(state.plan.raceDate)}` : 'No goal set yet.'}</p>
      <button class="btn btn-secondary" data-action="nav" data-route="edit-goal">Edit race goal</button>
    </div>

    <div class="card">
      <div class="card-title">Data</div>
      <p class="muted" style="margin-bottom:14px;">Everything is stored locally in this browser — nothing is sent anywhere except Strava and your own Worker.</p>
      <button class="btn btn-danger" data-action="clear-data">Clear all data</button>
    </div>`;
}

// ── Router / render ──────────────────────────────────────────────────

function render() {
  renderTopbar();
  switch (state.route) {
    case 'onboarding-strava': $app.innerHTML = viewOnboardingStrava(); break;
    case 'onboarding-goal': $app.innerHTML = viewGoalForm(false); break;
    case 'edit-goal': $app.innerHTML = viewGoalForm(true); break;
    case 'dashboard': $app.innerHTML = viewDashboard(); break;
    case 'plan': $app.innerHTML = viewPlan(); break;
    case 'checkin': $app.innerHTML = viewCheckin(); break;
    case 'settings': $app.innerHTML = viewSettings(); break;
    default: $app.innerHTML = '<div class="page-header"><div class="page-title">Loading…</div></div>';
  }
}

function goto(route) { state.route = route; render(); }

// ── Data loading ─────────────────────────────────────────────────────

async function refreshStravaData(showToast) {
  if (!strava.isConnected()) return;
  try {
    state.runs = await strava.fetchRecentRuns(12);
    if (!state.athlete) state.athlete = await strava.fetchAthlete();
    if (showToast) toast('Strava data refreshed.');
  } catch (e) {
    if (showToast) toast(e.message, true);
  }
}

async function boot() {
  try {
    const handled = await strava.handleOAuthRedirect();
    if (handled) toast('Connected to Strava!');
  } catch (e) {
    toast(e.message, true);
  }

  if (strava.isConnected()) {
    await refreshStravaData(false);
    state.route = state.plan ? 'dashboard' : 'onboarding-goal';
  } else if (state.plan) {
    state.route = 'dashboard';
  } else if (strava.isConfigured()) {
    state.route = 'onboarding-goal';
  } else {
    state.route = 'onboarding-strava';
  }
  render();
}

// ── Actions ──────────────────────────────────────────────────────────

async function handleGoalSubmit(form) {
  const group = (name) => form.querySelector(`[data-group="${name}"] .selected`)?.dataset.value;
  const raceType = group('raceType') || '10k';
  const experience = group('experience') || 'intermediate';
  const customDistanceKm = Number(form.querySelector('#customDistanceKm')?.value) || null;
  const raceDate = form.querySelector('#raceDate').value;
  const targetTimeText = form.querySelector('#targetTime').value;
  const targetTimeMinutes = parseDuration(targetTimeText);
  const daysPerWeek = Number(form.querySelector('#daysPerWeek').value);
  const longRunDay = form.querySelector('#longRunDay').value;
  const startingWeeklyKm = Number(form.querySelector('#startingWeeklyKm').value) || null;

  if (!raceDate) { toast('Please pick a race date.', true); return; }

  const goal = { raceType, customDistanceKm, raceDate, targetTimeText, targetTimeMinutes, daysPerWeek, longRunDay, experience, startingWeeklyKm };
  saveGoal(goal);

  state.loading = true;
  render();

  let fitness = null;
  if (strava.isConnected()) {
    try {
      if (!state.runs) state.runs = await strava.fetchRecentRuns(12);
      fitness = strava.estimateFitness(state.runs);
    } catch (e) {
      toast(`Couldn't load Strava data (${e.message}) — using manual mileage instead.`, true);
    }
  }

  const plan = engine.generatePlan({
    raceType: goal.raceType,
    customDistanceKm: goal.customDistanceKm,
    raceDate: goal.raceDate,
    targetTimeMinutes: goal.targetTimeMinutes,
    daysPerWeek: goal.daysPerWeek,
    longRunDay: goal.longRunDay,
    experience: goal.experience,
    startingWeeklyKm: goal.startingWeeklyKm,
    fitness,
  });

  savePlan(plan);
  state.loading = false;
  toast('Your training plan is ready!');
  goto('dashboard');
}

async function handleStravaSettingsSubmit(form, thenConnect) {
  const clientId = form.querySelector('#clientId').value;
  const workerUrl = form.querySelector('#workerUrl').value;
  if (!clientId || !workerUrl) { toast('Both fields are required.', true); return; }
  strava.saveConfig({ clientId, workerUrl });
  toast('Strava settings saved.');
  if (thenConnect) {
    strava.connect();
  } else if (state.route === 'onboarding-strava') {
    goto('onboarding-goal');
  } else {
    render();
  }
}

function handleCheckinSubmit(form) {
  const idx = state.checkinWeek;
  const rpe = Number(form.querySelector('#rpe').value);
  const soreness = Number(form.querySelector('#soreness').value);
  const motivation = Number(form.querySelector('#motivation').value);
  const notes = form.querySelector('#notes').value;
  const actualKmField = form.querySelector('#actualKm').value;
  const actualKm = actualKmField !== '' ? Number(actualKmField) : null;

  engine.applyWeeklyCheckin(state.plan, idx, { rpe, soreness, motivation, notes, actualKm });
  savePlan(state.plan);
  toast('Check-in saved — next week has been adjusted.');
  goto('dashboard');
}

// ── Event delegation ─────────────────────────────────────────────────

document.addEventListener('click', async (e) => {
  const pill = e.target.closest('.radio-pill');
  if (pill) {
    pill.parentElement.querySelectorAll('.radio-pill').forEach((p) => p.classList.remove('selected'));
    pill.classList.add('selected');
    if (pill.parentElement.dataset.group === 'raceType') {
      const customField = document.getElementById('customDistanceField');
      if (customField) customField.style.display = pill.dataset.value === 'custom' ? '' : 'none';
    }
    return;
  }

  const target = e.target.closest('[data-action]');
  if (!target) return;
  const action = target.dataset.action;

  if (action === 'nav') { goto(target.dataset.route); return; }
  if (action === 'skip-strava') { goto('onboarding-goal'); return; }
  if (action === 'disconnect-strava') {
    strava.disconnect();
    state.athlete = null;
    state.runs = null;
    toast('Disconnected from Strava.');
    render();
    return;
  }
  if (action === 'refresh-strava') { await refreshStravaData(true); render(); return; }
  if (action === 'open-checkin') { state.checkinWeek = Number(target.dataset.week); goto('checkin'); return; }
  if (action === 'toggle-week') {
    const w = Number(target.dataset.week);
    state.openWeek = state.openWeek === w ? null : w;
    render();
    return;
  }
  if (action === 'clear-data') {
    if (confirm('This removes your race goal, plan, check-in history and Strava connection from this browser. Continue?')) {
      localStorage.clear();
      window.location.reload();
    }
    return;
  }
});

document.addEventListener('input', (e) => {
  if (e.target.dataset && e.target.dataset.live) {
    document.getElementById(e.target.dataset.live).textContent = e.target.value;
  }
});

document.addEventListener('submit', (e) => {
  e.preventDefault();
  if (e.target.id === 'goal-form') { handleGoalSubmit(e.target); return; }
  if (e.target.id === 'strava-settings-form') {
    const thenConnect = document.activeElement && document.activeElement.dataset.action === 'connect-after-save';
    handleStravaSettingsSubmit(e.target, thenConnect);
    return;
  }
  if (e.target.id === 'checkin-form') { handleCheckinSubmit(e.target); return; }
});

boot();
