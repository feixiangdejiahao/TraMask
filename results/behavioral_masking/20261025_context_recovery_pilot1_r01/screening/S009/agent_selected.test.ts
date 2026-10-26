import { attest, contextualize } from "@ark/attest"
import { jsonSchemaToType } from "@ark/json-schema"

contextualize(() => {
	it("recursive $ref inside anyOf composition", () => {
		const t = jsonSchemaToType({
			$defs: {
				Tree: {
					anyOf: [
						{ type: "null" },
						{
							allOf: [
								{ type: "object", properties: { value: { type: "string" } } },
								{
									type: "object",
									properties: {
										children: {
											type: "array",
											items: { $ref: "#/$defs/Tree" }
										}
									}
								}
							]
						}
					]
				}
			},
			$ref: "#/$defs/Tree"
		})
		attest(t.allows(null)).equals(true)
		attest(t.allows({ value: "a", children: [] })).equals(true)
		attest(t.allows({ value: "a", children: [null, { value: "b" }] })).equals(
			true
		)
		attest(t.allows({ value: 1 })).equals(false)
	})
})
