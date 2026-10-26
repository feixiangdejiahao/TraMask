cd /app && git add -A && git commit -m "feat(schema): add requiredIf conditional requirements

Add a requiredIf(attributeName, ...triggerValues) builder to all schema
types used within map/item schemas. Attributes are declared required
when a named sibling matches any of the trigger values, with OR
semantics for chained calls.

- Enforce requiredIf during put parsing and throw a DynamoDBToolboxError
  when a matching trigger has an absent dependent
- During updates, add attribute_exists conditions for missing dependents
  when a controlling attribute is set to a trigger value, resolving full
  savedAs-aware paths
- Validate requiredIf in check(): controlling attributes must exist as
  siblings, self-references and key-attribute requirements are rejected
- Preserve requiredIf through DTO round-trips for all attribute types
  including anyOf
- Enforce conditional presence in JSON Schema export and in Zod
  formatter/parser schemas" && git log --oneline -3