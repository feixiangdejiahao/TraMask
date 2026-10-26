import type { TestUserConfig } from 'vitest/node'
import { existsSync, rmSync } from 'node:fs'
import { basename } from 'pathe'

import { expect, test } from 'vitest'
import * as testUtils from '../../test-utils'

function runVitest(config: TestUserConfig, root = './fixtures/duration-shard') {
  return testUtils.runVitest({ ...config, root })
}

function parsePaths(stdout: string) {
  return Array.from(new Set(stdout
    .split('\n')
    .filter(line => line && line.includes('.test.js'))
    .map(file => basename(file.trim().split(' ')[1]))
    .sort()))
}

const historyPath = 'duration-history.json'

test('time strategy balances shards by recorded duration', async () => {
  const { stdout: stdout1 } = await runVitest({
    shard: '1/2',
    sequence: { shardStrategy: 'time', durationHistoryPath: historyPath },
  })
  const { stdout: stdout2 } = await runVitest({
    shard: '2/2',
    sequence: { shardStrategy: 'time', durationHistoryPath: historyPath },
  })

  // durations: 1=400, 2=300, 3=200, 4=100
  // LPT: shard1 = [1, 4], shard2 = [2, 3]
  expect(parsePaths(stdout1)).toEqual(['1.test.js', '4.test.js'])
  expect(parsePaths(stdout2)).toEqual(['2.test.js', '3.test.js'])
})

test('round-robin strategy assigns files with a bouncing pointer', async () => {
  const { stdout: stdout1 } = await runVitest({
    shard: '1/3',
    sequence: { shardStrategy: 'round-robin', durationHistoryPath: historyPath },
  })
  const { stdout: stdout2 } = await runVitest({
    shard: '2/3',
    sequence: { shardStrategy: 'round-robin', durationHistoryPath: historyPath },
  })
  const { stdout: stdout3 } = await runVitest({
    shard: '3/3',
    sequence: { shardStrategy: 'round-robin', durationHistoryPath: historyPath },
  })

  // sorted by duration: 1, 2, 3, 4
  // pointer: 1->shard1, 2->shard2, 3->shard3, 4->shard3
  expect(parsePaths(stdout1)).toEqual(['1.test.js'])
  expect(parsePaths(stdout2)).toEqual(['2.test.js'])
  expect(parsePaths(stdout3)).toEqual(['3.test.js', '4.test.js'])
})

test('durationFallbackStrategy equal-split is used when history is missing', async () => {
  const { stdout: stdout1 } = await runVitest({
    shard: '1/2',
    sequence: {
      shardStrategy: 'time',
      durationFallbackStrategy: 'equal-split',
      durationHistoryPath: 'missing-history.json',
    },
  })
  const { stdout: stdout2 } = await runVitest({
    shard: '2/2',
    sequence: {
      shardStrategy: 'time',
      durationFallbackStrategy: 'equal-split',
      durationHistoryPath: 'missing-history.json',
    },
  })

  // sorted by path: 1, 2, 3, 4 -> shard1 = [1, 3], shard2 = [2, 4]
  expect(parsePaths(stdout1)).toEqual(['1.test.js', '3.test.js'])
  expect(parsePaths(stdout2)).toEqual(['2.test.js', '4.test.js'])
})

test('affinity rules pin files to shards and unmatched files use LPT', async () => {
  const { stdout: stdout1 } = await runVitest({
    shard: '1/2',
    sequence: {
      shardStrategy: 'affinity',
      durationHistoryPath: historyPath,
      shardAffinityRules: [
        { pattern: 'test/1.test.js', shardIndex: 1 },
        { pattern: 'test/2.test.js', shardIndex: 0 },
      ],
    },
  })
  const { stdout: stdout2 } = await runVitest({
    shard: '2/2',
    sequence: {
      shardStrategy: 'affinity',
      durationHistoryPath: historyPath,
      shardAffinityRules: [
        { pattern: 'test/1.test.js', shardIndex: 1 },
        { pattern: 'test/2.test.js', shardIndex: 0 },
      ],
    },
  })

  // 1 -> shard2, 2 -> shard1, unmatched (3, 4) via LPT with affinity loads
  // 3 -> shard1 (300), 4 -> shard2 (400), so shard1 = [2, 3], shard2 = [1, 4]
  expect(parsePaths(stdout1)).toEqual(['2.test.js', '3.test.js'])
  expect(parsePaths(stdout2)).toEqual(['1.test.js', '4.test.js'])
})

