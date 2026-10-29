import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import test from 'node:test'
import { runInNewContext } from 'node:vm'
import { compileScript, parse } from '@vue/compiler-sfc'
import typescript from 'typescript'
import { createRenderer, defineComponent, h, nextTick, ref } from 'vue'

const require = createRequire(import.meta.url)

function loadSource(path, dependencies = {}) {
	const source = readFileSync(new URL(path, import.meta.url), 'utf8')
	const code = path.endsWith('.vue')
		? compileScript(parse(source).descriptor, {
				id: path,
				inlineTemplate: true,
			}).content
		: source
	const exports = {}
	const compiled = typescript.transpileModule(code, {
		compilerOptions: { module: typescript.ModuleKind.CommonJS },
	}).outputText
	runInNewContext(compiled, {
		exports,
		require: (name) => dependencies[name] ?? require(name),
	})
	return exports
}

// Run real Vue templates and event handlers without a browser or network requests.
const renderer = createRenderer({
	createElement: (name) => ({ name, props: {}, children: [], parent: null }),
	createText: (text) => ({ name: '#text', text, children: [], parent: null }),
	createComment: (text) => ({
		name: '#comment',
		text,
		children: [],
		parent: null,
	}),
	patchProp: (node, key, _previous, value) => {
		node.props[key] = value
	},
	setText: (node, text) => {
		node.text = text
	},
	setElementText: (node, text) => {
		node.children = []
		node.text = text
	},
	insert(node, parent, anchor = null) {
		if (node.parent)
			node.parent.children.splice(node.parent.children.indexOf(node), 1)
		const index = anchor ? parent.children.indexOf(anchor) : -1
		parent.children.splice(index < 0 ? parent.children.length : index, 0, node)
		node.parent = parent
	},
	remove(node) {
		node.parent.children.splice(node.parent.children.indexOf(node), 1)
	},
	parentNode: (node) => node.parent,
	nextSibling: (node) =>
		node.parent?.children[node.parent.children.indexOf(node) + 1] ?? null,
})

function stub(name) {
	return defineComponent({
		inheritAttrs: false,
		setup:
			(_props, { attrs, slots }) =>
			() => {
				if (name === 'Dialog' && (attrs.open ?? attrs.modelValue) === false)
					return null
				return h(name, attrs, [
					...(slots.default?.() ?? []),
					...(slots.footer?.() ?? []),
					...(slots.actions?.() ?? []),
				])
			},
	})
}
const ui = Object.fromEntries(
	[
		'Alert',
		'Button',
		'Checkbox',
		'Dialog',
		'LoadingText',
		'TextInput',
		'Select',
		'Badge',
		'Tooltip',
	].map((name) => [name, stub(name)]),
)

function mount(component, props) {
	const root = { children: [] }
	const app = renderer.createApp({ setup: () => () => h(component, props()) })
	app.mount(root)
	function find(name, match = () => true, node = root) {
		if (node.name === name && match(node.props)) return node
		for (const child of node.children) {
			const found = find(name, match, child)
			if (found) return found
		}
		return null
	}
	function text(node = root) {
		return [node.text ?? '', ...node.children.map(text)].join(' ')
	}
	return { find, text, unmount: () => app.unmount() }
}

const InviteRows = loadSource('../src/components/team/InviteRows.vue', {
	'frappe-ui': ui,
	'@/composables/useBulkInvite': { ALL_RESOURCES: '*', MAX_INVITATIONS: 20 },
}).default

test('the only invitation row cannot be removed, and removing added rows preserves its input', async () => {
	const rows = ref([
		{
			email: 'member@example.com',
			role: 'Developer',
			resource: '*',
			error: '',
		},
	])
	const control = mount(InviteRows, () => ({
		rows: rows.value,
		defaultRole: 'Developer',
		roleOptions: [],
		'onUpdate:rows': (value) => {
			rows.value = value
		},
	}))
	assert.equal(
		control.find('Button', (props) =>
			props['aria-label']?.startsWith('Remove'),
		),
		null,
	)
	control
		.find('Button', (props) => props.label === 'Add another')
		.props.onClick()
	await nextTick()
	assert.equal(rows.value.length, 2)
	control
		.find('Button', (props) => props['aria-label'] === 'Remove row 2')
		.props.onClick()
	await nextTick()
	assert.equal(rows.value.length, 1)
	assert.equal(rows.value[0].email, 'member@example.com')
	assert.equal(
		control.find('Button', (props) =>
			props['aria-label']?.startsWith('Remove'),
		),
		null,
	)
	control.unmount()
})

