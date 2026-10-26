import type { DurationSmoothingStrategy } from '../../runtime/config'
import type { DurationHistory, DurationObservation } from './duration-history'
import { getHistoryObservations } from './duration-history'

/**
 * Smooths a list of duration observations into a single duration value.
 */
export function smoothObservations(
  observations: DurationObservation[],
  strategy: DurationSmoothingStrategy,
): number {
  if (observations.length === 0) {
    return 0
  }

  switch (strategy) {
    case 'latest': {
      return observations.reduce((latest: DurationObservation, observation: DurationObservation) => (
        observation.recordedAt > latest.recordedAt ? observation : latest
      ), observations[0]!).duration
    }
    case 'average': {
      const sum = observations.reduce((total: number, observation: DurationObservation) => total + observation.duration, 0)
      return Math.round(sum / observations.length)
    }
    case 'p95': {
      const sorted = observations
        .map(observation => observation.duration)
        .sort((a, b) => a - b)
      const index = Math.ceil(0.95 * sorted.length) - 1
      return sorted[index]
    }
    case 'median': {
      const sorted = observations
        .map(observation => observation.duration)
        .sort((a, b) => a - b)
      const middle = Math.floor(sorted.length / 2)
      if (sorted.length % 2 === 0) {
        return Math.floor((sorted[middle - 1] + sorted[middle]) / 2)
      }
      return sorted[middle]
    }
  }
}

/**
 * Builds a map of relative file paths to smoothed durations. Expired
 * observations (based on `ttl`) are excluded. Files missing from the history
 * are not present in the returned map and should be treated as duration 0.
 */
export function getSmoothedDurations(
  history: DurationHistory | null,
  strategy: DurationSmoothingStrategy,
  ttl: number,
  now: number = Date.now(),
): Map<string, number> {
  const durations = new Map<string, number>()
  if (!history) {
    return durations
  }

  for (const path of Object.keys(history)) {
    const observations = getHistoryObservations(history, path).filter((observation: DurationObservation) => {
      if (observation.recordedAt === 0) {
        return true
      }
      return ttl <= 0 || observation.recordedAt >= now - ttl
    })

    if (observations.length > 0) {
      durations.set(path, smoothObservations(observations, strategy))
    }
  }

  return durations
}
