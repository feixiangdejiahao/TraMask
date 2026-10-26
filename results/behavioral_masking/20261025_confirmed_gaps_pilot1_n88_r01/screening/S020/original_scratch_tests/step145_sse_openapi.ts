import { HttpApi, HttpApiEndpoint, HttpApiGroup, HttpApiSchema, OpenApi } from "@effect/platform"
import { Schema } from "effect"

class EventA extends Schema.TaggedClass<EventA>()("EventA", { value: Schema.String }) {}
class EventB extends Schema.TaggedClass<EventB>()("EventB", { value: Schema.Number }) {}
const Event = Schema.Union(EventA, EventB)

class SSEApi extends HttpApiGroup.make("sse")
  .add(
    HttpApiEndpoint.sse("stream", "/stream")
      .addSuccess(HttpApiSchema.withSSE(Event))
  ) {}

class Api extends HttpApi.make("api").add(SSEApi) {}

const spec = OpenApi.fromApi(Api)
console.log(JSON.stringify(spec.paths["/stream"].get.responses, null, 2))
