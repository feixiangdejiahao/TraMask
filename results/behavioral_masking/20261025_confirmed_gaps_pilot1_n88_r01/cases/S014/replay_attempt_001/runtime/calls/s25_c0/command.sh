cd /app && python3 - <<'PY'
import re
p='packages/core/src/prompts/autocomplete.ts'
s=open(p).read()
old = '''	#fetchSync(search: string): void {
		const id = ++this.#fetchId;
		const options = this.#resolver.call(this, search, { signal: undefined as unknown as AbortSignal });
		this.#options = options;
		this.filteredOptions = this.#filterOptions(options, search);
		this.#updateCursorAndSelection();
		this.#setupInitialValues();
		if (id !== this.#fetchId) {
			return;
		}
		this.#renderIfActive();
	}'''
new = '''	#fetchSync(search: string): void {
		this.#clearTimers();
		this.#abortCurrentFetch();
		const id = ++this.#fetchId;
		const controller = new AbortController();
		this.#abortController = controller;
		const options = this.#resolver.call(this, search, { signal: controller.signal });
		this.#abortController = undefined;
		this.#options = options;
		this.filteredOptions = this.#filterOptions(options, search);
		this.#updateCursorAndSelection();
		this.#setupInitialValues();
		if (id !== this.#fetchId) {
			return;
		}
		this.#renderIfActive();
	}'''
assert old in s
s=s.replace(old,new)
open(p,'w').write(s)
print("done")
PY