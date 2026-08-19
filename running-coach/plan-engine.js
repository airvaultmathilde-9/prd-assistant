/**
 * Rule-based training plan engine. No AI, no network calls — pure
 * periodization + load-management heuristics, adjusted week to week from
 * Strava compliance and the runner's self-reported feedback.
 *
 * A plan is a plain object:
 *   { raceType, raceDistanceKm, raceDate, daysPerWeek, longRunDay,
 *     experience, paceZones, generatedAt, weeks: [Week] }
 *
 * A Week is:
 *   { index, startDate, phase, targetDistanceKm, workouts: [Workout],
 *     checkin: null | { rpe, soreness, motivation, notes, actualKm, submittedAt },
 *     adjustment: null | string }   // human-readable note on why this week changed
 */

export const RACE_PRESETS = {
  '5k': { label: '5K', km: 5, maxLongRunKm: 12, taperWeeks: 1 },
  '10k': { label: '10K', km: 10, maxLongRunKm: 16, taperWeeks: 1 },
  half: { label: 'Half Marathon', km: 21.1, maxLongRunKm: 19, taperWeeks: 2 },
  marathon: { label: 'Marathon', km: 42.2, maxLongRunKm: 32, taperWeeks: 2 },
};

const EXPERIENCE_MULTIPLIER = { beginner: 0.75, intermediate: 1, advanced: 1.25 };
const PEAK_WEEKLY_KM_TABLE = { '5k': 35, '10k': 45, half: 55, marathon: 70 };

export function raceMeta(raceType, customDistanceKm) {
  if (raceType === 'custom') {
    const km = customDistanceKm || 10;
    return {
      label: `${km} km`,
      km,
      maxLongRunKm: Math.min(km * 1.3, km + 10),
      taperWeeks: km >= 30 ? 2 : 1,
    };
  }
  return RACE_PRESETS[raceType] || RACE_PRESETS['10k'];
}

function mondayOf(date) {
  const d = new Date(date);
  const day = (d.getDay() + 6) % 7;
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - day);
  return d;
}

function addDays(date, n) {
  const d = new Date(date);
  d.setDate(d.getDate() + n);
  return d;
}

function isoDate(d) {
  return d.toISOString().slice(0, 10);
}

function clamp(v, min, max) {
  return Math.max(min, Math.min(max, v));
}

/** Pace zones (min/km) derived from an estimated threshold pace. */
export function paceZonesFromThreshold(thresholdPaceMinKm) {
  if (!thresholdPaceMinKm) return null;
  return {
    easy: thresholdPaceMinKm * 1.25,
    long: thresholdPaceMinKm * 1.3,
    tempo: thresholdPaceMinKm * 1.04,
    threshold: thresholdPaceMinKm,
    interval: thresholdPaceMinKm * 0.92,
  };
}

/** If no Strava-derived threshold pace exists, estimate one from a goal race time. */
export function paceZonesFromGoalTime(raceType, customDistanceKm, targetTimeMinutes) {
  if (!targetTimeMinutes) return null;
  const { km } = raceMeta(raceType, customDistanceKm);
  const goalPaceMinKm = targetTimeMinutes / km;
  const raceToThresholdFactor = { '5k': 1.06, '10k': 1.03, half: 0.98, marathon: 0.93 };
  const factor = raceToThresholdFactor[raceType] || 1.0;
  return paceZonesFromThreshold(goalPaceMinKm * factor);
}

export function formatPace(minPerKm) {
  if (!minPerKm) return '—';
  const min = Math.floor(minPerKm);
  const sec = Math.round((minPerKm - min) * 60);
  return `${min}:${String(sec).padStart(2, '0')} /km`;
}

function recommendedPeakWeeklyKm(raceType, customDistanceKm, experience) {
  const base =
    raceType === 'custom'
      ? (customDistanceKm || 10) * 3.5
      : PEAK_WEEKLY_KM_TABLE[raceType] || PEAK_WEEKLY_KM_TABLE['10k'];
  return base * (EXPERIENCE_MULTIPLIER[experience] || 1);
}

