import { attest, contextualize } from "@ark/attest"
import {
	jsonSchemaToType,
	writeInvalidRefFormatMessage,
	writeUnresolvableRefMessage
} from "@ark/json-schema"

contextualize(() => {
	it("enum deep equality", () => {
		const t = jsonSchemaToType({ enum: [1, 2, "a", { foo: 1 }, [1, 2]] })
		attest(t.allows(1)).equals(true)
		attest(t.allows(2)).equals(true)
		attest(t.allows("a")).equals(true)
		attest(t.allows({ foo: 1 })).equals(true)
		attest(t.allows({ foo: 2 })).equals(false)
		attest(t.allows([1, 2])).equals(true)
		attest(t.allows([2, 1])).equals(false)
	})

	it("const deep equality", () => {
		const t = jsonSchemaToType({ const: { foo: 1 } })
		attest(t.allows({ foo: 1 })).equals(true)
		attest(t.allows({ foo: 2 })).equals(false)
	})

	it("dependentRequired", () => {
		const t = jsonSchemaToType({
			type: "object",
			properties: {
				a: { type: "string" },
				b: { type: "string" }
			},
			dependentRequired: { a: ["b"] }
		})
		attest(t.allows({})).equals(true)
		attest(t.allows({ a: "x" })).equals(false)
		attest(t.allows({ a: "x", b: "y" })).equals(true)
	})

	it("dependentSchemas", () => {
		const t = jsonSchemaToType({
			type: "object",
			properties: { a: { type: "string" } },
			dependentSchemas: {
				a: {
					properties: { b: { type: "number" } },
					required: ["b"]
				}
			}
		})
		attest(t.allows({ a: "x" })).equals(false)
		attest(t.allows({ a: "x", b: 1 })).equals(true)
		attest(t.allows({ a: "x", b: "y" })).equals(false)
		attest(t.allows({})).equals(true)
	})

	it("dependencies", () => {
		const t = jsonSchemaToType({
			type: "object",
			properties: { a: { type: "string" } },
			dependencies: { a: ["b"] }
		})
		attest(t.allows({ a: "x" })).equals(false)
		attest(t.allows({ a: "x", b: 1 })).equals(true)

		const tSchema = jsonSchemaToType({
			type: "object",
			properties: { a: { type: "string" } },
			dependencies: {
				a: { required: ["b"], properties: { b: { type: "number" } } }
			}
		})
		attest(tSchema.allows({ a: "x" })).equals(false)
		attest(tSchema.allows({ a: "x", b: 1 })).equals(true)
		attest(tSchema.allows({ a: "x", b: "y" })).equals(false)
	})

	it("$ref simple", () => {
		const t = jsonSchemaToType({
			$defs: {
				user: {
					type: "object",
					properties: { name: { type: "string" } },
					required: ["name"]
				}
			},
			$ref: "#/$defs/user"
		})
		attest(t.expression).snap("{ name: string }")
		attest(t.allows({ name: "x" })).equals(true)
		attest(t.allows({})).equals(false)
	})

	it("$ref recursion", () => {
		const t = jsonSchemaToType({
			$defs: {
				tree: {
					type: "object",
					properties: {
						name: { type: "string" },
						child: { $ref: "#/$defs/tree" }
					},
					required: ["name"]
				}
			},
			$ref: "#/$defs/tree"
		})
		attest(t.allows({ name: "x" })).equals(true)
		attest(t.allows({ name: "x", child: { name: "y" } })).equals(true)
		attest(t.allows({ name: "x", child: { name: 1 } })).equals(false)
	})

	it("$ref recursion in anyOf", () => {
		const t = jsonSchemaToType({
			$defs: {
				node: {
					anyOf: [
						{ type: "string" },
						{
							type: "object",
							properties: { child: { $ref: "#/$defs/node" } }
						}
					]
				}
			},
			$ref: "#/$defs/node"
		})
		attest(t.allows("x")).equals(true)
		attest(t.allows({})).equals(true)
		attest(t.allows({ child: { child: "x" } })).equals(true)
		attest(t.allows({ child: 1 })).equals(false)
	})

	it("$ref in dependentSchemas", () => {
		const t = jsonSchemaToType({
			$defs: {
				name: {
					type: "object",
					properties: { n: { type: "string" } },
					required: ["n"]
				}
			},
			type: "object",
			properties: { a: { type: "string" } },
			dependentSchemas: { a: { $ref: "#/$defs/name" } }
		})
		attest(t.allows({ a: "x" })).equals(false)
		attest(t.allows({ a: "x", n: "y" })).equals(true)
		attest(t.allows({ a: "x", n: 1 })).equals(false)
	})

	it("invalid ref format", () => {
		attest(() =>
			jsonSchemaToType({ $ref: "#/definitions/foo" } as never)
		).throws(writeInvalidRefFormatMessage())
	})

	it("unresolvable ref", () => {
		attest(() =>
			jsonSchemaToType({ $ref: "#/$defs/NonExistentDef" } as never)
		).throws(writeUnresolvableRefMessage("#/$defs/NonExistentDef"))
	})

	it("if/then/else", () => {
		const t = jsonSchemaToType({
			if: { type: "string" },
			then: { minLength: 3 },
			else: { type: "number" }
		})
		attest(t.allows("ab")).equals(false)
		attest(t.allows("abc")).equals(true)
		attest(t.allows(5)).equals(true)
		attest(t.allows(true)).equals(false)
	})

	it("if/then/else combined with type", () => {
		const t = jsonSchemaToType({
			type: "string",
			if: { minLength: 2 },
			then: { maxLength: 4 }
		})
		attest(t.allows("a")).equals(true)
		attest(t.allows("ab")).equals(true)
		attest(t.allows("abcde")).equals(false)
		attest(t.allows(5)).equals(false)
	})

	it("if alone is a no-op", () => {
		const t = jsonSchemaToType({ if: { type: "string" } })
		attest(t.allows(5)).equals(true)
		attest(t.allows("x")).equals(true)
	})

	it("then/else without if are ignored", () => {
		const t = jsonSchemaToType({ then: { type: "string" } } as never)
		attest(t.allows(5)).equals(true)
		attest(t.allows("x")).equals(true)
	})

	it("if/then/else with object fallback", () => {
		const t = jsonSchemaToType({
			if: {
				type: "object",
				properties: { kind: { const: "a" } },
				required: ["kind"]
			},
			then: { properties: { a: { type: "string" } }, required: ["a"] },
			else: { properties: { b: { type: "number" } }, required: ["b"] }
		})
		attest(t.allows({ kind: "a", a: "x" })).equals(true)
		attest(t.allows({ kind: "a" })).equals(false)
		attest(t.allows({ kind: "b", b: 1 })).equals(true)
		attest(t.allows({ kind: "b", b: "x" })).equals(false)
	})

	it("implicit object schema", () => {
		const t = jsonSchemaToType({
			properties: { foo: { type: "string" } },
			required: ["foo"]
		})
		attest(t.expression).snap("{ foo: string }")
		attest(t.allows({ foo: "x" })).equals(true)
		attest(t.allows({})).equals(false)
	})
})
