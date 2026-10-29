import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

function loadSupport(helpLinks) {
	const source = readFileSync(
		new URL('../src/composables/useSupport.ts', import.meta.url),
		'utf8',
	)
	const exports = {}
	const opened = []
	runInNewContext(
		typescript.transpileModule(source, {
			compilerOptions: { module: typescript.ModuleKind.CommonJS },
		}).outputText,
		{
			exports,
			URL,
			window: { help_links: helpLinks, open: (url) => opened.push(url) },
		},
	)
	return { support: exports.useSupport(), opened }
}

const ticketUrl = 'https://support.test/help/my-tickets/new'

test('the ticket URL carries the context as its subject and leaves out empty parts', () => {
	const { support } = loadSupport({ support_ticket_url: ticketUrl })

	const url = new URL(
		support.getTicketUrl({ Server: 'acme (vm-1)', Site: null, Region: '' }),
	)

	assert.equal(url.origin + url.pathname, ticketUrl)
	assert.equal(url.searchParams.get('q'), '[Server: acme (vm-1)] ')
	assert.equal(url.searchParams.get('utm_source'), 'central')
})

test('without context the ticket URL has no subject', () => {
	const { support } = loadSupport({ support_ticket_url: ticketUrl })

	assert.equal(new URL(support.getTicketUrl()).searchParams.has('q'), false)
})

test('an unset URL hides Contact support and Share feedback', () => {
	const { support } = loadSupport({
		support_ticket_url: null,
		feedback_url: null,
	})

	assert.equal(support.getTicketUrl({ Server: 'acme' }), null)
	assert.equal(support.getContactSupportOption(), null)
	assert.equal(support.feedbackOption, null)
})

test('Contact support opens the ticket in a new tab', () => {
	const { support, opened } = loadSupport({ support_ticket_url: ticketUrl })

	support.getContactSupportOption({ Site: 'acme.test' }).onClick()

	assert.equal(new URL(opened[0]).searchParams.get('q'), '[Site: acme.test] ')
})