/** Assign a training phase to every week between now and race day. */
function buildPhasePlan(totalWeeks, taperWeeks) {
  if (totalWeeks <= 4) {
    const taper = Math.min(taperWeeks, Math.max(1, totalWeeks - 2));
    const rest = totalWeeks - taper;
    return [...Array(rest).fill('build'), ...Array(taper).fill('taper')];
  }
  const peakWeeks = Math.max(1, Math.round(totalWeeks * 0.15));
  const remaining = totalWeeks - taperWeeks - peakWeeks;
  const buildWeeks = Math.max(1, Math.round(remaining * 0.5));
  const baseWeeks = Math.max(1, remaining - buildWeeks);
  return [
    ...Array(baseWeeks).fill('base'),
    ...Array(buildWeeks).fill('build'),
    ...Array(peakWeeks).fill('peak'),
    ...Array(taperWeeks).fill('taper'),
  ];
}

/** Weekly target distance ramp, with a lighter recovery week every 4th week. */
function buildVolumeRamp(phases, startWeeklyKm, peakWeeklyKm) {
  const rampEndIndex = phases.lastIndexOf('peak') >= 0 ? phases.lastIndexOf('peak') : phases.length - 1;
  const volumes = [];

  for (let i = 0; i < phases.length; i += 1) {
    const phase = phases[i];
    let target;

    if (phase === 'taper') {
      const taperWeeksLeft = phases.length - i;
      const totalTaper = phases.filter((p) => p === 'taper').length;
      const posInTaper = totalTaper - taperWeeksLeft + 1; // 1-indexed
      target = peakWeeklyKm * (posInTaper === totalTaper ? 0.4 : 0.7);
    } else {
      const progress = rampEndIndex === 0 ? 1 : i / rampEndIndex;
      target = startWeeklyKm + (peakWeeklyKm - startWeeklyKm) * Math.min(1, progress);
    }

    const isRecoveryWeek = phase !== 'taper' && (i + 1) % 4 === 0 && i !== rampEndIndex;
    if (isRecoveryWeek) target *= 0.8;

    volumes.push(Math.round(target * 10) / 10);
  }
  return volumes;
}

function intervalSession(phase, raceType) {
  const byPhase = {
    base: '6-8 x 400m @ 5K effort, 200m jog recovery',
    build: '5-6 x 1000m @ 10K effort, 2min jog recovery',
    peak:
      raceType === 'marathon' || raceType === 'half'
        ? '4 x 2km @ half-marathon effort, 3min jog recovery'
        : '5 x 1000m @ 5K race effort, 2min jog recovery',
    taper: '4 x 400m @ 5K effort, full recovery — keep it sharp, not tiring',
  };
  return byPhase[phase] || byPhase.base;
}

