import assert from 'assert';
import { lexer, fork } from 'css-tree';

describe('Lexer#expandShorthand()', () => {
    it('expands box-model shorthands clockwise', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('margin', '10px 20px'),
            {
                'margin-top': '10px',
                'margin-right': '20px',
                'margin-bottom': '10px',
                'margin-left': '20px'
            }
        );
    });

    it('expands one box-model value to all sides', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('padding', '1px'),
            {
                'padding-top': '1px',
                'padding-right': '1px',
                'padding-bottom': '1px',
                'padding-left': '1px'
            }
        );
    });

    it('expands inset', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('inset', '10px 20px 30px 40px'),
            {
                top: '10px',
                right: '20px',
                bottom: '30px',
                left: '40px'
            }
        );
    });
    it('expands two-value box-model shorthands', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('margin-block', '10px 20px'),
            { 'margin-block-start': '10px', 'margin-block-end': '20px' }
        );

        assert.deepStrictEqual(
            lexer.expandShorthand('padding-inline', '10px'),
            { 'padding-inline-start': '10px', 'padding-inline-end': '10px' }
        );
    });


    it('expands border-radius with slash', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('border-radius', '10px 20px / 5px 6px'),
            {
                'border-top-left-radius': '10px 5px',
                'border-top-right-radius': '20px 6px',
                'border-bottom-right-radius': '10px 5px',
                'border-bottom-left-radius': '20px 6px'
            }
        );
    });

    it('expands component shorthands in any order', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('border-top', 'red solid 1px'),
            {
                'border-top-width': '1px',
                'border-top-style': 'solid',
                'border-top-color': 'red'
            }
        );
    });

    it('expands text-decoration', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('text-decoration', 'underline wavy red 2px'),
            {
                'text-decoration-line': 'underline',
                'text-decoration-style': 'wavy',
                'text-decoration-color': 'red',
                'text-decoration-thickness': '2px'
            }
        );
    });

    it('expands list-style', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('list-style', 'square outside url(x)'),
            {
                'list-style-type': 'square',
                'list-style-position': 'outside',
                'list-style-image': 'url(x)'
            }
        );
    });

    it('expands flex-flow', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('flex-flow', 'row wrap'),
            {
                'flex-direction': 'row',
                'flex-wrap': 'wrap'
            }
        );
    });

    it('expands two-value shorthands', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('overflow', 'hidden auto'),
            { 'overflow-x': 'hidden', 'overflow-y': 'auto' }
        );

        assert.deepStrictEqual(
            lexer.expandShorthand('gap', '10px'),
            { 'row-gap': '10px', 'column-gap': '10px' }
        );
    });

    it('expands background layers', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('background', 'url(a.png) no-repeat, url(b.png) center red'),
            {
                'background-image': 'url(a.png), url(b.png)',
                'background-position': '0% 0%, center',
                'background-size': 'auto auto, auto auto',
                'background-repeat': 'no-repeat, repeat',
                'background-origin': 'padding-box, padding-box',
                'background-clip': 'border-box, border-box',
                'background-attachment': 'scroll, scroll',
                'background-color': 'transparent, red'
            }
        );
    });

    it('expands font', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('font', 'italic bold 16px/1.5 Arial'),
            {
                'font-style': 'italic',
                'font-variant': 'normal',
                'font-weight': 'bold',
                'font-stretch': 'normal',
                'font-size': '16px',
                'line-height': '1.5',
                'font-family': 'Arial'
            }
        );
    });

    it('expands flex', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('flex', '1 0 auto'),
            { 'flex-grow': '1', 'flex-shrink': '0', 'flex-basis': 'auto' }
        );
    });

    it('expands CSS-wide keywords to every longhand', () => {
        assert.deepStrictEqual(
            lexer.expandShorthand('margin', 'inherit'),
            {
                'margin-top': 'inherit',
                'margin-right': 'inherit',
                'margin-bottom': 'inherit',
                'margin-left': 'inherit'
            }
        );
    });

    it('returns null for unknown shorthand', () => {
        assert.strictEqual(lexer.expandShorthand('color', 'red'), null);
        assert.strictEqual(lexer.expandShorthand('margin-top', '10px'), null);
    });

    it('returns null for invalid values', () => {
        assert.strictEqual(lexer.expandShorthand('margin', '10px 20px 30px 40px 50px'), null);
        assert.strictEqual(lexer.expandShorthand('margin', 'red'), null);
    });

    it('works with custom syntax created via fork()', () => {
        const custom = fork({
            properties: {
                'my-short': "<'my-a'> || <'my-b'>",
                'my-a': { syntax: 'foo | bar', initial: 'foo' },
                'my-b': { syntax: 'baz | qux', initial: 'qux' }
            }
        });

        assert.deepStrictEqual(
            custom.lexer.expandShorthand('my-short', 'baz foo'),
            { 'my-a': 'foo', 'my-b': 'baz' }
        );
        assert.strictEqual(custom.lexer.expandShorthand('my-a', 'foo'), null);
    });
});