const capabilities = loadSource('../src/lib/capabilities.ts', {
	'@/lib/format': {
		capitalise: (value) => value.charAt(0).toUpperCase() + value.slice(1),
	},
})

test('permission loading, empty, retry, and saving states stay inside the role dialog', async () => {
	const state = {
		capabilities: ref([]),
		capabilitiesLoading: ref(true),
		capabilitiesError: ref(''),
		creating: ref(false),
	}
	let retries = 0
	let creates = 0
	const RoleBuilder = loadSource(
		'../src/components/team/RoleBuilderDialog.vue',
		{
			'frappe-ui': ui,
			'@/lib/capabilities': capabilities,
			'@/lib/feedback': { getErrorMessage: (error) => String(error) },
			'@/composables/useTeamRoles': {
				useTeamRoles: () => ({
					...state,
					reloadCapabilities: () => {
						retries++
						state.capabilitiesError.value = ''
						state.capabilities.value = [
							{ name: 'server:view', description: 'View servers' },
						]
					},
					createRole: async () => {
						creates++
					},
				}),
			},
		},
	).default
	const control = mount(RoleBuilder, () => ({ open: true }))
	assert.ok(control.find('LoadingText'))
	state.capabilitiesLoading.value = false
	await nextTick()
	assert.match(control.text(), /No permissions are available/)
	state.capabilitiesError.value = 'Could not load permissions.'
	await nextTick()
	assert.equal(control.find('Alert').props.title, 'Could not load permissions.')
	control.find('Button', (props) => props.label === 'Retry').props.onClick()
	await nextTick()
	assert.equal(retries, 1)
	assert.equal(control.find('Alert'), null)
	control.find('TextInput').props['onUpdate:modelValue']('Server viewer')
	control.find('Checkbox').props['onUpdate:modelValue'](true)
	await nextTick()
	assert.equal(control.find('Dialog').props.actions[0].disabled, false)
	state.creating.value = true
	await nextTick()
	const dialog = control.find('Dialog').props
	assert.equal(dialog.dismissible, false)
	assert.equal(dialog.actions[0].disabled, true)
	assert.equal(dialog.actions[0].loading, true)
	await dialog.actions[0].onClick()
	assert.equal(creates, 0)
	assert.equal(control.find('TextInput').props.disabled, true)
	control.unmount()
})

test('snapshot errors open with their full details and close without a mutation', async () => {
	const snapshots = [
		{
			name: 'snapshot-failed',
			status: 'Failed',
			error_detail: 'Snapshot transfer failed. Retry the snapshot.',
			is_billed: false,
		},
	]
	const ListView = defineComponent({
		inheritAttrs: false,
		setup:
			(_props, { attrs, slots }) =>
			() =>
				h(
					'ListView',
					{},
					attrs.rows.map((row) => slots.status({ row })),
				),
	})
	const SnapshotList = loadSource(
		'../src/components/snapshots/SnapshotListView.vue',
		{
			'frappe-ui': ui,
			'@/components/common/list-view': {
				ListView,
				createListViewQuery: () => ({}),
			},
			'@/components/common/RowActionsMenu.vue': {
				default: stub('RowActionsMenu'),
			},
			'@/lib/capabilities': capabilities,
			'@/lib/format': {
				formatDate: (value) => value,
				money: (value) => String(value),
			},
			'@/lib/snapshots': {
				SNAPSHOT_STATUS_THEME: { Failed: 'red' },
				SNAPSHOT_TYPE_LABEL: {},
				snapshotCostLabel: () => 'Free',
			},
		},
	).default
	const control = mount(SnapshotList, () => ({
		snapshots,
		loading: false,
		error: '',
		currency: 'USD',
		canManage: false,
		canRestore: false,
		freePerServer: 1,
	}))
	assert.equal(control.find('Dialog'), null)
	const button = control.find(
		'Button',
		(props) => props.tooltip === 'View snapshot error',
	)
	assert.equal(button.props.theme, 'red')
	button.props.onClick({ stopPropagation() {} })
	await nextTick()
	assert.equal(control.find('Dialog').props.title, 'Snapshot error')
	assert.match(control.text(), /Snapshot transfer failed. Retry the snapshot./)
	control.find('Dialog').props['onUpdate:open'](false)
	await nextTick()
	assert.equal(control.find('Dialog'), null)
	assert.equal(snapshots[0].status, 'Failed')
	control.unmount()
})

