/** Count includes duplicates; first preserves input order and is null when empty. */
export function summarize(values: number[]): { count: number, first: number | null } {
  return { count: values.length, first: values[0] ?? null };
}