describe('Lexer#compressShorthand()', () => {
    it('compresses box-model shorthands to the fewest values', () => {
        assert.strictEqual(
            lexer.compressShorthand('margin', {
                'margin-top': '10px',
                'margin-right': '10px',
                'margin-bottom': '10px',
                'margin-left': '10px'
            }),
            '10px'
        );

        assert.strictEqual(
            lexer.compressShorthand('margin', {
                'margin-top': '10px',
                'margin-right': '20px',
                'margin-bottom': '10px',
                'margin-left': '20px'
            }),
            '10px 20px'
        );
    });

    it('compresses two-value shorthands', () => {
        assert.strictEqual(
            lexer.compressShorthand('overflow', {
                'overflow-x': 'hidden',
                'overflow-y': 'hidden'
            }),
            'hidden'
        );

        assert.strictEqual(
            lexer.compressShorthand('gap', {
                'row-gap': '10px',
                'column-gap': '20px'
            }),
            '10px 20px'
        );
    });

    it('compresses component shorthands in canonical order', () => {
        assert.strictEqual(
            lexer.compressShorthand('border', {
                'border-width': '1px',
                'border-style': 'solid',
                'border-color': 'red'
            }),
            '1px solid red'
        );
    });

    it('joins background position/size and font size/line-height with slash', () => {
        assert.strictEqual(
            lexer.compressShorthand('font', {
                'font-style': 'normal',
                'font-variant': 'normal',
                'font-weight': 'normal',
                'font-stretch': 'normal',
                'font-size': '16px',
                'line-height': '1.5',
                'font-family': 'Arial'
            }),
            'normal normal normal normal 16px/1.5 Arial'
        );
    });

    it('compresses background layers', () => {
        const longhands = {
            'background-image': 'url(a.png), url(b.png)',
            'background-position': '0% 0%, center',
            'background-size': 'auto auto, auto auto',
            'background-repeat': 'no-repeat, repeat',
            'background-origin': 'padding-box, padding-box',
            'background-clip': 'border-box, border-box',
            'background-attachment': 'scroll, scroll',
            'background-color': 'transparent, red'
        };

        assert.strictEqual(
            lexer.compressShorthand('background', longhands),
            'url(a.png) 0% 0%/auto auto no-repeat padding-box border-box scroll, ' +
            'url(b.png) center/auto auto repeat padding-box border-box scroll red'
        );
    });

    it('compresses all-CSS-wide-keyword longhands to a single keyword', () => {
        assert.strictEqual(
            lexer.compressShorthand('margin', {
                'margin-top': 'inherit',
                'margin-right': 'inherit',
                'margin-bottom': 'inherit',
                'margin-left': 'inherit'
            }),
            'inherit'
        );
    });

    it('returns null for differing CSS-wide keywords', () => {
        assert.strictEqual(
            lexer.compressShorthand('margin', {
                'margin-top': 'inherit',
                'margin-right': 'initial',
                'margin-bottom': 'inherit',
                'margin-left': 'inherit'
            }),
            null
        );
    });

    it('returns null for unknown shorthand', () => {
        assert.strictEqual(lexer.compressShorthand('color', {}), null);
    });

    it('returns null for incomplete longhand sets', () => {
        assert.strictEqual(
            lexer.compressShorthand('margin', { 'margin-top': '10px' }),
            null
        );
    });
    it('returns null for inconsistent background layer counts', () => {
        assert.strictEqual(
            lexer.compressShorthand('background', {
                'background-image': 'none, none',
                'background-position': '0% 0%',
                'background-size': 'auto auto, auto auto',
                'background-repeat': 'repeat, repeat',
                'background-origin': 'padding-box, padding-box',
                'background-clip': 'border-box, border-box',
                'background-attachment': 'scroll, scroll',
                'background-color': 'transparent, red'
            }),
            null
        );
    });


    it('round-trips expand then compress', () => {
        const values = [
            ['margin', '10px 20px 30px 40px'],
            ['border-radius', '10px 20px / 5px 6px'],
            ['border', '1px solid red'],
            ['background', 'url(a.png) no-repeat, url(b.png) center red'],
            ['font', 'italic bold 16px/1.5 Arial'],
            ['flex', '1 0 auto'],
            ['text-decoration', 'underline wavy red 2px']
        ];

        for (const [property, value] of values) {
            const expanded = lexer.expandShorthand(property, value);
            const compressed = lexer.compressShorthand(property, expanded);

            assert.deepStrictEqual(
                lexer.expandShorthand(property, compressed),
                expanded
            );
        }
    });
});
