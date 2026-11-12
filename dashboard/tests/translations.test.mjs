import assert from 'node:assert/strict'
import { readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import typescript from 'typescript'
import { parse } from 'vue/compiler-sfc'

// Text a person reads must go through __(). This test finds the literals that do not.
// The baseline holds the count each file had before the dashboard was translated; a
// file may only go down. Run with UPDATE_TRANSLATION_BASELINE=1 to write the new counts.

const DASHBOARD = fileURLToPath(new URL('..', import.meta.url))
const SOURCE = join(DASHBOARD, 'src')
const BASELINE = new URL('translations.baseline.json', import.meta.url)

// Props and attributes whose value is shown to a person.
const TEXT_ATTRIBUTES = new Set([
	'alt',
	'any-label',
	'aria-description',
	'aria-label',
	'cancel-label',
	'confirm-label',
	'description',
	'empty-text',
	'help',
	'label',
	'message',
	'placeholder',
	'search-placeholder',
	'subtitle',
	'text',
	'title',
	'title-info',
	'tooltip',
])
// Object keys and parameter names that hold the same kind of text in a script.
const TEXT_KEYS = new Set([
	...[...TEXT_ATTRIBUTES].map(toCamelCase),
	'fallback',
	'heading',
])
// A variable with a name like this holds text for a person.
const TEXT_VARIABLE =
	/(Label|Title|Text|Message|Description|Placeholder|Heading|Tooltip|^label|^title|^message|^description)$/
const FEEDBACK_FUNCTIONS = new Set([
	'backgroundErrorToast',
	'confirm',
	'infoToast',
	'reportError',
	'successToast',
])
const LETTER = /\p{L}/u
// The node types of @vue/compiler-core, which vue/compiler-sfc does not export.
const NodeTypes = { TEXT: 2, INTERPOLATION: 5, ATTRIBUTE: 6, DIRECTIVE: 7 }

function toCamelCase(name) {
	return name.replace(/-(\w)/g, (_match, letter) => letter.toUpperCase())
}

function listSourceFiles(directory) {
	return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
		const path = join(directory, entry.name)
		if (entry.isDirectory())
			return entry.name === 'types' ? [] : listSourceFiles(path)
		return /\.(vue|ts)$/.test(entry.name) && !entry.name.endsWith('.d.ts')
			? [path]
			: []
	})
}

function hasText(node) {
	if (
		typescript.isStringLiteral(node) ||
		typescript.isNoSubstitutionTemplateLiteral(node)
	)
		return LETTER.test(node.text)
	if (typescript.isTemplateExpression(node))
		return [node.head, ...node.templateSpans.map((span) => span.literal)].some(
			(part) => LETTER.test(part.text),
		)
	return false
}

/** The literals an expression can evaluate to, such as both sides of `a ? 'Yes' : 'No'`. */
function getResultLiterals(node) {
	if (!node) return []
	if (hasText(node)) return [node]
	if (
		typescript.isParenthesizedExpression(node) ||
		typescript.isAsExpression(node)
	)
		return getResultLiterals(node.expression)
	if (typescript.isConditionalExpression(node))
		return [
			...getResultLiterals(node.whenTrue),
			...getResultLiterals(node.whenFalse),
		]
	if (typescript.isBinaryExpression(node)) {
		const operator = node.operatorToken.kind
		const SyntaxKind = typescript.SyntaxKind
		if (
			[
				SyntaxKind.BarBarToken,
				SyntaxKind.QuestionQuestionToken,
				SyntaxKind.PlusToken,
			].includes(operator)
		)
			return [...getResultLiterals(node.left), ...getResultLiterals(node.right)]
	}
	if (
		typescript.isArrowFunction(node) ||
		typescript.isFunctionExpression(node)
	) {
		if (!typescript.isBlock(node.body)) return getResultLiterals(node.body)
		return getReturnedLiterals(node.body)
	}
	// computed(() => 'Text')
	if (typescript.isCallExpression(node) && getCallName(node) === 'computed')
		return getResultLiterals(node.arguments[0])
	return []
}

function getReturnedLiterals(block) {
	const literals = []
	const visit = (node) => {
		if (typescript.isFunctionLike(node)) return
		if (typescript.isReturnStatement(node))
			literals.push(...getResultLiterals(node.expression))
		typescript.forEachChild(node, visit)
	}
	typescript.forEachChild(block, visit)
	return literals
}

