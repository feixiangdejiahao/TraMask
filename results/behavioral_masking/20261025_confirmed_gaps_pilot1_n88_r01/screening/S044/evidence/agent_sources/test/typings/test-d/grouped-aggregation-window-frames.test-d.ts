import { expectError, expectType } from 'tsd'
import {
  type AggregateFunctionBuilder,
  type ExpressionWrapper,
  type Kysely,
  SimplifyFramePlugin,
  sql,
} from '..'
import type { Database } from '../shared'

async function testGroupedAggregation(db: Kysely<Database>) {
  expectType<string>(
    db
      .selectFrom('person')
      .select('first_name')
      .groupByCube('first_name', 'last_name')
      .compile().sql,
  )

  expectType<string>(
    db
      .selectFrom('person')
      .select('first_name')
      .groupByRollup(['first_name', 'last_name'])
      .compile().sql,
  )

  expectType<string>(
    db
      .selectFrom('person')
      .select('first_name')
      .groupByGroupingSets(['first_name'], ['first_name', 'last_name'])
      .compile().sql,
  )

  expectType<string>(
    db
      .selectFrom('person')
      .select('first_name')
      .groupBy('gender')
      .groupByRollup('marital_status')
      .compile().sql,
  )

  db.selectFrom('person').select((eb) => {
    expectType<ExpressionWrapper<Database, 'person', number>>(
      eb.fn.grouping('first_name'),
    )

    return eb.fn.grouping('first_name').as('grouping')
  })
}

async function testWindowFunctions(db: Kysely<Database>) {
  db.selectFrom('person').select((eb) => {
    expectType<AggregateFunctionBuilder<Database, 'person', number>>(
      eb.fn.rowNumber(),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', number>>(
      eb.fn.rank(),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', number>>(
      eb.fn.denseRank(),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', number>>(
      eb.fn.percentRank(),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', number>>(
      eb.fn.cumeDist(),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', number>>(
      eb.fn.ntile(4),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', number>>(
      eb.fn.ntile(4n),
    )

    expectType<AggregateFunctionBuilder<Database, 'person', string | null>>(
      eb.fn.firstValue<string | null>('last_name'),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', string | null>>(
      eb.fn.lastValue<string | null>('last_name'),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', string | null>>(
      eb.fn.nthValue<string | null>('last_name', 2),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', string | null>>(
      eb.fn.lag<string | null>('last_name', 1, 0),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', string | null>>(
      eb.fn.lead<string | null>('last_name', 1),
    )

    expectType<AggregateFunctionBuilder<Database, 'person', string | null>>(
      eb.fn.firstValue<string | null>('last_name').respectNulls(),
    )
    expectType<AggregateFunctionBuilder<Database, 'person', string | null>>(
      eb.fn.firstValue<string | null>('last_name').ignoreNulls(),
    )

    return eb.fn.rowNumber().as('row_number')
  })

  expectError(db.fn.ntile(sql.lit(1)))
  expectError(db.fn.lag<number>('age', sql.lit(1)))
}

async function testWindowFrames(db: Kysely<Database>) {
  db.selectFrom('person').select((eb) => {
    expectType<AggregateFunctionBuilder<Database, 'person', number>>(
      eb.fn.rowNumber().over((ob) =>
        ob
          .partitionBy('gender')
          .orderBy('age')
          .rows((fb) =>
            fb.betweenUnboundedPreceding().andCurrentRow().excludeTies(),
          ),
      ),
    )

    expectType<AggregateFunctionBuilder<Database, 'person', number>>(
      eb.fn
        .rowNumber()
        .over((ob) =>
          ob.range((fb) =>
            fb.betweenPreceding(1).andFollowing(2).excludeGroup(),
          ),
        ),
    )

    expectType<AggregateFunctionBuilder<Database, 'person', number>>(
      eb.fn
        .rowNumber()
        .over((ob) =>
          ob.groups((fb) => fb.unboundedPreceding().excludeNoOthers()),
        ),
    )

    expectError(
      eb.fn
        .rowNumber()
        .over((ob) => ob.rows((fb) => fb.betweenUnboundedPreceding())),
    )

    return eb.fn.rowNumber().as('row_number')
  })

  expectType<SimplifyFramePlugin>(new SimplifyFramePlugin())
}