test('invitation dismissal has no extra close button and is blocked while sending', async () => {
	const saving = ref(false)
	const InviteDialog = loadSource(
		'../src/components/team/InviteMemberDialog.vue',
		{
			'frappe-ui': {
				...ui,
				useCall: () => ({ data: { servers: [], sites: [] }, reload() {} }),
			},
			'@/api/methods': {
				API: { registry: 'registry' },
				method: (value) => value,
			},
			'@/components/team/InviteRows.vue': InviteRows,
			'@/composables/useTeamScope': {
				teamParams: () => ({ team: 'test-team' }),
			},
			'@/composables/useRegions': { useRegions: () => ({ regions: ref([]) }) },
			'@/composables/useBulkInvite': {
				ALL_RESOURCES: '*',
				useBulkInvite: () => ({
					rows: ref([
						{ email: '', role: 'Developer', resource: '*', error: '' },
					]),
					roleOptions: ref([]),
					defaultRole: ref('Developer'),
					rolesLoading: ref(false),
					rolesError: ref(''),
					canSubmit: ref(false),
					submitLabel: ref('Send invitations'),
					saving,
					requestError: ref(''),
					reset() {},
					submit: async () => ({ sent: 0, failed: 0 }),
				}),
			},
		},
	).default
	const control = mount(InviteDialog, () => ({ open: true }))
	assert.equal(control.find('Dialog').props['show-close-button'], false)
	assert.equal(control.find('Dialog').props.dismissible, true)
	saving.value = true
	await nextTick()
	assert.equal(control.find('Dialog').props.dismissible, false)
	assert.equal(
		control.find('Button', (props) => props.label === 'Cancel').props.disabled,
		true,
	)
	control.unmount()
})

test('chart summary controls hide and restore one series while keeping a visible series', async () => {
	const metrics = loadSource('../src/lib/serverMetrics.ts')
	const ServerMetricChart = loadSource(
		'../src/components/servers/detail/ServerMetricChart.vue',
		{
			'frappe-ui': ui,
			'frappe-ui/charts': {
				AreaChart: stub('AreaChart'),
				ChartCard: stub('ChartCard'),
				useChartTokens: () => ({
					tokens: ref({ categorical: Array(9).fill('#123456') }),
				}),
			},
			'@/lib/serverMetrics': metrics,
		},
	).default
	const chart = metrics.getMetricCharts(
		[{ time: 1, received_bytes_per_second: 2048, sent_bytes_per_second: 512 }],
		1,
	)[2]
	const control = mount(ServerMetricChart, () => ({
		chart,
		timeGrain: 'minute',
		averageLabel: 'Average over 1 hour',
	}))
	assert.equal(
		control.find('Tooltip', (props) => props.text === 'Average over 1 hour')
			.props.disabled,
		false,
	)
	const hideReceived = control.find(
		'Button',
		(props) => props['aria-label'] === 'Hide Received',
	)
	assert.equal(hideReceived.props['aria-pressed'], true)
	hideReceived.props.onClick()
	await nextTick()
	assert.equal(
		control.find('Button', (props) => props['aria-label'] === 'Show Received')
			.props['aria-pressed'],
		false,
	)
	assert.equal(
		control.find('Button', (props) => props['aria-label'] === 'Hide Sent').props
			.disabled,
		true,
	)
	assert.deepEqual(
		Array.from(control.find('AreaChart').props['hidden-series']),
		['Received'],
	)
	control
		.find('Button', (props) => props['aria-label'] === 'Show Received')
		.props.onClick()
	await nextTick()
	assert.equal(
		control.find('Button', (props) => props['aria-label'] === 'Hide Sent').props
			.disabled,
		false,
	)
	assert.equal(control.find('AreaChart').props['hidden-series'].length, 0)
	assert.match(control.text(), /2 KB\/s/)
	assert.match(control.text(), /512 B\/s/)
	control.unmount()
})
