import type { File } from '@vitest/runner'
import type { ResolvedConfig } from '../types/config'
import { existsSync } from 'node:fs'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { slash } from '@vitest/utils/helpers'
import { dirname, relative, resolve } from 'pathe'

export interface DurationObservation {
  duration: number
  recordedAt: number
}

export type DurationHistoryEntry
  = | DurationObservation
    | {
      observations: DurationObservation[]
    }
    | number

export type DurationHistory = Record<string, DurationHistoryEntry>

export function isDurationHistory(history: unknown): history is DurationHistory {
  return typeof history === 'object' && history !== null && !Array.isArray(history)
}

/**
 * Reads and normalizes the duration history file. Legacy numeric entries are
 * migrated to single-entry observations with `recordedAt: 0`.
 * Missing or corrupt files return `null`.
 */
export async function readDurationHistory(path: string): Promise<DurationHistory | null> {
  if (!existsSync(path)) {
    return null
  }

  let raw: string
  try {
    raw = await readFile(path, 'utf8')
  }
  catch {
    return null
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  }
  catch {
    return null
  }

  if (!isDurationHistory(parsed)) {
    return null
  }

  const normalized: DurationHistory = {}
  for (const [key, entry] of Object.entries(parsed)) {
    if (typeof entry === 'number') {
      normalized[key] = {
        duration: Math.round(entry),
        recordedAt: 0,
      }
    }
    else if (
      typeof entry === 'object'
      && entry !== null
      && typeof (entry as DurationObservation).duration === 'number'
      && typeof (entry as DurationObservation).recordedAt === 'number'
    ) {
      normalized[key] = {
        duration: Math.round((entry as DurationObservation).duration),
        recordedAt: (entry as DurationObservation).recordedAt,
      }
    }
    else if (
      typeof entry === 'object'
      && entry !== null
      && Array.isArray((entry as { observations?: unknown }).observations)
    ) {
      const observations = ((entry as { observations: unknown[] }).observations).filter((observation): observation is DurationObservation => (
        typeof observation === 'object'
        && observation !== null
        && typeof (observation as DurationObservation).duration === 'number'
        && typeof (observation as DurationObservation).recordedAt === 'number'
      )).map(observation => ({
        duration: Math.round(observation.duration),
        recordedAt: observation.recordedAt,
      }))
      normalized[key] = { observations }
    }
  }

  return normalized
}

/**
 * Returns all observations for a file, or an empty array when missing.
 */
export function getHistoryObservations(
  history: DurationHistory | null,
  path: string,
): DurationObservation[] {
  const entry = history?.[path]
  if (!entry) {
    return []
  }
  if (typeof entry === 'number') {
    return [{ duration: entry, recordedAt: 0 }]
  }
  if ('observations' in entry) {
    return entry.observations
  }
  return [entry]
}

/**
 * Writes duration observations to the history file. Parent directories are
 * created automatically and entries for other files are preserved.
 *
 * The number of observations written per file is capped to `maxRuns` (the N
 * most recent by `recordedAt`). When `maxRuns === 1`, a single-entry object is
 * written, otherwise a multi-entry object with `observations` is written.
 */
export async function writeDurationHistory(
  path: string,
  durations: Record<string, number>,
  maxRuns: number,
  ttl = 0,
): Promise<void> {
  const existing = await readDurationHistory(path)
  const now = Date.now()

  const merged: DurationHistory = { ...existing ?? {} }

  for (const [pathKey, duration] of Object.entries(durations)) {
    const observations = getHistoryObservations(existing, pathKey)
    observations.push({
      duration: Math.round(duration),
      recordedAt: now,
    })

    // drop expired observations, `recordedAt: 0` never expires
    const nonExpired = ttl > 0
      ? observations.filter(observation => observation.recordedAt === 0 || observation.recordedAt >= now - ttl)
      : observations

    // keep N most recent
    const capped = nonExpired
      .sort((a, b) => b.recordedAt - a.recordedAt)
      .slice(0, maxRuns)

    if (maxRuns <= 1) {
      merged[pathKey] = capped[0] ?? { duration: Math.round(duration), recordedAt: now }
    }
    else {
      merged[pathKey] = { observations: capped }
    }
  }

  await mkdir(dirname(path), { recursive: true })
  await writeFile(path, JSON.stringify(merged, null, 2), 'utf8')
}

export interface RecordFileDurationsOptions {
  config: ResolvedConfig
  files: File[]
}

/**
 * Records durations of finished test files into the duration history file.
 */
export async function recordFileDurations({ config, files }: RecordFileDurationsOptions): Promise<void> {
  const { sequence } = config
  if (!sequence.recordFileDurations) {
    return
  }

  const historyPath = resolve(config.root, sequence.durationHistoryPath)
  const durations: Record<string, number> = {}

  for (const file of files) {
    const duration = file.result?.duration
    if (typeof duration !== 'number' || !Number.isFinite(duration)) {
      continue
    }
    const relativePath = slash(relative(config.root, file.filepath))
    durations[relativePath] = Math.round(duration)
  }

  if (Object.keys(durations).length === 0) {
    return
  }

  try {
    await writeDurationHistory(
      historyPath,
      durations,
      sequence.durationHistoryMaxRuns,
      sequence.durationHistoryTTL,
    )
  }
  catch {}
}
