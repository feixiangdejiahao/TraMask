cat > /app/.changeset/async-autocomplete.md <<'EOF'
---
"@clack/core": minor
"@clack/prompts": minor
---

Add async search-as-you-type support to `AutocompletePrompt`, `autocomplete`, and `autocompleteMultiselect`. Options can now be a function returning a Promise, with debouncing, result caching, stale-while-revalidate, retries, fallback options, loading messages, and minimum search length support.
EOF
cd /app && cat .changeset/async-autocomplete.md