function buildWeekWorkouts({ weekIndex, phase, targetDistanceKm, daysPerWeek, longRunDay, raceType, maxLongRunKm, paceZones }) {
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  const workouts = [];

  const longRunKm = Math.min(
    maxLongRunKm,
    Math.round(targetDistanceKm * (phase === 'taper' ? 0.28 : 0.32) * 10) / 10
  );
  workouts.push({
    day: longRunDay,
    type: 'long',
    name: 'Long Run',
    distanceKm: longRunKm,
    paceMinKm: paceZones ? paceZones.long : null,
    description: paceZones
      ? `${longRunKm} km @ easy/long pace (${formatPace(paceZones.long)}). Keep it conversational.`
      : `${longRunKm} km at an easy, conversational effort.`,
  });

  let remainingKm = Math.max(0, targetDistanceKm - longRunKm);
  const otherDays = days.filter((d) => d !== longRunDay).slice(0, Math.max(0, daysPerWeek - 1));

  const hasTempo = daysPerWeek >= 4 && phase !== 'taper';
  const hasIntervals = daysPerWeek >= 5;

  let tempoKm = 0;
  if (hasTempo) {
    tempoKm = Math.round(targetDistanceKm * 0.18 * 10) / 10;
    remainingKm = Math.max(0, remainingKm - tempoKm);
  }
  let intervalKm = 0;
  if (hasIntervals) {
    intervalKm = Math.round(targetDistanceKm * 0.14 * 10) / 10;
    remainingKm = Math.max(0, remainingKm - intervalKm);
  }

  const easyDaysCount = Math.max(0, otherDays.length - (hasTempo ? 1 : 0) - (hasIntervals ? 1 : 0));
  const easyKmEach = easyDaysCount > 0 ? Math.round((remainingKm / easyDaysCount) * 10) / 10 : 0;

  let dayCursor = 0;
  if (hasIntervals) {
    workouts.push({
      day: otherDays[dayCursor],
      type: 'interval',
      name: 'Speed Intervals',
      distanceKm: intervalKm,
      paceMinKm: paceZones ? paceZones.interval : null,
      description: intervalSession(phase, raceType),
    });
    dayCursor += 1;
  }
  if (hasTempo) {
    workouts.push({
      day: otherDays[dayCursor],
      type: 'tempo',
      name: 'Tempo Run',
      distanceKm: tempoKm,
      paceMinKm: paceZones ? paceZones.tempo : null,
      description: paceZones
        ? `${tempoKm} km @ tempo pace (${formatPace(paceZones.tempo)}), controlled and steady.`
        : `${tempoKm} km at a "comfortably hard" tempo effort.`,
    });
    dayCursor += 1;
  }
  for (; dayCursor < otherDays.length; dayCursor += 1) {
    workouts.push({
      day: otherDays[dayCursor],
      type: 'easy',
      name: 'Easy Run',
      distanceKm: easyKmEach,
      paceMinKm: paceZones ? paceZones.easy : null,
      description: paceZones
        ? `${easyKmEach} km @ easy pace (${formatPace(paceZones.easy)}).`
        : `${easyKmEach} km at an easy, relaxed effort.`,
    });
  }

  const restDays = days.filter((d) => d !== longRunDay && !otherDays.includes(d));
  for (const d of restDays) {
    workouts.push({ day: d, type: 'rest', name: 'Rest / Cross-train', distanceKm: 0, paceMinKm: null, description: 'Full rest or light cross-training (bike, swim, mobility).' });
  }

  const order = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
  workouts.sort((a, b) => order[a.day] - order[b.day]);
  return workouts;
}

export function generatePlan({
  raceType,
  customDistanceKm,
  raceDate,
  targetTimeMinutes,
  daysPerWeek,
  longRunDay,
  experience,
  startingWeeklyKm,
  fitness,
}) {
  const meta = raceMeta(raceType, customDistanceKm);
  const today = mondayOf(new Date());
  const raceMonday = mondayOf(raceDate);
  const totalWeeks = Math.max(2, Math.round((raceMonday - today) / (7 * 24 * 3600 * 1000)) + 1);

  const currentWeeklyKm =
    (fitness && fitness.avgWeeklyKm > 0 ? fitness.avgWeeklyKm : null) ?? startingWeeklyKm ?? 15;
  const peakWeeklyKm = clamp(
    recommendedPeakWeeklyKm(raceType, customDistanceKm, experience),
    currentWeeklyKm * 1.1,
    currentWeeklyKm * 1.6
  );

  const phases = buildPhasePlan(totalWeeks, meta.taperWeeks);
  const volumes = buildVolumeRamp(phases, currentWeeklyKm, peakWeeklyKm);

  const paceZones =
    (fitness && paceZonesFromThreshold(fitness.thresholdPaceMinKm)) ||
    paceZonesFromGoalTime(raceType, customDistanceKm, targetTimeMinutes);

  const weeks = phases.map((phase, i) => {
    const startDate = isoDate(addDays(today, i * 7));
    const targetDistanceKm = volumes[i];
    return {
      index: i,
      startDate,
      phase,
      targetDistanceKm,
      workouts: buildWeekWorkouts({
        weekIndex: i,
        phase,
        targetDistanceKm,
        daysPerWeek,
        longRunDay,
        raceType,
        maxLongRunKm: meta.maxLongRunKm,
        paceZones,
      }),
      checkin: null,
      adjustment: null,
    };
  });

  return {
    raceType,
    raceLabel: meta.label,
    raceDistanceKm: meta.km,
    raceDate: isoDate(new Date(raceDate)),
    targetTimeMinutes: targetTimeMinutes || null,
    daysPerWeek,
    longRunDay,
    experience,
    paceZones,
    peakWeeklyKm: Math.round(peakWeeklyKm * 10) / 10,
    generatedAt: new Date().toISOString(),
    weeks,
  };
}

