import { HttpApiSSE, HttpClientRequest, HttpClientResponse } from "@effect/platform"
import { describe, it } from "@effect/vitest"
import * as assert from "node:assert"
import { Chunk, Effect, Schema, Stream } from "effect"

class A extends Schema.TaggedClass<A>()("A", { a: Schema.String }) {}
class B extends Schema.TaggedClass<B>()("B", { b: Schema.Number }) {}
const Union = Schema.Union(A, B)

describe("HttpApiSSE", () => {
  describe("formatMessage", () => {
    it("formats a simple message", () => {
      assert.strictEqual(HttpApiSSE.formatMessage({ data: "hello" }), "data: hello\n\n")
    })

    it("formats multi-line data", () => {
      assert.strictEqual(
        HttpApiSSE.formatMessage({ data: "line1\nline2" }),
        "data: line1\ndata: line2\n\n"
      )
    })

    it("formats event, id and retry", () => {
      assert.strictEqual(
        HttpApiSSE.formatMessage({ data: "hello", event: "evt", id: "1", retry: 100 }),
        "event: evt\nid: 1\nretry: 100\ndata: hello\n\n"
      )
    })
  })

  describe("formatDataMessage", () => {
    it("JSON encodes the data", () => {
      assert.strictEqual(HttpApiSSE.formatDataMessage({ foo: 1 }), "data: {\"foo\":1}\n\n")
    })
  })

  describe("makeEventEncoder / makeEventDecoder", () => {
    it.effect("round trips", () =>
      Effect.gen(function*() {
        const encode = HttpApiSSE.makeEventEncoder(Union)
        const decode = HttpApiSSE.makeEventDecoder(Union)
        const message = yield* encode(new A({ a: "x" }))
        assert.strictEqual(message, "data: {\"a\":\"x\",\"_tag\":\"A\"}\n\n")
        const value = yield* decode(JSON.stringify({ a: "x", _tag: "A" }))
        assert.ok(value instanceof A)
      }))
  })

  describe("makeUnionEventEncoder / makeUnionEventDecoder", () => {
    it.effect("sets event from _tag for tagged unions", () =>
      Effect.gen(function*() {
        const encode = HttpApiSSE.makeUnionEventEncoder(Union)
        const decode = HttpApiSSE.makeUnionEventDecoder(Union)
        const message = yield* encode(new A({ a: "x" }))
        assert.strictEqual(message, "event: A\ndata: {\"a\":\"x\",\"_tag\":\"A\"}\n\n")
        const value = yield* decode({ data: JSON.stringify({ a: "x" }), event: "A" })
        assert.ok(value instanceof A)
      }))

    it.effect("supports transformed unions", () =>
      Effect.gen(function*() {
        const transformed = Schema.transform(Union, Union, {
          decode: (u) => u,
          encode: (u) => u
        })
        const encode = HttpApiSSE.makeUnionEventEncoder(transformed)
        const message = yield* encode(new B({ b: 1 }))
        assert.strictEqual(message, "event: B\ndata: {\"b\":1,\"_tag\":\"B\"}\n\n")
      }))

    it.effect("supports suspended unions", () =>
      Effect.gen(function*() {
        const suspended = Schema.suspend(() => Union)
        const encode = HttpApiSSE.makeUnionEventEncoder(suspended)
        const message = yield* encode(new B({ b: 1 }))
        assert.strictEqual(message, "event: B\ndata: {\"b\":1,\"_tag\":\"B\"}\n\n")
      }))

    it.effect("falls back to data-only for non-union schemas", () =>
      Effect.gen(function*() {
        const encode = HttpApiSSE.makeUnionEventEncoder(A)
        const message = yield* encode(new A({ a: "x" }))
        assert.strictEqual(message, "data: {\"a\":\"x\",\"_tag\":\"A\"}\n\n")
      }))
  })

  describe("fromStream", () => {
    it.effect("maps a stream through an encoder", () =>
      Effect.gen(function*() {
        const encode = HttpApiSSE.makeUnionEventEncoder(Union)
        const values = yield* Stream.runCollect(
          HttpApiSSE.fromStream(Stream.make(new A({ a: "x" }), new B({ b: 1 })), encode)
        )
        assert.deepStrictEqual(Chunk.toReadonlyArray(values), [
          "event: A\ndata: {\"a\":\"x\",\"_tag\":\"A\"}\n\n",
          "event: B\ndata: {\"b\":1,\"_tag\":\"B\"}\n\n"
        ])
      }))
  })

  describe("toStream", () => {
    it.effect("buffers partial chunks across \\n\\n boundaries", () =>
      Effect.gen(function*() {
        const wire =
          "event: A\ndata: {\"a\":\"hello\"}\n\nevent: B\ndata: {\"b\":42}\n\n"
        const encoder = new TextEncoder()
        const chunks = [0, 7, 20, 45, 55].map((_, i, arr) => {
          const start = i === 0 ? 0 : arr[i]
          const end = i === arr.length - 1 ? wire.length : arr[i + 1]
          return encoder.encode(wire.slice(start, end))
        })
        const response = new Response(new ReadableStream({
          start(controller) {
            for (const chunk of chunks) {
              controller.enqueue(chunk)
            }
            controller.close()
          }
        }), { status: 200 })
        const clientResponse = HttpClientResponse.fromWeb(
          HttpClientRequest.get("http://localhost/stream"),
          response
        )
        const values = yield* Stream.runCollect(
          HttpApiSSE.toStream(clientResponse, HttpApiSSE.makeUnionEventDecoder(Union))
        )
        const events = Chunk.toReadonlyArray(values)
        assert.strictEqual(events.length, 2)
        assert.ok(events[0] instanceof A)
        assert.ok(events[1] instanceof B)
      }))
  })
})
