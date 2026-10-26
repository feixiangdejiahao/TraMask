import {RulesRunner, createRunLinterRulesOptions} from '../src/rules-runner';
import {DEFAULT_SETTINGS, LinterSettings} from '../src/settings-data';
import {rules} from '../src/rules';
import {getLinterDisableDirectives, getLinterDisableSectionsInText, registerRuleAlias} from '../src/utils/linter-disable';
import '../src/rules-registry';
import {defaultMisspellings} from './common';
import dedent from 'ts-dedent';
import TrailingSpaces from '../src/rules/trailing-spaces';

const rulesRunner = new RulesRunner();

function lint(text: string, enabledRules: string[]): string {
  const settings = JSON.parse(JSON.stringify(DEFAULT_SETTINGS)) as LinterSettings;
  settings.ruleConfigs = {};
  for (const rule of rules) {
    settings.ruleConfigs[rule.alias] = {};
  }
  for (const alias of enabledRules) {
    settings.ruleConfigs[alias] = {enabled: true};
  }
  const options = createRunLinterRulesOptions(text, null, 'en-gb', settings, defaultMisspellings());
  return rulesRunner.lintText(options);
}

describe('Linter Disable Markers', () => {
  describe('rule list normalization', () => {
    it('parses directives for both comment formats', () => {
      const text = dedent`
        <!-- linter-disable: trailing-spaces, capitalize-headings -->
        %% linter-disable-next-line: trailing-spaces %%
        %% linter-disable-next-n-lines: 2 trailing-spaces %%
      `;
      const directives = getLinterDisableDirectives(text);
      expect(directives.length).toBe(3);
      expect(directives[0].type).toBe('disable');
      expect([...directives[0].rules]).toEqual(['trailing-spaces', 'capitalize-headings']);
      expect(directives[1].type).toBe('disable-next-line');
      expect([...directives[1].rules]).toEqual(['trailing-spaces']);
      expect(directives[2].type).toBe('disable-next-n-lines');
      expect(directives[2].numLines).toBe(2);
    });

    it('normalizes case, removes duplicates, ignores empty entries and trailing commas', () => {
      const text = dedent`
        <!-- linter-disable: Trailing-Spaces, TRAILING-SPACES, , -->
      `;
      const directives = getLinterDisableDirectives(text);
      expect([...directives[0].rules]).toEqual(['trailing-spaces']);
    });

    it('ignores unknown rule aliases', () => {
      registerRuleAlias('trailing-spaces');
      const text = dedent`
        <!-- linter-disable: not-a-rule, trailing-spaces -->
      `;
      const directives = getLinterDisableDirectives(text);
      expect([...directives[0].rules]).toEqual(['trailing-spaces']);
    });

    it('has no effect when a rule list normalizes to empty', () => {
      const before = dedent`
        a   
        <!-- linter-disable: not-a-rule -->
        b   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).not.toContain('b   ');
    });

    it('treats a disable marker without a rule list as all rules', () => {
      const before = dedent`
        a   
        <!-- linter-disable -->
        b   
        <!-- linter-enable -->
        c   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).toContain('b   ');
      expect(after).not.toContain('c   ');
    });
  });

  describe('ranged scopes', () => {
    it('disables only the listed rule', () => {
      const before = dedent`
        Some text   
        <!-- linter-disable: trailing-spaces -->
        Ignored text   
        <!-- linter-enable: trailing-spaces -->
        More text   
      `;
      const after = lint(before, ['trailing-spaces', 'capitalize-headings']);
      expect(after).toContain('Ignored text   ');
      expect(after).toContain('<!-- linter-disable: trailing-spaces -->');
      expect(after).toContain('<!-- linter-enable: trailing-spaces -->');
      expect(after).not.toContain('Some text   ');
      expect(after).not.toContain('More text   ');
    });

    it('works with Obsidian comment markers', () => {
      const before = dedent`
        a   
        %% linter-disable: trailing-spaces %%
        b   
        %% linter-enable: trailing-spaces %%
        c   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).toContain('b   ');
      expect(after).not.toContain('c   ');
      expect(after).toContain('%% linter-disable: trailing-spaces %%');
      expect(after).toContain('%% linter-enable: trailing-spaces %%');
    });

    it('supports disabling all rules and re-enabling a specific rule within the scope', () => {
      const before = dedent`
        a   
        <!-- linter-disable -->
        b   
        <!-- linter-enable: trailing-spaces -->
        c   
        <!-- linter-enable -->
        d   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).toContain('b   ');
      expect(after).not.toContain('c   ');
      expect(after).not.toContain('d   ');
    });

    it('supports nested scopes with stack semantics', () => {
      const before = dedent`
        a   
        <!-- linter-disable -->
        b   
        <!-- linter-disable: trailing-spaces -->
        c   
        <!-- linter-enable -->
        d   
        <!-- linter-enable -->
        e   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).not.toContain('a   ');
      expect(after).toContain('b   ');
      expect(after).toContain('c   ');
      expect(after).toContain('d   ');
      expect(after).not.toContain('e   ');
    });

    it('closes only the nearest scope when enabling a specific rule', () => {
      const before = dedent`
        a   
        <!-- linter-disable: trailing-spaces -->
        b   
        <!-- linter-disable: trailing-spaces -->
        c   
        <!-- linter-enable: trailing-spaces -->
        d   
        <!-- linter-enable: trailing-spaces -->
        e   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).toContain('b   ');
      expect(after).toContain('c   ');
      expect(after).toContain('d   ');
      expect(after).not.toContain('e   ');
    });

    it('protects until end of file when a disable scope is not closed', () => {
      const before = dedent`
        a   
        <!-- linter-disable: trailing-spaces -->
        b   
        c   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).toContain('b   ');
      expect(after).toContain('c   ');
    });
  });

  describe('line scoped disables', () => {
    it('disables the next line', () => {
      const before = dedent`
        a   
        <!-- linter-disable-next-line: trailing-spaces -->
        b   
        c   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).toContain('b   ');
      expect(after).not.toContain('c   ');
    });

    it('disables the next N lines and clamps to end of file', () => {
      const before = dedent`
        a   
        <!-- linter-disable-next-n-lines: 5 trailing-spaces -->
        b   
        c   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).toContain('b   ');
      expect(after).toContain('c   ');
    });

    it('has no effect when there is no following line', () => {
      const before = `a   \n<!-- linter-disable-next-line: trailing-spaces -->\n`;
      const after = lint(before, ['trailing-spaces']);
      expect(after).not.toContain('a   ');
    });

    it('ignores non-positive or non-numeric N', () => {
      const before = dedent`
        a   
        <!-- linter-disable-next-n-lines: 0 trailing-spaces -->
        b   
        <!-- linter-disable-next-n-lines: -1 trailing-spaces -->
        c   
        <!-- linter-disable-next-n-lines: abc trailing-spaces -->
        d   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).not.toContain('b   ');
      expect(after).not.toContain('c   ');
      expect(after).not.toContain('d   ');
    });
  });

  describe('marker recognition', () => {
    it('only recognizes standalone markers', () => {
      const before = dedent`
        a <!-- linter-disable: trailing-spaces -->   
        b   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).not.toContain('b   ');
    });

    it('ignores markers inside YAML frontmatter', () => {
      const before = dedent`
        ---
        <!-- linter-disable: trailing-spaces -->
        ---
        a   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).not.toContain('a   ');
    });

    it('ignores markers inside fenced code blocks', () => {
      const before = dedent`
        a   
        \`\`\`
        <!-- linter-disable: trailing-spaces -->
        b   
        <!-- linter-enable: trailing-spaces -->
        \`\`\`
        c   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).toContain('<!-- linter-disable: trailing-spaces -->');
      expect(after).not.toContain('c   ');
    });

    it('ignores markers inside indented code blocks', () => {
      const before = dedent`
        a   
            <!-- linter-disable: trailing-spaces -->
        b   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).not.toContain('b   ');
    });

    it('ignores markers inside inline code', () => {
      const before = '`a\n<!-- linter-disable: trailing-spaces -->\nz`\n  b   \n';
      const after = lint(before, ['trailing-spaces']);
      expect(after).not.toContain('b   ');
    });

    it('ignores markers inside math blocks', () => {
      const before = dedent`
        $$
        <!-- linter-disable: trailing-spaces -->
        $$
        a   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).not.toContain('a   ');
    });
  });

  describe('marker line protection', () => {
    it('never modifies marker lines even for rules they do not disable', () => {
      const before = dedent`
        <!-- linter-disable: capitalize-headings -->   
        a   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).toContain('<!-- linter-disable: capitalize-headings -->   ');
    });

    it('never modifies marker lines for line scoped markers', () => {
      const before = dedent`
        <!-- linter-disable-next-line: trailing-spaces -->   
        a   
      `;
      const after = lint(before, ['trailing-spaces']);
      expect(after).toContain('<!-- linter-disable-next-line: trailing-spaces -->   ');
    });

    it('always includes marker lines in sections even when a rule is not disabled', () => {
      const text = dedent`
        <!-- linter-disable: trailing-spaces -->
        a
        <!-- linter-enable: trailing-spaces -->
        b
      `;
      const sections = getLinterDisableSectionsInText(text, 'capitalize-headings');
      expect(sections.length).toBe(2);
      expect(text.substring(sections[0].startIndex, sections[0].endIndex)).toContain('linter-disable');
      expect(text.substring(sections[1].startIndex, sections[1].endIndex)).toContain('linter-enable');
    });
  });

  describe('robustness', () => {
    it('re-detects scopes after other rules shift line numbers', () => {
      const before = dedent`
        line1

        line2
        <!-- linter-disable: trailing-spaces -->
        a   
        <!-- linter-enable: trailing-spaces -->
        line3   
      `;
      const after = lint(before, ['trailing-spaces', 'consecutive-blank-lines']);
      expect(after).toContain('a   ');
      expect(after).toContain('<!-- linter-disable: trailing-spaces -->');
      expect(after).toContain('<!-- linter-enable: trailing-spaces -->');
    });

    it('works when a rule is applied directly', () => {
      const rule = TrailingSpaces.getRule();
      const before = dedent`
        a   
        <!-- linter-disable: trailing-spaces -->
        b   
        <!-- linter-enable: trailing-spaces -->
        c   
      `;
      const after = rule.apply(before, {enabled: true});
      expect(after).toContain('b   ');
      expect(after).toContain('<!-- linter-disable: trailing-spaces -->');
    });
  });
});

