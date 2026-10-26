cd /app && git status --short && npx prettier --write \
  src/schema/types/schemaProps.ts src/schema/types/index.ts \
  src/schema/utils/checkSchemaProps.ts src/schema/utils/errors.ts src/schema/utils/checkRequiredIf.ts \
  src/schema/item/schema.ts src/schema/map/schema.ts \
  src/schema/actions/parse/errors.ts src/schema/actions/parse/utils.ts src/schema/actions/parse/item.ts src/schema/actions/parse/map.ts \
  src/schema/*/schema_.ts \
  src/schema/actions/dto/types.ts src/schema/actions/dto/getSchemaDTO/*.ts \
  src/schema/actions/fromDTO/fromSchemaDTO/anyOf.ts \
  src/schema/actions/jsonSchemer/formattedValue/item.ts src/schema/actions/jsonSchemer/formattedValue/map.ts src/schema/actions/jsonSchemer/formattedValue/shared.ts \
  src/schema/actions/zodSchemer/formatter/utils.ts src/schema/actions/zodSchemer/formatter/item.ts src/schema/actions/zodSchemer/formatter/map.ts \
  src/schema/actions/zodSchemer/parser/utils.ts src/schema/actions/zodSchemer/parser/item.ts src/schema/actions/zodSchemer/parser/map.ts \
  src/entity/actions/update/updateItemParams/updateItemParams.ts src/entity/actions/update/updateItemParams/requiredIfConditions.ts \
  2>&1 | tail -20