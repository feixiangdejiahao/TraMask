import type { DurationFallbackStrategy, ShardStrategy } from '../../runtime/config'
import type { TestSpecification } from '../test-specification'
import type { CompiledAffinityRule } from './shard-affinity'
import { slash } from '@vitest/utils/helpers'
import { relative, resolve } from 'pathe'
import { hash } from '../hash'
import { getAffinityShardIndex } from './shard-affinity'

export interface ShardOptions {
  root: string
  hasHistory: boolean
  strategy: ShardStrategy
  fallbackStrategy: DurationFallbackStrategy
  affinityRules: CompiledAffinityRule[]
  isolateSlowThreshold: number
  durations: Map<string, number>
}

export function getFileRelativePath(root: string, moduleId: string): string {
  return slash(relative(root, moduleId))
}

export function getFileDuration(path: string, durations: Map<string, number>): number {
  return durations.get(path) ?? 0
}

export function shardHash(
  files: TestSpecification[],
  root: string,
  shardCount: number,
): TestSpecification[][] {
  const sorted = [...files]
    .map((spec) => {
      const fullPath = resolve(slash(root), slash(spec.moduleId))
      const specPath = fullPath?.slice(root.length)
      return {
        spec,
        hash: hash('sha1', specPath, 'hex'),
      }
    })
    .sort((a, b) => (a.hash < b.hash ? -1 : a.hash > b.hash ? 1 : 0))
    .map(({ spec }) => spec)

  const shards: TestSpecification[][] = Array.from({ length: shardCount }, () => [])
  for (let index = 1; index <= shardCount; index++) {
    const [start, end] = calculateShardRange(sorted.length, index, shardCount)
    shards[index - 1] = sorted.slice(start, end)
  }
  return shards
}

function calculateShardRange(filesCount: number, index: number, count: number): [number, number] {
  const baseShardSize = Math.floor(filesCount / count)
  const remainderTestFilesCount = filesCount % count
  if (remainderTestFilesCount >= index) {
    const shardSize = baseShardSize + 1
    const shardStart = shardSize * (index - 1)
    const shardEnd = shardSize * index
    return [shardStart, shardEnd]
  }
  const shardStart = remainderTestFilesCount * (baseShardSize + 1) + (index - remainderTestFilesCount - 1) * baseShardSize
  const shardEnd = shardStart + baseShardSize
  return [shardStart, shardEnd]
}

export function shardEqualSplit(files: TestSpecification[], shardCount: number): TestSpecification[][] {
  const sorted = [...files].sort((a, b) => (a.moduleId < b.moduleId ? -1 : a.moduleId > b.moduleId ? 1 : 0))
  const shards: TestSpecification[][] = Array.from({ length: shardCount }, () => [])
  sorted.forEach((file, index) => {
    shards[index % shardCount].push(file)
  })
  return shards
}

export function shardTime(
  files: TestSpecification[],
  root: string,
  durations: Map<string, number>,
  shardCount: number,
): TestSpecification[][] {
  const sorted = [...files].sort((a, b) => {
    const durationDiff = getFileDuration(getFileRelativePath(root, b.moduleId), durations)
      - getFileDuration(getFileRelativePath(root, a.moduleId), durations)
    return durationDiff || (a.moduleId < b.moduleId ? -1 : a.moduleId > b.moduleId ? 1 : 0)
  })

  const loads = Array.from({ length: shardCount }, () => 0)
  const shards: TestSpecification[][] = Array.from({ length: shardCount }, () => [])

  for (const file of sorted) {
    let minIndex = 0
    for (let i = 1; i < shardCount; i++) {
      if (loads[i] < loads[minIndex]) {
        minIndex = i
      }
    }
    shards[minIndex].push(file)
    loads[minIndex] += getFileDuration(getFileRelativePath(root, file.moduleId), durations)
  }

  return shards
}

export function shardRoundRobin(
  files: TestSpecification[],
  root: string,
  durations: Map<string, number>,
  shardCount: number,
): TestSpecification[][] {
  const sorted = [...files].sort((a, b) => {
    const durationDiff = getFileDuration(getFileRelativePath(root, b.moduleId), durations)
      - getFileDuration(getFileRelativePath(root, a.moduleId), durations)
    if (durationDiff !== 0) {
      return durationDiff
    }
    return a.moduleId < b.moduleId ? -1 : a.moduleId > b.moduleId ? 1 : 0
  })

  const shards: TestSpecification[][] = Array.from({ length: shardCount }, () => [])
  let pointer = 0
  let direction = 1

  for (const file of sorted) {
    shards[pointer].push(file)

    pointer += direction
    if (pointer < 0) {
      pointer = 0
      direction = 1
    }
    else if (pointer >= shardCount) {
      pointer = shardCount - 1
      direction = -1
    }
  }

  return shards
}

