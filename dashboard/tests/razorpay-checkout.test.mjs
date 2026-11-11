import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const source = readFileSync(
	new URL('../src/lib/gateway.ts', import.meta.url),
	'utf8',
)

const sheet = {}
const window = {
	Razorpay: class {
		constructor(options) {
			sheet.options = options
		}
		on(event, handler) {
			if (event === 'payment.failed') sheet.onFailed = handler
		}
		open() {}
	},
}
const exports = {}
runInNewContext(
	typescript.transpileModule(source, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText,
	{
		exports,
		window,
		// The checkout script is already on the page, so loadScript resolves.
		document: { querySelector: () => ({}) },
	},
)
const { openRazorpayCheckout } = exports

// Open the sheet and let loadScript settle, so the options and handler exist.
async function openSheet() {
	const result = openRazorpayCheckout({ adapter_key: 'Razorpay' })
	result.catch(() => {})
	await new Promise((resolve) => setImmediate(resolve))
	// Wrapped: an async function that returns a promise would wait for it to settle.
	return { result }
}

test('a plain close rejects as cancelled', async () => {
	const { result } = await openSheet()
	sheet.options.modal.ondismiss()
	await assert.rejects(result, { message: 'cancelled' })
})

test('a close after a failed payment rejects with the gateway reason', async () => {
	const { result } = await openSheet()
	sheet.onFailed({ error: { description: 'Card declined by bank' } })
	sheet.options.modal.ondismiss()
	await assert.rejects(result, { message: 'Card declined by bank' })
})

test('a close after a failed payment with no reason rejects with the fallback', async () => {
	const { result } = await openSheet()
	sheet.onFailed({})
	sheet.options.modal.ondismiss()
	await assert.rejects(result, {
		message:
			"The payment didn't go through. Try again, or choose another payment method.",
	})
})

test('a retry that succeeds after a failure resolves with the handles', async () => {
	const { result } = await openSheet()
	sheet.onFailed({ error: { description: 'Card declined by bank' } })
	sheet.options.handler({
		razorpay_order_id: 'order_1',
		razorpay_payment_id: 'pay_1',
		razorpay_signature: 'sig_1',
	})
	// The spread copies the object out of the vm realm, so the prototype check passes.
	assert.deepEqual(
		{ ...(await result) },
		{
			razorpay_order_id: 'order_1',
			razorpay_payment_id: 'pay_1',
			razorpay_signature: 'sig_1',
		},
	)
})
