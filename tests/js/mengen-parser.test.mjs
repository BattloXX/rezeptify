import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../../static/js/mengen-parser.js', import.meta.url), 'utf8');
const { parseEintrag, splitMehrfach } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const cases = JSON.parse(await readFile(new URL('../fixtures/mengen_parser_cases.json', import.meta.url), 'utf8'));
for (const { text, expected } of cases.parse) test(`parse: ${text}`, () => assert.deepEqual(parseEintrag(text), expected));
for (const { text, expected } of cases.split) test(`split: ${text}`, () => assert.deepEqual(splitMehrfach(text), expected));