test('isolateSlowThreshold isolates slow files across shards', async () => {
  const { stdout: stdout1 } = await runVitest({
    shard: '1/2',
    sequence: {
      shardStrategy: 'time',
      isolateSlowThreshold: 350,
      durationHistoryPath: historyPath,
    },
  })
  const { stdout: stdout2 } = await runVitest({
    shard: '2/2',
    sequence: {
      shardStrategy: 'time',
      isolateSlowThreshold: 350,
      durationHistoryPath: historyPath,
    },
  })

  // slow files (1, 2, 3) >= shard count: shard1 gets slowest, last shard gets extras + remaining
  expect(parsePaths(stdout1)).toEqual(['1.test.js'])
  expect(parsePaths(stdout2)).toEqual(['2.test.js', '3.test.js', '4.test.js'])
})

test('rebalanceThreshold warns when shard loads are unbalanced', async () => {
  const { stderr } = await runVitest({
    shard: '1/2',
    sequence: {
      shardStrategy: 'time',
      isolateSlowThreshold: 150,
      rebalanceThreshold: 0.9,
      durationHistoryPath: historyPath,
    },
  })

  expect(stderr).toContain('ratio=0.67')
  expect(stderr).toContain('threshold=0.90')
})

test('invalid sequence config throws at startup', async () => {
  const invalid = await runVitest({
    shard: '1/2',
    sequence: { shardStrategy: 'bogus' as any, durationHistoryPath: historyPath },
  })
  expect(invalid.thrown).toBe(true)
  expect(invalid.stderr).toContain('Invalid "sequence.shardStrategy" config')

  const invalidTtl = await runVitest({
    shard: '1/2',
    sequence: { durationHistoryTTL: -1, durationHistoryPath: historyPath },
  })
  expect(invalidTtl.thrown).toBe(true)
  expect(invalidTtl.stderr).toContain('Invalid "sequence.durationHistoryTTL" config')
})

test('recordFileDurations writes a duration history file', async () => {
  const historyFileAbsolute = new URL(`../fixtures/duration-record/tmp-history.json`, import.meta.url)
  rmSync(historyFileAbsolute, { force: true })

  const { thrown } = await testUtils.runVitest({
    root: './fixtures/duration-record',
    sequence: {
      recordFileDurations: true,
      durationHistoryPath: 'tmp-history.json',
      durationHistoryMaxRuns: 2,
    },
  })

  expect(thrown).toBe(false)
  expect(existsSync(historyFileAbsolute)).toBe(true)
  const history = JSON.parse(await import('node:fs/promises').then(fs => fs.readFile(historyFileAbsolute, 'utf8')))
  expect(Object.keys(history)).toEqual(expect.arrayContaining(['test/1.test.js', 'test/2.test.js']))
  const entry = history['test/1.test.js']
  const observations = Array.isArray(entry?.observations) ? entry.observations : [entry]
  expect(observations.length).toBeGreaterThan(0)
  expect(typeof observations[0].duration).toBe('number')
  expect(typeof observations[0].recordedAt).toBe('number')

  rmSync(historyFileAbsolute, { force: true })
})

test('balanceShardsByTime resolves to time when shardStrategy is unset', async () => {
  const { stdout } = await runVitest({
    shard: '1/2',
    sequence: { balanceShardsByTime: true, durationHistoryPath: historyPath },
  })

  // resolved to "time": shard1 = [1, 4]
  expect(parsePaths(stdout)).toEqual(['1.test.js', '4.test.js'])
})

test('affinity falls back to time when no rule matches any file', async () => {
  const { stdout } = await runVitest({
    shard: '1/2',
    sequence: {
      shardStrategy: 'affinity',
      durationHistoryPath: historyPath,
      shardAffinityRules: [{ pattern: 'does-not-match/**', shardIndex: 0 }],
    },
  })

  // no matches -> time strategy: shard1 = [1, 4]
  expect(parsePaths(stdout)).toEqual(['1.test.js', '4.test.js'])
})

test('durationBasedSorting runs files by duration descending', async () => {
  const { stdout } = await runVitest({
    sequence: {
      durationBasedSorting: true,
      durationHistoryPath: historyPath,
    },
    fileParallelism: false,
  })
  const paths = stdout
    .split('\n')
    .filter(line => line && line.includes('.test.js'))
    .map(file => basename(file.trim().split(' ')[1]))

  // durations: 1=400, 2=300, 3=200, 4=100
  expect(paths).toEqual(['1.test.js', '2.test.js', '3.test.js', '4.test.js'])
})