function getCallName(call) {
	const callee = call.expression
	if (typescript.isIdentifier(callee)) return callee.text
	if (typescript.isPropertyAccessExpression(callee)) {
		const owner = callee.expression
		return typescript.isIdentifier(owner) && owner.text === 'toast'
			? 'toast'
			: callee.name.text
	}
	return null
}

function getName(node) {
	return node &&
		(typescript.isIdentifier(node) || typescript.isStringLiteral(node))
		? node.text
		: null
}

/** The untranslated literals in a script, an event handler, or a bound expression. */
function findScriptLiterals(sourceFile) {
	const literals = []
	const visit = (node) => {
		if (
			typescript.isPropertyAssignment(node) &&
			TEXT_KEYS.has(getName(node.name))
		)
			literals.push(...getResultLiterals(node.initializer))
		if (typescript.isParameter(node) && TEXT_KEYS.has(getName(node.name)))
			literals.push(...getResultLiterals(node.initializer))
		if (
			typescript.isVariableDeclaration(node) &&
			TEXT_VARIABLE.test(getName(node.name) ?? '')
		)
			literals.push(...getResultLiterals(node.initializer))
		if (typescript.isCallExpression(node)) {
			const name = getCallName(node)
			if (name === 'toast' || FEEDBACK_FUNCTIONS.has(name))
				literals.push(...node.arguments.flatMap(getResultLiterals))
		}
		typescript.forEachChild(node, visit)
	}
	visit(sourceFile)
	return literals.map((literal) => ({
		line:
			sourceFile.getLineAndCharacterOfPosition(literal.getStart(sourceFile))
				.line + 1,
		text: literal.getText(sourceFile),
	}))
}

function parseScript(code, firstLine = 1) {
	// Blank lines keep each line number the same as in the .vue file.
	return typescript.createSourceFile(
		'script.ts',
		'\n'.repeat(firstLine - 1) + code,
		typescript.ScriptTarget.Latest,
		true,
	)
}

function findExpressionLiterals(code, line, { isText, isStatement = false }) {
	const sourceFile = parseScript(isStatement ? code : `(${code})`, line)
	const statement = sourceFile.statements[0]
	const literals = findScriptLiterals(sourceFile)
	if (isText && statement && typescript.isExpressionStatement(statement)) {
		const results = getResultLiterals(statement.expression).map((literal) => ({
			line:
				sourceFile.getLineAndCharacterOfPosition(literal.getStart(sourceFile))
					.line + 1,
			text: literal.getText(sourceFile),
		}))
		literals.push(
			...results.filter(
				(result) =>
					!literals.some(
						(found) => found.text === result.text && found.line === result.line,
					),
			),
		)
	}
	return literals
}

function findTemplateLiterals(node, literals = []) {
	if (node.type === NodeTypes.TEXT && LETTER.test(node.content))
		literals.push({ line: node.loc.start.line, text: node.content.trim() })

	if (node.type === NodeTypes.INTERPOLATION)
		literals.push(
			...findExpressionLiterals(
				node.content.content,
				node.content.loc.start.line,
				{ isText: true },
			),
		)

	for (const prop of node.props ?? []) {
		if (prop.type === NodeTypes.ATTRIBUTE) {
			if (
				TEXT_ATTRIBUTES.has(prop.name) &&
				prop.value &&
				LETTER.test(prop.value.content)
			)
				literals.push({
					line: prop.loc.start.line,
					text: `${prop.name}="${prop.value.content}"`,
				})
			continue
		}
		// v-for and v-slot hold a pattern, not an expression.
		if (
			prop.type !== NodeTypes.DIRECTIVE ||
			!prop.exp ||
			['for', 'slot'].includes(prop.name)
		)
			continue
		literals.push(
			...findExpressionLiterals(prop.exp.content, prop.exp.loc.start.line, {
				isText: prop.name === 'bind' && TEXT_ATTRIBUTES.has(prop.arg?.content),
				// An event handler can hold statements, such as `open = true; save()`.
				isStatement: prop.name === 'on',
			}),
		)
	}

	for (const child of node.children ?? []) findTemplateLiterals(child, literals)
	return literals
}

function findUntranslated(code, { isVue }) {
	if (!isVue) return findScriptLiterals(parseScript(code))

	const { descriptor } = parse(code)
	const scripts = [descriptor.script, descriptor.scriptSetup].filter(Boolean)
	return [
		...(descriptor.template
			? findTemplateLiterals(descriptor.template.ast)
			: []),
		...scripts.flatMap((script) =>
			findScriptLiterals(parseScript(script.content, script.loc.start.line)),
		),
	]
}

