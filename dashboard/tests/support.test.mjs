import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

// The composable holds the dialog state in `ref`s, so the sandbox needs the one
// piece of Vue it imports. Everything else is a plain function.
const vue = { ref: (value) => ({ value }) }

function loadSupport(helpLinks, user = 'member@test') {
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
			require: (name) => (name === 'vue' ? vue : undefined),
			window: { help_links: helpLinks, user, open: (url) => opened.push(url) },
		},
	)
	return { exports, support: exports.useSupport(), opened }
}

function transpile(relativePath, sandbox) {
	const source = readFileSync(new URL(relativePath, import.meta.url), 'utf8')
	const exports = {}
	runInNewContext(
		typescript.transpileModule(source, {
			compilerOptions: { module: typescript.ModuleKind.CommonJS },
		}).outputText,
		{ ...sandbox, exports },
	)
	return exports
}

function loadSupportAnswers() {
	const search = transpile('../src/components/search/utils.ts', {
		require: () => undefined,
	})

	return transpile('../src/composables/useSupportAnswers.ts', {
		require: (name) => {
			if (name === 'vue')
				return {
					ref: (value) => ({ value }),
					computed: (fn) => ({
						get value() {
							return fn()
						},
					}),
				}
			if (name === 'frappe-ui')
				return { useCall: () => ({ reload: async () => null }) }
			if (name === '@/components/search/utils') return search
			if (name === '@/composables/useSupport') return {}
			return { API: {}, method: () => '' }
		},
	})
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
	assert.equal(support.hasSupport, false)
})

test('Contact support opens the ticket in a new tab', () => {
	const { support, opened } = loadSupport({ support_ticket_url: ticketUrl })

	support.getContactSupportOption({ Site: 'acme.test' }).onClick()

	assert.equal(new URL(opened[0]).searchParams.get('q'), '[Site: acme.test] ')
})

test('in-app tickets open the dialog with the context and tab prefilled', () => {
	const { exports, support, opened } = loadSupport({ in_app_tickets: true })

	support.getContactSupportOption({ Server: 'acme (vm-1)' }).onClick()

	assert.equal(exports.supportDialogOpen.value, true)
	assert.equal(exports.supportDialogTab.value, 'new')
	assert.deepEqual(
		{ ...exports.supportDialogContext.value },
		{ Server: 'acme (vm-1)' },
	)
	assert.deepEqual(opened, [])

	support.openSupport({ Site: 'acme.test' }, 'open')
	assert.equal(exports.supportDialogOpen.value, true)
	assert.equal(exports.supportDialogTab.value, 'open')
	assert.deepEqual(
		{ ...exports.supportDialogContext.value },
		{ Site: 'acme.test' },
	)
})

test('a guest keeps the external URL even when in-app tickets are configured', () => {
	const { support, opened } = loadSupport(
		{ in_app_tickets: true, support_ticket_url: ticketUrl },
		'Guest',
	)

	assert.equal(support.canUseInAppTickets, false)
	support.openSupport({ Page: 'Sign in' })

	assert.equal(new URL(opened[0]).searchParams.get('q'), '[Page: Sign in] ')
})

test('the category is resolved from the place the user asked for help', () => {
	const { exports } = loadSupport({ in_app_tickets: true })

	assert.equal(exports.getSupportCategory({ Server: 'acme (vm-1)' }), 'server')
	assert.equal(exports.getSupportCategory({ Site: 'acme.test' }), 'site')
	assert.equal(
		exports.getSupportCategory({ Topic: 'Object storage or LLM service' }),
		'account',
	)
	assert.equal(
		exports.getSupportCategory({ Topic: 'spending limit' }),
		'billing',
	)
	assert.equal(exports.getSupportCategory({}), null)
})

test('category details cover every category the backend can send', () => {
	const { exports } = loadSupport({ in_app_tickets: true })

	assert.deepEqual(Object.keys(exports.SUPPORT_CATEGORY_DETAILS), [
		'server',
		'site',
		'billing',
		'account',
	])
	for (const details of Object.values(exports.SUPPORT_CATEGORY_DETAILS)) {
		assert.ok(details.icon)
		assert.ok(details.description)
	}
})

