/** An ordered queue. take(n) removes and returns up to n front elements. */
export class Queue {
  private values: number[];
  constructor(values: number[]) { this.values = [...values]; }
  peek(): number | undefined { return this.values[0]; }
  remaining(): number[] { return [...this.values]; }
  take(n: number): number[] { return this.values.splice(0, n); }
}