/** Index of the week whose startDate covers today, clamped to the plan's range. */
export function getCurrentWeekIndex(plan) {
  const today = mondayOf(new Date());
  const idx = plan.weeks.findIndex((w) => mondayOf(w.startDate).getTime() === today.getTime());
  if (idx >= 0) return idx;
  return today < mondayOf(plan.weeks[0].startDate) ? 0 : plan.weeks.length - 1;
}

/**
 * Record a check-in for `weekIndex` and adapt the following week's target
 * distance/workouts based on reported fatigue and how much of the plan was
 * actually completed (actualKm, typically pulled from Strava).
 */
export function applyWeeklyCheckin(plan, weekIndex, { rpe, soreness, motivation, notes, actualKm }) {
  const week = plan.weeks[weekIndex];
  if (!week) return plan;

  week.checkin = { rpe, soreness, motivation, notes: notes || '', actualKm: actualKm ?? null, submittedAt: new Date().toISOString() };

  const next = plan.weeks[weekIndex + 1];
  if (!next || next.phase === 'taper') return plan; // never override the taper/race week

  const fatigueScore = (rpe / 10) * 0.6 + (soreness / 5) * 0.4;
  const compliance = actualKm != null && week.targetDistanceKm > 0 ? actualKm / week.targetDistanceKm : 1;

  let factor = 1;
  let note = null;

  if (fatigueScore >= 0.75 || soreness >= 4) {
    factor = 0.82;
    note = 'Reduced next week’s volume — you reported high fatigue/soreness this week.';
  } else if (compliance < 0.6) {
    factor = Math.min(1, next.targetDistanceKm > 0 ? week.targetDistanceKm / next.targetDistanceKm : 1);
    note = 'Held next week steady instead of progressing — several sessions were missed this week.';
  } else if (fatigueScore <= 0.35 && compliance >= 0.95 && motivation >= 4) {
    factor = 1.05;
    note = 'Nudged next week’s volume up slightly — you’re recovering well and hitting your sessions.';
  }

  if (factor !== 1) {
    const cap = plan.peakWeeklyKm * 1.05;
    next.targetDistanceKm = Math.round(Math.min(cap, next.targetDistanceKm * factor) * 10) / 10;
    const meta = raceMeta(plan.raceType, plan.raceDistanceKm);
    next.workouts = buildWeekWorkouts({
      weekIndex: next.index,
      phase: next.phase,
      targetDistanceKm: next.targetDistanceKm,
      daysPerWeek: plan.daysPerWeek,
      longRunDay: plan.longRunDay,
      raceType: plan.raceType,
      maxLongRunKm: meta.maxLongRunKm,
      paceZones: plan.paceZones,
    });
    next.adjustment = note;
  } else {
    next.adjustment = null;
  }

  return plan;
}

/**
 * Re-estimate pace zones from the athlete's latest Strava runs and, if
 * fitness has genuinely improved (a faster sustained effort than what the
 * plan was built on), refresh the pace targets on every week that hasn't
 * started yet. Distances/phases are untouched — only the min/km targets and
 * their descriptions. Past weeks and their check-in history are never
 * rewritten. Returns true if the plan was updated.
 */
export function refreshPaceZones(plan, fitness) {
  if (!fitness || !fitness.thresholdPaceMinKm) return false;

  const newZones = paceZonesFromThreshold(fitness.thresholdPaceMinKm);
  const current = plan.paceZones;
  const improved = !current || fitness.thresholdPaceMinKm < current.threshold * 0.99;
  if (!improved) return false;

  plan.paceZones = newZones;
  const meta = raceMeta(plan.raceType, plan.raceDistanceKm);
  const currentIdx = getCurrentWeekIndex(plan);

  for (let i = currentIdx; i < plan.weeks.length; i += 1) {
    const week = plan.weeks[i];
    week.workouts = buildWeekWorkouts({
      weekIndex: week.index,
      phase: week.phase,
      targetDistanceKm: week.targetDistanceKm,
      daysPerWeek: plan.daysPerWeek,
      longRunDay: plan.longRunDay,
      raceType: plan.raceType,
      maxLongRunKm: meta.maxLongRunKm,
      paceZones: newZones,
    });
  }
  return true;
}