export function shardAffinity(
  files: TestSpecification[],
  root: string,
  durations: Map<string, number>,
  shardCount: number,
  rules: CompiledAffinityRule[],
): TestSpecification[][] {
  const shards: TestSpecification[][] = Array.from({ length: shardCount }, () => [])
  const loads = Array.from({ length: shardCount }, () => 0)
  let matchedAny = false

  for (const file of files) {
    const path = getFileRelativePath(root, file.moduleId)
    const affinityIndex = getAffinityShardIndex(path, rules, shardCount)
    if (affinityIndex !== undefined) {
      shards[affinityIndex].push(file)
      loads[affinityIndex] += getFileDuration(path, durations)
      matchedAny = true
    }
    else {
      let minIndex = 0
      for (let i = 1; i < shardCount; i++) {
        if (loads[i] < loads[minIndex]) {
          minIndex = i
        }
      }
      shards[minIndex].push(file)
      loads[minIndex] += getFileDuration(path, durations)
    }
  }

  if (!matchedAny) {
    return shardTime(files, root, durations, shardCount)
  }

  return shards
}

export type EffectiveShardStrategy = ShardStrategy | 'equal-split'

export function shardByStrategy(
  files: TestSpecification[],
  strategy: EffectiveShardStrategy,
  root: string,
  durations: Map<string, number>,
  shardCount: number,
  affinityRules: CompiledAffinityRule[],
): TestSpecification[][] {
  switch (strategy) {
    case 'time':
      return shardTime(files, root, durations, shardCount)
    case 'round-robin':
      return shardRoundRobin(files, root, durations, shardCount)
    case 'affinity':
      return shardAffinity(files, root, durations, shardCount, affinityRules)
    case 'equal-split':
      return shardEqualSplit(files, shardCount)
    case 'hash':
      return shardHash(files, root, shardCount)
    default:
      return shardEqualSplit(files, shardCount)
  }
}

function isolateSlowFiles(
  assignment: TestSpecification[][],
  files: TestSpecification[],
  root: string,
  durations: Map<string, number>,
  threshold: number,
  shardCount: number,
  strategy: EffectiveShardStrategy,
  affinityRules: CompiledAffinityRule[],
): TestSpecification[][] {
  const slow = files
    .filter(file => getFileDuration(getFileRelativePath(root, file.moduleId), durations) > threshold)
    .sort((a, b) => {
      const durationDiff = getFileDuration(getFileRelativePath(root, b.moduleId), durations)
        - getFileDuration(getFileRelativePath(root, a.moduleId), durations)
      return durationDiff || (a.moduleId < b.moduleId ? -1 : a.moduleId > b.moduleId ? 1 : 0)
    })

  if (slow.length === 0) {
    return assignment
  }

  const slowSet = new Set(slow)
  const remaining = files.filter(file => !slowSet.has(file))
  const newAssignment: TestSpecification[][] = Array.from({ length: shardCount }, () => [])

  if (slow.length < shardCount) {
    slow.forEach((file, index) => {
      newAssignment[index].push(file)
    })
    const remainingAssignment = shardByStrategy(remaining, strategy, root, durations, shardCount, affinityRules)
    remainingAssignment.forEach((group, index) => {
      newAssignment[index].push(...group)
    })
  }
  else {
    for (let i = 0; i < shardCount - 1; i++) {
      newAssignment[i].push(slow[i])
    }
    newAssignment[shardCount - 1].push(...slow.slice(shardCount - 1))
    newAssignment[shardCount - 1].push(...remaining)
  }

  return newAssignment
}

/**
 * Shards files into `shardCount` groups using the configured strategy and
 * returns the complete assignment. `isolateSlowThreshold` is applied on top of
 * the selected strategy.
 */
export function shardFiles(
  files: TestSpecification[],
  shardCount: number,
  options: ShardOptions,
): TestSpecification[][] {
  const strategy: EffectiveShardStrategy = options.hasHistory
    ? options.strategy
    : (options.fallbackStrategy === 'equal-split' ? 'equal-split' : 'hash')

  let assignment = shardByStrategy(files, strategy, options.root, options.durations, shardCount, options.affinityRules)

  if (options.isolateSlowThreshold > 0) {
    assignment = isolateSlowFiles(
      assignment,
      files,
      options.root,
      options.durations,
      options.isolateSlowThreshold,
      shardCount,
      strategy,
      options.affinityRules,
    )
  }

  return assignment
}

export function computeShardLoads(
  assignment: TestSpecification[][],
  root: string,
  durations: Map<string, number>,
): number[] {
  return assignment.map(group => group.reduce(
    (total, file) => total + getFileDuration(getFileRelativePath(root, file.moduleId), durations),
    0,
  ))
}

export function shouldWarnRebalance(loads: number[], threshold: number): boolean {
  if (threshold <= 0 || loads.length === 0) {
    return false
  }
  const maxLoad = Math.max(...loads)
  const minLoad = Math.min(...loads)
  if (maxLoad <= 0) {
    return false
  }
  return (minLoad / maxLoad) < threshold
}
