import React from 'react';
import test from 'ava';
import {Box, Text} from '../src/index.js';
import {
	renderToString,
	renderToStringAsync,
} from './helpers/render-to-string.js';

test('display grid places children into columns', t => {
	const output = renderToString(
		<Box display="grid" gridTemplateColumns="10 10" width={20}>
			<Text>A</Text>
			<Text>B</Text>
			<Text>C</Text>
			<Text>D</Text>
		</Box>,
		{columns: 20},
	);

	t.is(output, 'A         B\nC         D');
});

test('grid gap applies to tracks', t => {
	const output = renderToString(
		<Box display="grid" gridTemplateColumns="5 5" gap={1} width={11}>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
		{columns: 11},
	);

	t.is(output, 'A     B');
});

test('grid column and row gap apply to tracks', t => {
	const output = renderToString(
		<Box
			display="grid"
			gridTemplateColumns="3 3"
			columnGap={1}
			rowGap={1}
			width={7}
		>
			<Text>A</Text>
			<Text>B</Text>
			<Text>C</Text>
			<Text>D</Text>
		</Box>,
		{columns: 7},
	);

	t.is(output, 'A   B\n\nC   D');
});

test('fr columns distribute remaining space', t => {
	const output = renderToString(
		<Box display="grid" gridTemplateColumns="1fr 2fr" width={12}>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
		{columns: 12},
	);

	t.is(output, 'A   B');
});

test('minmax with fr max distributes remaining space after minimums', t => {
	const output = renderToString(
		<Box
			display="grid"
			gridTemplateColumns="minmax(10, 1fr) minmax(20, 1fr)"
			width={40}
		>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
		{columns: 40},
	);

	t.is(output, 'A              B');
});

test('rows are created automatically as needed', t => {
	const output = renderToString(
		<Box display="grid" gridTemplateColumns="5 5" width={10}>
			<Text>A</Text>
			<Text>B</Text>
			<Text>C</Text>
			<Text>D</Text>
		</Box>,
		{columns: 10},
	);

	t.is(output, 'A    B\nC    D');
});

test('grid without column template uses a single column', t => {
	const output = renderToString(
		<Box display="grid" width={10}>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
		{columns: 10},
	);

	t.is(output, 'A\nB');
});

test('children can be explicitly placed with gridColumn and gridRow', t => {
	const output = renderToString(
		<Box
			display="grid"
			gridTemplateColumns="5 5"
			gridTemplateRows="5 5"
			width={10}
			height={10}
		>
			<Box gridColumn="2" gridRow="2">
				<Text>D</Text>
			</Box>
			<Box>
				<Text>A</Text>
			</Box>
		</Box>,
		{columns: 10},
	);

	t.is(output, 'A\n\n\n\n\n     D\n\n\n\n');
});

test('gridColumn and gridRow accept start / end string', t => {
	const output = renderToString(
		<Box display="grid" gridTemplateColumns="5 5 5" width={15}>
			<Box gridColumn="1 / 3">
				<Text>AB</Text>
			</Box>
			<Text>C</Text>
		</Box>,
		{columns: 15},
	);

	t.is(output, 'AB        C');
});

test('Text children can be explicitly placed', t => {
	const output = renderToString(
		<Box display="grid" gridTemplateColumns="5 5" width={10}>
			<Text gridColumn="2">B</Text>
			<Text gridColumn="1">A</Text>
		</Box>,
		{columns: 10},
	);

	t.is(output, 'A    B');
});

test('grid - concurrent', async t => {
	const output = await renderToStringAsync(
		<Box display="grid" gridTemplateColumns="5 5" width={10}>
			<Text>A</Text>
			<Text>B</Text>
			<Text>C</Text>
		</Box>,
		{columns: 10},
	);

	t.is(output, 'A    B\nC');
});

test('gridTemplateRows with fixed tracks', t => {
	const output = renderToString(
		<Box
			display="grid"
			gridTemplateColumns="5 5"
			gridTemplateRows="2 2"
			width={10}
			height={4}
		>
			<Text>A</Text>
			<Text>B</Text>
			<Text>C</Text>
			<Text>D</Text>
		</Box>,
		{columns: 10},
	);

	t.is(output, 'A    B\n\nC    D\n');
});

test('auto tracks size to content', t => {
	const output = renderToString(
		<Box display="grid" gridTemplateColumns="auto 1fr" width={12}>
			<Text>AA</Text>
			<Text>B</Text>
		</Box>,
		{columns: 12},
	);

	t.is(output, 'AAB');
});

test('minmax with fixed maximum', t => {
	const output = renderToString(
		<Box
			display="grid"
			gridTemplateColumns="minmax(5, 10) 1fr"
			width={20}
		>
			<Text>A</Text>
			<Text>B</Text>
		</Box>,
		{columns: 20},
	);

	t.is(output, 'A    B');
});

test('Text children can be explicitly placed with gridRow', t => {
	const output = renderToString(
		<Box
			display="grid"
			gridTemplateColumns="5"
			gridTemplateRows="3 3"
			width={5}
			height={6}
		>
			<Text gridRow="2">B</Text>
			<Text>A</Text>
		</Box>,
		{columns: 5},
	);

	t.is(output, 'A\n\n\nB\n\n');
});
