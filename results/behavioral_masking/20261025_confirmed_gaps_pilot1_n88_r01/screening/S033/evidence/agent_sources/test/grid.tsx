import React from 'react';
import test from 'ava';
import {Box, Text, render} from '../src/index.js';
import {
	renderToString,
	renderToStringAsync,
} from './helpers/render-to-string.js';
import createStdout from './helpers/create-stdout.js';

test('display grid places children into fixed columns', t => {
	const output = renderToString(
		<Box width={11} display="grid" gridTemplateColumns="5 5" columnGap={1}>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(output, 'A     B');
});

test('grid distributes space proportionally between fr columns', t => {
	const output = renderToString(
		<Box width={10} display="grid" gridTemplateColumns="1fr 2fr" columnGap={1}>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(output, 'A   B');
});

test('grid supports auto columns', t => {
	const output = renderToString(
		<Box
			width={10}
			display="grid"
			gridTemplateColumns="auto auto"
			columnGap={1}
		>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(output, 'A B');
});

test('grid supports minmax with fixed maximum', t => {
	const output = renderToString(
		<Box
			width={20}
			display="grid"
			gridTemplateColumns="minmax(3, 5) minmax(3, 5)"
			columnGap={1}
		>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(output, 'A   B');
});

test('grid supports minmax with fr maximum', t => {
	const output = renderToString(
		<Box
			width={20}
			display="grid"
			gridTemplateColumns="minmax(3, 1fr) minmax(3, 2fr)"
			columnGap={1}
		>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(output, 'A       B');
});

test('grid supports explicit rows and row gap', t => {
	const output = renderToString(
		<Box
			width={5}
			height={5}
			display="grid"
			gridTemplateColumns="5"
			gridTemplateRows="2 2"
			rowGap={1}
		>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(output, 'A\n\n\nB\n');
});

test('grid creates rows automatically when gridTemplateRows is omitted', t => {
	const output = renderToString(
		<Box width={5} display="grid" gridTemplateColumns="5">
			<Text>A</Text>
			<Text>B</Text>
			<Text>C</Text>
		</Box>,
	);

	t.is(output, 'A\nB\nC');
});

test('grid accepts a single index for gridColumn', t => {
	const output = renderToString(
		<Box width={15} display="grid" gridTemplateColumns="5 5 5" columnGap={1}>
			<Box>
				<Text>A</Text>
			</Box>
			<Box gridColumn={3}>
				<Text>C</Text>
			</Box>
		</Box>,
	);

	t.is(output, 'A           C');
});

test('grid accepts start / end for gridColumn', t => {
	const output = renderToString(
		<Box width={15} display="grid" gridTemplateColumns="5 5 5" columnGap={1}>
			<Box gridColumn="1 / 3">
				<Text>A</Text>
			</Box>
			<Box>
				<Text>B</Text>
			</Box>
		</Box>,
	);

	t.is(output, 'A           B');
});

test('grid accepts start / end for gridRow', t => {
	const output = renderToString(
		<Box
			width={5}
			height={5}
			display="grid"
			gridTemplateColumns="5"
			gridTemplateRows="1 1 1"
			rowGap={1}
		>
			<Text gridRow="1 / 3">A</Text>
		</Box>,
	);

	t.is(output, 'A\n\n\n\n');
});

test('grid gap shorthand applies to tracks', t => {
	const output = renderToString(
		<Box width={11} display="grid" gridTemplateColumns="5 5" gap={1}>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(output, 'A     B');
});

test('grid with fr rows distributes remaining height', t => {
	const output = renderToString(
		<Box
			width={5}
			height={5}
			display="grid"
			gridTemplateColumns="5"
			gridTemplateRows="1fr 2fr"
			rowGap={1}
		>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(output, 'A\n\nB\n\n');
});

test('grid display grid - concurrent', async t => {
	const output = await renderToStringAsync(
		<Box width={11} display="grid" gridTemplateColumns="5 5" columnGap={1}>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(output, 'A     B');
});

test('grid auto-places items around explicit rows', t => {
	const output = renderToString(
		<Box width={5} display="grid" gridTemplateColumns="5">
			<Box gridRow={3}>
				<Text>C</Text>
			</Box>
			<Box>
				<Text>A</Text>
			</Box>
			<Box>
				<Text>B</Text>
			</Box>
		</Box>,
	);

	t.is(output, 'A\nB\nC');
});

test('grid wraps auto-placed items to new rows', t => {
	const output = renderToString(
		<Box
			width={15}
			display="grid"
			gridTemplateColumns="5 5 5"
			columnGap={1}
			rowGap={1}
		>
			<Box>
				<Text>A</Text>
			</Box>
			<Box>
				<Text>B</Text>
			</Box>
			<Box>
				<Text>C</Text>
			</Box>
			<Box>
				<Text>D</Text>
			</Box>
		</Box>,
	);

	t.is(output, 'A     B     C\n\nD');
});

test('grid layout is stable across rerenders', t => {
	const stdout = createStdout(100);
	const {rerender, unmount} = render(
		<Box
			width={10}
			display="grid"
			gridTemplateColumns="auto auto"
			columnGap={1}
		>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
		{stdout, debug: true, exitOnCtrlC: false, patchConsole: false},
	);

	t.is(stdout.get(), 'A B');

	rerender(
		<Box
			width={10}
			display="grid"
			gridTemplateColumns="auto auto"
			columnGap={1}
		>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(stdout.get(), 'A B');

	rerender(
		<Box
			width={10}
			display="grid"
			gridTemplateColumns="auto auto"
			columnGap={1}
		>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
	);

	t.is(stdout.get(), 'A B');
});