function getCounts() {
	const counts = {}
	const findings = {}
	for (const path of listSourceFiles(SOURCE).sort()) {
		const found = findUntranslated(readFileSync(path, 'utf8'), {
			isVue: path.endsWith('.vue'),
		})
		if (!found.length) continue
		const name = relative(DASHBOARD, path)
		counts[name] = found.length
		findings[name] = found
	}
	return { counts, findings }
}

test('text a person reads goes through __()', () => {
	const { counts, findings } = getCounts()
	if (process.env.UPDATE_TRANSLATION_BASELINE) {
		writeFileSync(BASELINE, `${JSON.stringify(counts, null, '\t')}\n`)
		return
	}

	const baseline = JSON.parse(readFileSync(BASELINE, 'utf8'))
	const problems = []
	for (const name of new Set([
		...Object.keys(baseline),
		...Object.keys(counts),
	])) {
		const count = counts[name] ?? 0
		const allowed = baseline[name] ?? 0
		if (count > allowed) {
			const lines = findings[name].map(
				(found) => `  ${name}:${found.line}  ${found.text}`,
			)
			problems.push(
				`${name} has ${count} untranslated strings, the baseline allows ${allowed}. Wrap them in __():\n${lines.join('\n')}`,
			)
		}
		if (count < allowed)
			problems.push(
				`${name} has ${count} untranslated strings, fewer than the baseline ${allowed}. Run UPDATE_TRANSLATION_BASELINE=1 node --test dashboard/tests/translations.test.mjs`,
			)
	}
	assert.deepEqual(problems, [], problems.join('\n\n'))
})

test('the scanner finds untranslated text and accepts __()', () => {
	const template = `<template>
		<Button label="Save" :title="isNew ? 'Create' : __('Edit')" @click="reportError('Failed')" />
		<p>Hello</p>
		<p>{{ __('Hello {0}', [name]) }}</p>
		<Dialog :options="{ title: 'Delete server', size: 'sm' }" :label="__('Delete')" />
	</template>
	<script setup lang="ts">
	const emptyMessage = 'No servers yet'
	const status = 'Running'
	successToast(__('Saved'))
	</script>`
	const texts = findUntranslated(template, { isVue: true }).map(
		(found) => found.text,
	)
	assert.deepEqual(
		texts.sort(),
		[
			"'Create'",
			"'Delete server'",
			"'Failed'",
			"'No servers yet'",
			'Hello',
			'label="Save"',
		].sort(),
	)
})

let moduleCount = 0

/** Load translate.ts as the browser does, with `fetch` and `window` as its globals. */
async function importTranslate(fetch, window) {
	const source = readFileSync(
		new URL('../src/lib/translate.ts', import.meta.url),
		'utf8',
	)
	const code = typescript.transpileModule(source, {
		compilerOptions: {
			module: typescript.ModuleKind.ESNext,
			target: typescript.ScriptTarget.ES2022,
		},
	}).outputText
	const original = globalThis.fetch
	Object.assign(globalThis, { fetch, window })
	try {
		// A unique URL, so each test loads its own copy of the module.
		moduleCount += 1
		return await import(
			`data:text/javascript,${encodeURIComponent(`${code}\n// ${moduleCount}`)}`
		)
	} finally {
		globalThis.fetch = original
		delete globalThis.window
	}
}

test('__ finds the translation for the context and fills the placeholders', async () => {
	const translations = {
		'{0} of {1} servers': '{1} में से {0} सर्वर',
		Open: 'खोलें',
		'Open:Status': 'खुला',
	}
	const requested = []
	const fetch = async (url) => {
		requested.push(url)
		return { ok: true, json: async () => ({ message: translations }) }
	}

	const { __ } = await importTranslate(fetch, {
		lang: 'hi',
		translations_version: 'v1',
	})

	assert.deepEqual(requested, [
		'/api/method/frappe.translate.get_boot_translations?v=v1&lang=hi',
	])
	assert.equal(__('{0} of {1} servers', [2, 5]), '5 में से 2 सर्वर')
	assert.equal(__('Open'), 'खोलें')
	assert.equal(__('Open', [], 'Status'), 'खुला')
	assert.equal(__('Close {0}', []), 'Close {0}')
})

test('__ shows English when the catalog does not load', async () => {
	const fetch = async () => ({ ok: false, status: 503 })
	const warn = console.warn
	console.warn = () => {}
	try {
		const { __ } = await importTranslate(fetch, {
			lang: 'hi',
			translations_version: 'v1',
		})

		assert.equal(__('Open'), 'Open')
		assert.equal(__('{0} servers', [3]), '3 servers')
	} finally {
		console.warn = warn
	}
})
