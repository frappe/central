import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import typescript from 'typescript'

const require = createRequire(import.meta.url)
const source = readFileSync(
	new URL('../src/composables/useSession.ts', import.meta.url),
	'utf8',
)
const compiled = typescript.transpileModule(source, {
	compilerOptions: { module: typescript.ModuleKind.CommonJS },
}).outputText
const storageKey = 'central.console.activeTeam'

function startSession(
	pathname,
	storage,
	storageBlocked = false,
	{ search = '', tabStorage = new Map(), extraTeams = [], teams } = {},
) {
	const navigations = []
	const rosterReads = []
	const rosterParams = []
	const addresses = []
	const exports = {}
	const roster = teams ?? [
		{ name: 'team-a', label: 'Acme', status: 'Active' },
		{ name: 'team-b', label: 'Pied Piper', status: 'Active' },
		...extraTeams,
	]
	const localStorage = {
		getItem: (key) => storage.get(key) ?? null,
		setItem(key, value) {
			if (storageBlocked) throw new Error('Storage blocked')
			storage.set(key, value)
		},
		removeItem: (key) => storage.delete(key),
	}
	const dependencies = {
		vue: require('vue'),
		'@/api/methods': { API: { myTeams: 'my_teams' }, method: (value) => value },
		'frappe-ui': {
			useCall(options) {
				rosterParams.push(options.params())
				options.onSuccess(roster)
				return {
					data: roster,
					promise: Promise.resolve(),
					reload: async () => rosterReads.push('my_teams'),
				}
			},
		},
	}
	runInNewContext(compiled, {
		exports,
		require: (name) => dependencies[name],
		localStorage,
		sessionStorage: {
			getItem: (key) => tabStorage.get(key) ?? null,
			setItem: (key, value) => tabStorage.set(key, value),
			removeItem: (key) => tabStorage.delete(key),
		},
		URL,
		window: {
			location: {
				pathname,
				href: `https://cloud.example${pathname}${search}`,
				reload: () => navigations.push('reload'),
				replace: (path) => navigations.push(path),
				assign: (path) => navigations.push(path),
			},
			history: {
				state: null,
				replaceState: (_state, _title, url) => addresses.push(String(url)),
			},
		},
	})
	return {
		session: exports.useSession(),
		navigations,
		rosterReads,
		rosterParams,
		addresses,
	}
}

test('switching preserves a section and boots with the new team before reads start', () => {
	for (const path of [
		'/dashboard/llm',
		'/dashboard/billing/invoices',
		'/dashboard/team/members',
		'/dashboard/servers/snapshots',
	]) {
		const storage = new Map([[storageKey, 'team-a']])
		const { session, navigations } = startSession(path, storage)
		session.setActiveTeam('team-b')
		assert.deepEqual(navigations, ['reload'])
		assert.equal(storage.get(storageKey), 'team-b')
		// The departing document never pairs team B's identity with team A's data.
		assert.equal(session.activeTeam.value, 'team-a')
		const nextDocument = startSession(path, storage)
		assert.equal(nextDocument.session.activeTeam.value, 'team-b')
		assert.equal(nextDocument.session.activeTeamLabel.value, 'Pied Piper')
	}
})

test('resource pages return to their section when the selected team changes', () => {
	for (const [path, destination] of [
		['/dashboard/servers/vm-a/access', '/dashboard/servers'],
		['/dashboard/servers/new', '/dashboard/servers'],
		['/dashboard/object-storage/bucket-a', '/dashboard/object-storage'],
	]) {
		const storage = new Map([[storageKey, 'team-a']])
		const { session, navigations } = startSession(path, storage)
		session.setActiveTeam('team-b')
		assert.deepEqual(navigations, [destination])
	}
})

test('a storage failure keeps the existing team and prevents navigation', () => {
	const storage = new Map([[storageKey, 'team-a']])
	const { session, navigations } = startSession('/dashboard/llm', storage, true)
	assert.throws(
		() => session.setActiveTeam('team-b'),
		/Could not save the selected team/,
	)
	assert.equal(session.activeTeam.value, 'team-a')
	assert.equal(storage.get(storageKey), 'team-a')
	assert.deepEqual(navigations, [])
})

test('a team the caller just created is selected without leaving the page', async () => {
	const storage = new Map()
	const { session, navigations, rosterReads } = startSession(
		'/dashboard/onboarding/site',
		storage,
	)

	await session.adoptNewTeam('team-b')

	assert.equal(session.activeTeam.value, 'team-b')
	assert.equal(storage.get(storageKey), 'team-b')
	assert.deepEqual(rosterReads, ['my_teams'])
	assert.deepEqual(navigations, [])
})

test('an operator opened from Desk sees the impersonated team for this tab only', () => {
	const storage = new Map([[storageKey, 'team-a']])
	const tabStorage = new Map()
	const { session, rosterParams, addresses } = startSession(
		'/dashboard/servers',
		storage,
		false,
		{
			search: '?view_as=team-c',
			tabStorage,
			extraTeams: [
				{
					name: 'team-c',
					label: 'Customer',
					status: 'Active',
					is_impersonated: true,
				},
			],
		},
	)

	assert.equal(rosterParams[0].view_as, 'team-c')
	assert.equal(session.activeTeam.value, 'team-c')
	assert.equal(session.impersonatedTeam.value?.label, 'Customer')
	// The address loses view_as, and the operator's own stored team stays as it was.
	assert.deepEqual(addresses, ['https://cloud.example/dashboard/servers'])
	assert.equal(storage.get(storageKey), 'team-a')
	assert.equal(tabStorage.get('central.console.viewAs'), 'team-c')
})

test('switching to another team ends the impersonation', () => {
	const tabStorage = new Map([['central.console.viewAs', 'team-c']])
	const { session } = startSession('/dashboard/llm', new Map(), false, {
		tabStorage,
		extraTeams: [
			{
				name: 'team-c',
				label: 'Customer',
				status: 'Active',
				is_impersonated: true,
			},
		],
	})

	session.setActiveTeam('team-a')

	assert.equal(tabStorage.has('central.console.viewAs'), false)
})

test('a suspended team is listed but an active team is selected first', () => {
	const storage = new Map()
	const { session } = startSession('/dashboard/servers', storage, false, {
		teams: [
			{ name: 'team-a', label: 'Acme', status: 'Suspended' },
			{ name: 'team-b', label: 'Pied Piper', status: 'Active' },
		],
	})

	assert.equal(session.activeTeam.value, 'team-b')
	assert.equal(session.isActiveTeamSuspended.value, false)
	assert.equal(session.teams.value.length, 2)
})
