import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

class Element {
	constructor(tagName, disabled = false) {
		this.tagName = tagName
		this.disabled = disabled
	}
	closest() {
		return this.tagName === 'BUTTON' ? this : null
	}
	focus() {
		focused = this
	}
}
let focused = null
const source = readFileSync(
	new URL('../src/composables/useMenuKeyboardNavigation.ts', import.meta.url),
	'utf8',
)
const compiled = typescript.transpileModule(source, {
	compilerOptions: { module: typescript.ModuleKind.CommonJS },
}).outputText
const exports = {}
runInNewContext(compiled, { exports, HTMLElement: Element })
const { useMenuKeyboardNavigation } = exports

function menu() {
	focused = null
	const buttons = [
		new Element('BUTTON'),
		new Element('BUTTON', true),
		new Element('BUTTON'),
	]
	let closed = 0
	const { onKeydown } = useMenuKeyboardNavigation(() => {
		closed++
	})
	function press(key, target, modifiers = {}) {
		let prevented = false
		onKeydown({
			key,
			target,
			currentTarget: {
				querySelectorAll: () => buttons.filter((button) => !button.disabled),
			},
			preventDefault: () => {
				prevented = true
			},
			...modifiers,
		})
		return prevented
	}
	return { buttons, press, closed: () => closed }
}

test('arrows wrap through enabled buttons, including entry from search', () => {
	const { buttons, press } = menu()
	const input = new Element('INPUT')
	assert.equal(press('ArrowDown', input), true)
	assert.equal(focused, buttons[0])
	press('ArrowDown', focused)
	assert.equal(focused, buttons[2])
	press('ArrowDown', focused)
	assert.equal(focused, buttons[0])
	press('ArrowUp', focused)
	assert.equal(focused, buttons[2])
	press('ArrowUp', input)
	assert.equal(focused, buttons[2])
})

test('Home and End select boundaries without consuming text-editing or modified keys', () => {
	const { buttons, press } = menu()
	press('End', buttons[0])
	assert.equal(focused, buttons[2])
	press('Home', buttons[2])
	assert.equal(focused, buttons[0])
	for (const tagName of ['INPUT', 'TEXTAREA']) {
		assert.equal(press('Home', new Element(tagName)), false)
		assert.equal(press('End', new Element(tagName)), false)
	}
	assert.equal(press('ArrowDown', buttons[0], { ctrlKey: true }), false)
	assert.equal(press('Tab', buttons[0]), false)
	assert.equal(press('Enter', buttons[0]), false)
})

test('Escape closes the menu and an empty list does not consume arrow keys', () => {
	const state = menu()
	state.press('Escape', state.buttons[0])
	assert.equal(state.closed(), 1)
	const { onKeydown } = useMenuKeyboardNavigation(() => {})
	let prevented = false
	onKeydown({
		key: 'ArrowDown',
		target: new Element('INPUT'),
		currentTarget: { querySelectorAll: () => [] },
		preventDefault: () => {
			prevented = true
		},
	})
	assert.equal(prevented, false)
})