describe('Linter Disable Markers - syntax variants', () => {
  it('supports colon after next-n-lines N', () => {
    const text = dedent`
      <!-- linter-disable-next-n-lines: 5: trailing-spaces -->
    `;
    const directives = getLinterDisableDirectives(text);
    expect(directives[0].type).toBe('disable-next-n-lines');
    expect(directives[0].numLines).toBe(5);
    expect([...directives[0].rules]).toEqual(['trailing-spaces']);
  });

  it('supports disable-next-line without a colon before the rule list', () => {
    const text = dedent`
      %% linter-disable-next-line trailing-spaces %%
    `;
    const directives = getLinterDisableDirectives(text);
    expect(directives[0].type).toBe('disable-next-line');
    expect([...directives[0].rules]).toEqual(['trailing-spaces']);
  });

  it('supports disable-next-n-lines without a colon before N', () => {
    const text = dedent`
      <!-- linter-disable-next-n-lines 3 trailing-spaces -->
    `;
    const directives = getLinterDisableDirectives(text);
    expect(directives[0].type).toBe('disable-next-n-lines');
    expect(directives[0].numLines).toBe(3);
    expect([...directives[0].rules]).toEqual(['trailing-spaces']);
  });

  it('supports trailing whitespace after a marker', () => {
    const before = dedent`
      a   
      <!-- linter-disable: trailing-spaces -->   
      b   
      <!-- linter-enable: trailing-spaces -->   
      c   
    `;
    const after = lint(before, ['trailing-spaces']);
    expect(after).toContain('b   ');
    expect(after).not.toContain('c   ');
  });
});

describe('Linter Disable Markers - legacy spacing', () => {
  it('supports no-space HTML and Obsidian markers', () => {
    const text = dedent`
      <!--linter-disable: trailing-spaces-->
      %%linter-enable: trailing-spaces%%
    `;
    const directives = getLinterDisableDirectives(text);
    expect(directives.length).toBe(2);
    expect(directives[0].type).toBe('disable');
    expect(directives[1].type).toBe('enable');
  });
});
