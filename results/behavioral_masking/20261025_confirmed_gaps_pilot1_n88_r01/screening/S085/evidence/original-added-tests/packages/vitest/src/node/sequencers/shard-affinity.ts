import type { ShardAffinityRule } from '../../runtime/config'
import pm from 'picomatch'

export interface CompiledAffinityRule {
  pattern: string
  shardIndex: number
  matcher: (path: string) => boolean
}

/**
 * Compiles affinity rules into matchers. Invalid patterns are ignored.
 */
export function compileAffinityRules(rules: ShardAffinityRule[]): CompiledAffinityRule[] {
  const compiled: CompiledAffinityRule[] = []
  for (const rule of rules) {
    try {
      const matcher = pm(rule.pattern)
      compiled.push({
        pattern: rule.pattern,
        shardIndex: rule.shardIndex,
        matcher,
      })
    }
    catch {
      // invalid glob pattern, skip
    }
  }
  return compiled
}

/**
 * Returns the 0-based shard index for a file, clamped to `shardCount - 1`.
 * The first matching rule wins. Returns `undefined` when no rule matches.
 */
export function getAffinityShardIndex(
  path: string,
  rules: CompiledAffinityRule[],
  shardCount: number,
): number | undefined {
  for (const rule of rules) {
    if (rule.matcher(path)) {
      return Math.min(Math.max(rule.shardIndex, 0), shardCount - 1)
    }
  }
  return undefined
}
