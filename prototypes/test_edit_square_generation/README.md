# Independent lexical edit square

`edit_square(A, B, C)` takes three complete source strings. It does not use the tree-analogy views, repository metadata, language grammars, API names or execution outcomes.

The core tokenizes all text with the same lossless regex, computes one deterministic A→B and A→C diff, and verifies both byte-exact reconstructions. It merges disjoint source intervals; overlapping replacements or an insertion strictly inside a replacement conflict. Boundary insertions compose with the replacement. At shared insertion points it tries two globally consistent orders, sharing one result set of at most two candidates.

For example, `f(1)==2 → f([1])==[2]` combines with `f(1)==2 → f(3)==6` to produce `f([3])==[6]`: both the input and the expected expression are transported as existing text edits. Conflicting replacements of the same expected value are rejected without inventing a new expectation.

This is a **parallel alternative experiment**, not an extra stage of the current tree generator. The optional `prototypes.test_edit_square_generation.generate` wrapper reuses the existing corpus, triple selection, budget, novelty, binding-check and emitter interfaces. Its composition callback invokes only this lexical kernel: it does not also invoke raw or aligned tree analogy. `generate(corpus, Budget())` keeps the shared limits of 2,000 attempted triples and 128 selected candidates; both insertion orders consume the same budgets.

The wrapper parses each merged Python, Go or TypeScript body in a small synthetic function and verifies that the resulting body Term renders to exactly the merged bytes. Invalid merged syntax is counted as `edit_square:body_syntax_error` and never enters the candidate pool. Source-relative edits and both reconstruction checks remain in the gate evidence. The oracle policy explicitly attributes inputs and assertions to both source edits, rather than only to B. This interface does not call a model or execute a repository.

Its limits are intentional and visible:

- A deterministic diff is not proof of a unique correspondence. The repeated-token toy shows a conflict under the chosen alignment even though another valid alignment would permit a merge.
- Preserving nonoverlapping source intervals does not establish scope safety, effect independence or oracle correctness. Separate toys have all A/B/C pass while D fails through variable capture or a state interaction.
- Raw merging may produce invalid program syntax. The wrapper rejects parser errors and applies the shared binding checks, but passing these checks still requires semantic admission before experimental use.
- Two shared-insertion orders do not enumerate all interleavings when several shared points exist.

Each result retains the concrete byte/token intervals, replacement text and reconstruction checks. No expected values are supplied by a model or obtained by executing the candidate program.
