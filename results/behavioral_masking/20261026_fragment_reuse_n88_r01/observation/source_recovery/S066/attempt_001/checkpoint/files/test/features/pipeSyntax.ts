import dedent from 'dedent-js';

import { FormatFn } from '../../src/sqlFormatter.js';

export default function supportsPipeSyntax(format: FormatFn) {
  it('formats simple BigQuery pipe query', () => {
    const result = format(`FROM table
  |> WHERE a > 1
  |> SELECT a, b
  |> ORDER BY a
  |> LIMIT 10`);
    expect(result).toBe(dedent`
      FROM
        table
      |> WHERE
        a > 1
      |> SELECT
        a,
        b
      |> ORDER BY
        a
      |> LIMIT 10
    `);
  });

  it('formats pipe query with AGGREGATE and nested GROUP BY', () => {
    const result = format(`FROM t |> AGGREGATE SUM(a) AS total GROUP BY b`);
    expect(result).toBe(dedent`
      FROM
        t
      |> AGGREGATE
        SUM(a) AS total
        GROUP BY
          b
    `);
  });

  it('formats pipe-exclusive clauses EXTEND, SET, DROP and AS', () => {
    const result = format(`FROM t |> EXTEND a + 1 AS b |> SET a = 1 |> DROP c |> AS result`);
    expect(result).toBe(dedent`
      FROM
        t
      |> EXTEND
        a + 1 AS b
      |> SET
        a = 1
      |> DROP
        c
      |> AS result
    `);
  });

  it('formats one-line pipe clauses JOIN, LIMIT and AS', () => {
    const result = format(`FROM t |> JOIN u ON u.id = t.id |> LIMIT 5, 10 |> AS result`);
    expect(result).toBe(dedent`
      FROM
        t
      |> JOIN u ON u.id = t.id
      |> LIMIT 5, 10
      |> AS result
    `);
  });

  it('formats pipe query nested in parentheses', () => {
    const result = format(`SELECT * FROM (FROM t |> WHERE x > 1) AS s`);
    expect(result).toBe(dedent`
      SELECT
        *
      FROM
        (
          FROM
            t
          |> WHERE
            x > 1
        ) AS s
    `);
  });

  it('supports keywordCase for pipe keywords', () => {
    const result = format(`from t |> where a > 1 |> select a`, { keywordCase: 'lower' });
    expect(result).toBe(dedent`
      from
        t
      |> where
        a > 1
      |> select
        a
    `);
  });

  it('keeps AS inside pipe SELECT expression on same clause', () => {
    const result = format(`FROM t |> SELECT a AS b, c`);
    expect(result).toBe(dedent`
      FROM
        t
      |> SELECT
        a AS b,
        c
    `);
  });

  it('formats mixed pipe and traditional statements independently', () => {
    const result = format(`FROM t |> SELECT a; SELECT b FROM u;`, { linesBetweenQueries: 0 });
    expect(result).toBe(dedent`
      FROM
        t
      |> SELECT
        a;
      SELECT
        b
      FROM
        u;
    `);
  });

  it('formats pipe query combined with set operation', () => {
    const result = format(`FROM t |> SELECT a UNION ALL SELECT b FROM u`);
    expect(result).toBe(dedent`
      FROM
        t
      |> SELECT
        a
      UNION ALL
      SELECT
        b
      FROM
        u
    `);
  });
}
