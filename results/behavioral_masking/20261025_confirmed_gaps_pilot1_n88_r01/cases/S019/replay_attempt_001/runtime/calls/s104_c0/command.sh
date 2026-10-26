cd /app && cat > src/entity/actions/update/updateItemParams/updateItemParams.ts <<'EOF'
import type { UpdateCommandInput } from '@aws-sdk/lib-dynamodb'

import { EntityParser } from '~/entity/actions/parse/index.js'
import type { Entity } from '~/entity/index.js'
import { isEmpty } from '~/utils/isEmpty.js'
import { omit } from '~/utils/omit.js'

import { expressUpdate } from '../expressUpdate/index.js'
import type { UpdateItemOptions } from '../options.js'
import type { UpdateItemInput } from '../types.js'
import { parseUpdateExtension } from './extension/index.js'
import { parseUpdateItemOptions } from './parseUpdateItemOptions.js'
import { getRequiredIfConditions } from './requiredIfConditions.js'

type UpdateItemParamsGetter = <ENTITY extends Entity, OPTIONS extends UpdateItemOptions<ENTITY>>(
  entity: ENTITY,
  input: UpdateItemInput<ENTITY>,
  updateItemOptions?: OPTIONS
) => UpdateCommandInput & { ToolboxItem: UpdateItemInput<ENTITY, { filled: true }> }

export const updateItemParams: UpdateItemParamsGetter = <
  ENTITY extends Entity,
  OPTIONS extends UpdateItemOptions<ENTITY>
>(
  entity: ENTITY,
  input: UpdateItemInput<ENTITY>,
  options: OPTIONS = {} as OPTIONS
) => {
  const { parsedItem, item, key } = entity.build(EntityParser).parse(input, {
    mode: 'update',
    parseExtension: parseUpdateExtension
  })

  const {
    ExpressionAttributeNames: updateExpressionAttributeNames,
    ExpressionAttributeValues: updateExpressionAttributeValues,
    ...update
  } = expressUpdate(entity, omit(item, ...Object.keys(key)))

  const {
    ExpressionAttributeNames: optionsExpressionAttributeNames,
    ExpressionAttributeValues: optionsExpressionAttributeValues,
    ...awsOptions
  } = parseUpdateItemOptions(entity, options)

  const requiredIfCondition = getRequiredIfConditions(entity.schema, parsedItem)

  const ExpressionAttributeNames = {
    ...optionsExpressionAttributeNames,
    ...updateExpressionAttributeNames,
    ...(requiredIfCondition?.ExpressionAttributeNames ?? {})
  }

  const ExpressionAttributeValues = {
    ...optionsExpressionAttributeValues,
    ...updateExpressionAttributeValues
  }

  const ConditionExpression = [
    requiredIfCondition?.ConditionExpression,
    awsOptions.ConditionExpression
  ]
    .filter((condition): condition is string => condition !== undefined)
    .map(condition => `(${condition})`)
    .join(' AND ')

  return {
    TableName: options.tableName ?? entity.table.getName(),
    /**
     * @debt type "TODO: Rework extensions & not cast here (use `ParsedItem<ENTITY, { extension: UpdateItemExtension }>`)"'
     */
    ToolboxItem: parsedItem as UpdateItemInput<ENTITY, { filled: true }>,
    Key: key,
    ...update,
    ...awsOptions,
    ...(ConditionExpression !== '' ? { ConditionExpression } : {}),
    ...(!isEmpty(ExpressionAttributeNames) ? { ExpressionAttributeNames } : {}),
    ...(!isEmpty(ExpressionAttributeValues) ? { ExpressionAttributeValues } : {})
  }
}
EOF
npx tsc --noEmit 2>&1 | head -40