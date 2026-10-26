cd /app && python3 - <<'PYEOF'
path = 'src/index.ts'
with open(path) as f:
    src = f.read()

# Add imports
old_import = """import { Class, JSONValue, SuperJSONResult, SuperJSONValue } from './types.js';
import { ClassRegistry, RegisterOptions } from './class-registry.js';
import { Registry } from './registry.js';
import {
  CustomTransfomer,
  CustomTransformerRegistry,
} from './custom-transformer-registry.js';"""

new_import = """import { Class, JSONValue, SuperJSONResult, SuperJSONValue } from './types.js';
import { ClassRegistry, RegisterOptions } from './class-registry.js';
import { Registry } from './registry.js';
import {
  CustomTransfomer,
  CustomTransformerRegistry,
} from './custom-transformer-registry.js';
import {
  ErrorStackOptions,
  NormalizedErrorStackOptions,
  normalizeErrorStackOptions,
} from './error-options.js';
import {
  ErrorClassRegistry,
  ErrorStackProcessor,
} from './error-class-registry.js';"""

assert old_import in src
src = src.replace(old_import, new_import)

# Add errorStackOptions field and constructor option
old_ctor = """  private readonly dedupe: boolean;

  /**
   * @param dedupeReferentialEqualities  If true, SuperJSON will make sure only one instance of referentially equal objects are serialized and the rest are replaced with `null`.
   */
  constructor({
    dedupe = false,
  }: {
    dedupe?: boolean;
  } = {}) {
    this.dedupe = dedupe;
  }"""

new_ctor = """  private readonly dedupe: boolean;

  readonly errorStackOptions: NormalizedErrorStackOptions | undefined;

  /**
   * @param dedupeReferentialEqualities  If true, SuperJSON will make sure only one instance of referentially equal objects are serialized and the rest are replaced with `null`.
   * @param errorStack  Options controlling how Error stack data is serialized.
   */
  constructor({
    dedupe = false,
    errorStack,
  }: {
    dedupe?: boolean;
    errorStack?: ErrorStackOptions;
  } = {}) {
    this.dedupe = dedupe;
    this.errorStackOptions = normalizeErrorStackOptions(errorStack);
  }"""

assert old_ctor in src
src = src.replace(old_ctor, new_ctor)

# Add errorClassRegistry field and instance method after allowedErrorProps/allowErrorProps
old_allowed = """  readonly allowedErrorProps: string[] = [];
  allowErrorProps(...props: string[]) {
    this.allowedErrorProps.push(...props);
  }"""

new_allowed = """  readonly allowedErrorProps: string[] = [];
  allowErrorProps(...props: string[]) {
    this.allowedErrorProps.push(...props);
  }

  readonly errorClassRegistry = new ErrorClassRegistry();
  registerErrorStackProcessor(className: string, fn: ErrorStackProcessor) {
    this.errorClassRegistry.register(className, fn);
  }"""

assert old_allowed in src
src = src.replace(old_allowed, new_allowed)

# Add static wrapper + standalone export
old_static = """  static allowErrorProps = SuperJSON.defaultInstance.allowErrorProps.bind(
    SuperJSON.defaultInstance
  );
}"""

new_static = """  static allowErrorProps = SuperJSON.defaultInstance.allowErrorProps.bind(
    SuperJSON.defaultInstance
  );
  static registerErrorStackProcessor =
    SuperJSON.defaultInstance.registerErrorStackProcessor.bind(
      SuperJSON.defaultInstance
    );
}"""

assert old_static in src
src = src.replace(old_static, new_static)

old_exports = """export const registerClass = SuperJSON.registerClass;
export const registerCustom = SuperJSON.registerCustom;
export const registerSymbol = SuperJSON.registerSymbol;
export const allowErrorProps = SuperJSON.allowErrorProps;
"""

new_exports = """export const registerClass = SuperJSON.registerClass;
export const registerCustom = SuperJSON.registerCustom;
export const registerSymbol = SuperJSON.registerSymbol;
export const allowErrorProps = SuperJSON.allowErrorProps;
export const registerErrorStackProcessor =
  SuperJSON.registerErrorStackProcessor;
"""

assert old_exports in src
src = src.replace(old_exports, new_exports)

with open(path, 'w') as f:
    f.write(src)

print("patched index.ts")
PYEOF
cat src/index.ts