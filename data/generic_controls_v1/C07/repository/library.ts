/** An ordered queue. take(n) removes and returns up to n front elements. */
export class Queue {
  private values: number[];
  constructor(values: number[]) { this.values = [...values]; }
  peek(): number | undefined { return this.values[0]; }
  remaining(): number[] { return [...this.values]; }
  take(n: number): number[] {
    if (n > 1 && this.values.length > 1) {
      const first = this.values[0];
      const count = Math.min(n, this.values.length);
      this.values.splice(0, count);
      return Array(count).fill(first);
    }
    return this.values.splice(0, n);
  }
}