test('contact support needs at least 3 characters and a settled search', () => {
	const { canContactSupport } = loadSupportAnswers()

	assert.equal(canContactSupport({ query: '', isLoading: false }), false)
	assert.equal(canContactSupport({ query: 'ab', isLoading: false }), false)
	assert.equal(canContactSupport({ query: '  ab  ', isLoading: false }), false)
	assert.equal(canContactSupport({ query: 'ssh', isLoading: true }), false)
	assert.equal(canContactSupport({ query: 'ssh', isLoading: false }), true)
	assert.equal(
		canContactSupport({ query: 'server down', isLoading: false }),
		true,
	)
})

test('matching answers make the user dismiss them before contacting support', () => {
	const { contactAction } = loadSupportAnswers()

	assert.equal(
		contactAction({ query: 'ab', isLoading: false, hasResults: false }),
		'disabled',
	)
	assert.equal(
		contactAction({ query: 'ssh', isLoading: true, hasResults: true }),
		'disabled',
	)
	assert.equal(
		contactAction({ query: 'ssh', isLoading: false, hasResults: true }),
		'dismiss',
	)
	assert.equal(
		contactAction({ query: 'ssh', isLoading: false, hasResults: false }),
		'contact',
	)
})

test('the outage issue matches the context', () => {
	const { getOutageIssue } = loadSupportAnswers()

	assert.deepEqual(
		{ ...getOutageIssue({ Server: 'acme (vm-1)' }) },
		{ category: 'server', issue: 'Unreachable or down' },
	)
	assert.deepEqual(
		{ ...getOutageIssue({ server: { resource_id: 'vm-1' } }) },
		{ category: 'server', issue: 'Unreachable or down' },
	)
	assert.deepEqual(
		{ ...getOutageIssue({ Site: 'acme.test' }) },
		{ category: 'site', issue: 'Site setup or provisioning failed' },
	)
	assert.deepEqual(
		{ ...getOutageIssue({}) },
		{ category: 'server', issue: 'Unreachable or down' },
	)
})

test('highlight marks every query word of 3 characters or more', () => {
	const { highlightWords } = loadSupportAnswers()

	assert.equal(
		highlightWords('Server down after a resize', 'server RESIZE'),
		'<mark>Server</mark> down after a <mark>resize</mark>',
	)
	assert.equal(highlightWords('Server down', 'do'), 'Server down')
	assert.equal(
		highlightWords('Run bench migrate', 'bench  run'),
		'<mark>Run</mark> <mark>bench</mark> migrate',
	)
})

test('highlight escapes the text and the query before adding markup', () => {
	const { highlightWords } = loadSupportAnswers()

	assert.equal(
		highlightWords('<script>alert(1)</script>', 'alert'),
		'&lt;script&gt;<mark>alert</mark>(1)&lt;/script&gt;',
	)
	assert.equal(highlightWords('a < b', '<'), 'a &lt; b')
	assert.equal(
		highlightWords('cost is $50 (approx)', '$50'),
		'cost is <mark>$50</mark> (approx)',
	)
})

test('a server passed along names the ticket place and stays out of the subject', () => {
	const { exports } = loadSupport({ in_app_tickets: true })
	const server = {
		name: 'web-prod-01',
		resource_id: 'web-prod-01',
		title: 'Production Web',
		region: 'ap-south-1',
		plan: 'plan-4vcpu',
		status: 'Running',
	}

	assert.deepEqual({ ...exports.getSupportServer({ server }) }, server)
	assert.equal(exports.getSupportCategory({ server }), 'server')

	const subject = exports.getTicketSubject({
		Site: 'acme-hr.blr1.frappe.dev',
		server,
	})
	assert.equal(
		subject,
		'[Server: Production Web (web-prod-01) · Site: acme-hr.blr1.frappe.dev] ',
	)
	assert.equal(
		exports.getTicketSubject({ server: { resource_id: 'vm-2' } }),
		'[Server: vm-2] ',
	)
})
