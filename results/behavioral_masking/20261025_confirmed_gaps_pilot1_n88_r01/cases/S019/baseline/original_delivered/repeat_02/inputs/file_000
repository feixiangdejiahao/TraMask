import { z } from 'zod'

import { DynamoDBToolboxError } from '~/errors/index.js'
import { Entity, PutItemCommand, Table, UpdateItemCommand } from '~/index.js'
import { SchemaDTO } from '~/schema/actions/dto/index.js'
import { fromSchemaDTO } from '~/schema/actions/fromDTO/index.js'
import { JSONSchemer } from '~/schema/actions/jsonSchemer/index.js'
import { ZodSchemer } from '~/schema/actions/zodSchemer/index.js'
import { item, map, string } from '~/schema/index.js'

describe('requiredIf', () => {
  test('chains trigger values with OR semantics', () => {
    const attr = string().optional().requiredIf('type', 'a').requiredIf('type', 'b')

    expect(attr.props.requiredIf).toStrictEqual({ type: ['a', 'b'] })
  })

  test('check validates controlling attributes, self-references and key attributes', () => {
    expect(() =>
      item({ type: string(), details: string().optional().requiredIf('foo', 'a') }).check()
    ).toThrow(DynamoDBToolboxError)
    expect(() => item({ details: string().optional().requiredIf('details', 'a') }).check()).toThrow(
      DynamoDBToolboxError
    )
    expect(() =>
      item({
        pk: string().key(),
        type: string(),
        details: string().key().requiredIf('type', 'a')
      }).check()
    ).toThrow(DynamoDBToolboxError)
  })

  test('enforces requiredIf during put', () => {
    const schema = item({
      pk: string().key(),
      type: string().enum('a', 'b'),
      details: string().optional().requiredIf('type', 'a')
    })
    schema.check()

    const table = new Table({
      name: 'test',
      partitionKey: { type: 'string', name: 'pk' }
    })
    const entity = new Entity({ name: 'Test', schema, table, timestamps: false })

    expect(() => entity.build(PutItemCommand).item({ pk: 'x', type: 'a' }).params()).toThrow(
      DynamoDBToolboxError
    )

    expect(() => entity.build(PutItemCommand).item({ pk: 'x', type: 'b' }).params()).not.toThrow()

    expect(() =>
      entity.build(PutItemCommand).item({ pk: 'x', type: 'a', details: 'd' }).params()
    ).not.toThrow()
  })

  test('applied defaults satisfy requiredIf during put', () => {
    const schema = item({
      pk: string().key(),
      type: string().enum('a', 'b'),
      details: string().optional().putDefault('default').requiredIf('type', 'a')
    })
    schema.check()

    const table = new Table({
      name: 'test',
      partitionKey: { type: 'string', name: 'pk' }
    })
    const entity = new Entity({ name: 'Test', schema, table, timestamps: false })

    const res = entity.build(PutItemCommand).item({ pk: 'x', type: 'a' }).params()
    expect((res as { Item: Record<string, unknown> }).Item.details).toBe('default')
  })

  test('adds attribute_exists condition during update when dependent is missing', () => {
    const schema = item({
      pk: string().key(),
      profile: map({
        type: string().enum('x', 'y'),
        bio: string().optional().savedAs('b').requiredIf('type', 'x')
      }).savedAs('p')
    })
    schema.check()

    const table = new Table({
      name: 'test',
      partitionKey: { type: 'string', name: 'pk' }
    })
    const entity = new Entity({ name: 'Test', schema, table, timestamps: false })

    const missing = entity
      .build(UpdateItemCommand)
      .item({ pk: 'x', profile: { type: 'x' } })
      .params()
    expect(missing.ConditionExpression).toContain('attribute_exists(')
    expect(missing.ExpressionAttributeNames).toMatchObject({ '#r_1': 'p', '#r_2': 'b' })

    const present = entity
      .build(UpdateItemCommand)
      .item({ pk: 'x', profile: { type: 'x', bio: 'b' } })
      .params()
    expect(present.ConditionExpression).toBeUndefined()
  })

  test('DTO round-trips requiredIf', () => {
    const schema = item({
      pk: string().key(),
      type: string().enum('a', 'b'),
      details: string().optional().requiredIf('type', 'a')
    })
    schema.check()

    const dto = new SchemaDTO(schema).toJSON()
    const restored = fromSchemaDTO(dto)
    restored.check()

    expect((restored.attributes as any).details.props.requiredIf).toStrictEqual({
      type: ['a']
    })
  })

  test('JSON schema enforces conditional presence', () => {
    const schema = item({
      pk: string().key(),
      type: string().enum('a', 'b'),
      details: string().optional().requiredIf('type', 'a')
    })
    schema.check()

    const jsonSchema = new JSONSchemer(schema).formattedValueSchema()
    expect(JSON.stringify(jsonSchema)).toContain('"if"')
    expect(JSON.stringify(jsonSchema)).toContain('"then"')
  })

  test('zod parser and formatter enforce requiredIf', () => {
    const schema = item({
      pk: string().key(),
      type: string().enum('a', 'b'),
      details: string().optional().requiredIf('type', 'a')
    })
    schema.check()

    const zod = new ZodSchemer(schema)

    expect(() => zod.parser({ mode: 'put' }).parse({ pk: 'x', type: 'a' })).toThrow(z.ZodError)
    expect(() =>
      zod.parser({ mode: 'put' }).parse({ pk: 'x', type: 'a', details: 'd' })
    ).not.toThrow()
    expect(() => zod.formatter().parse({ pk: 'x', type: 'a' })).toThrow(z.ZodError)
    expect(() => zod.formatter().parse({ pk: 'x', type: 'a', details: 'd' })).not.toThrow()
  })
})
