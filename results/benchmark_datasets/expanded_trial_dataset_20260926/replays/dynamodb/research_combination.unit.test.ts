// Retrospective witness. Candidate source is unmodified; no reference patch.
import { expect, test } from 'vitest';
import { ZodSchemer } from '~/schema/actions/zodSchemer/index.js';
import { item, string } from '~/schema/index.js';

test('control: conditional requirement rejects with explicit put mode', () => {
  const schema = item({
    type: string().required('always'),
    detail: string().optional().requiredIf('type', 'verbose'),
  });
  schema.check();
  const parser = new ZodSchemer(schema).parser({ mode: 'put' });
  expect(parser.safeParse({ type: 'verbose' }).success).toBe(false);
  expect(parser.safeParse({ type: 'verbose', detail: 'x' }).success).toBe(true);
});

test('control: default parser preserves an ordinary unconditional requirement', () => {
  const schema = item({ type: string().required('always') });
  const parser = new ZodSchemer(schema).parser();
  expect(parser.safeParse({}).success).toBe(false);
  expect(parser.safeParse({ type: 'verbose' }).success).toBe(true);
});

test('combination: default parser must enforce a conditional requirement', () => {
  const schema = item({
    type: string().required('always'),
    detail: string().optional().requiredIf('type', 'verbose'),
  });
  schema.check();
  const parser = new ZodSchemer(schema).parser();
  expect(parser.safeParse({ type: 'simple' }).success).toBe(true);
  expect(parser.safeParse({ type: 'verbose' }).success).toBe(false);
});
