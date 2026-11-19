const GIB = 1024 ** 3
const MIB = 1024 ** 2
const DAY_MS = 86_400_000
const HOUR_MS = 3_600_000

// The site reads a time without a zone as local time.
const ago = (milliseconds) => new Date(Date.now() - milliseconds).toLocaleString('sv-SE')
const day = (offset) => new Date(Date.now() - offset * DAY_MS).toISOString().slice(0, 10)

const ENDPOINT = 'https://s3.bom.frappe.cloud'
const BUCKETS = [
	{ name: 'bucket-media', label: 'media', days: 96, used: 41.6 * GIB, objects: 18_240, quota: 100 * GIB },
	{ name: 'bucket-backups', label: 'erp-backups', days: 210, used: 128.3 * GIB, objects: 642, quota: null },
	{ name: 'bucket-exports', label: 'report-exports', days: 12, used: 3.2 * GIB, objects: 1_105, quota: null },
]

const FILES = {
	'': {
		folders: ['brand/', 'product-photos/'],
		objects: [
			['menu-autumn-2026.pdf', 4.8 * MIB, 2 * HOUR_MS],
			['roastery-tour.mp4', 312 * MIB, 3 * DAY_MS],
			['store-locations.csv', 86 * 1024, 9 * DAY_MS],
			['wholesale-price-list.xlsx', 1.2 * MIB, 21 * DAY_MS],
		],
	},
}

const GATEWAYS = [
	{ name: 'in', label: 'India', endpoint: 'https://in.llm.frappe.cloud', is_default: true },
	{ name: 'eu', label: 'Europe', endpoint: 'https://eu.llm.frappe.cloud', is_default: false },
]

const model = (provider, providerName, id, title, input, output, dialects, retention = true) => ({
	name: `${provider}/${id}`,
	provider,
	provider_display_name: providerName,
	model_id: id,
	display_name: title,
	zero_data_retention: retention,
	input_modalities: input,
	output_modalities: output,
	dialects,
})

const MODELS = [
	model('frappe', 'Frappe', 'llama-3.3-70b', 'Llama 3.3 70B', ['text'], ['text'], ['openai', 'anthropic']),
	model('frappe', 'Frappe', 'qwen3-embedding', 'Qwen3 Embedding', ['text'], ['embeddings'], ['openai']),
	model('anthropic', 'Anthropic', 'claude-sonnet-4-5', 'Claude Sonnet 4.5', ['text', 'image', 'file'], ['text'], ['openai', 'anthropic']),
	model('openai', 'OpenAI', 'gpt-4o-mini', 'GPT-4o mini', ['text', 'image'], ['text'], ['openai'], false),
	model('openai', 'OpenAI', 'whisper-1', 'Whisper', ['audio'], ['transcription'], ['openai'], false),
]

const LIMITS = [
	{ metric: 'requests', window: '1m', value: 60 },
	{ metric: 'total_tokens', window: '1m', value: 200_000 },
]
const key = (name, title, days, geography, cap, spent) => ({
	name,
	title,
	status: 'active',
	creation: ago(days * DAY_MS),
	masked: `fc-${name.slice(-4)}…${name.slice(0, 4)}`,
	geography: geography.label,
	gateway_url: geography.endpoint,
	cap,
	month_spent: spent,
	limits: LIMITS,
})
const KEYS = [
	key('k7f2a9c1', 'n8n prod', 64, GATEWAYS[0], 40, 21.37),
	key('p3d8e5b2', 'helpdesk assistant', 31, GATEWAYS[0], 25, 9.84),
	key('m1c4f7a6', 'eu research notebook', 8, GATEWAYS[1], 10, 1.12),
]

// One row per day per model: a weekday rhythm, heavier on the first two models.
function getDailyUsage(days) {
	const shares = [0.46, 0.08, 0.31, 0.15]
	const rows = []
	for (let offset = days - 1; offset >= 0; offset--) {
		const weekday = new Date(Date.now() - offset * DAY_MS).getUTCDay()
		const load = (weekday === 0 || weekday === 6 ? 0.45 : 1) * (1 + 0.2 * Math.sin(offset * 1.7))
		shares.forEach((share, index) => {
			const cost = Number((2.9 * load * share).toFixed(2))
			rows.push({ day: day(offset), model: MODELS[index].name, requests: Math.round(1180 * load * share), tokens: Math.round(1_640_000 * load * share), cost })
		})
	}
	return rows
}

function getUsage(url) {
	const days = { 'Last 7 Days': 7, 'Last 30 Days': 30 }[url.searchParams.get('period')] ?? new Date().getUTCDate()
	const daily = getDailyUsage(days)
	const sum = (rows, field) => Number(rows.reduce((total, row) => total + row[field], 0).toFixed(2))
	const models = MODELS.slice(0, 4).map(({ name }) => {
		const rows = daily.filter((row) => row.model === name)
		return { model: name, requests: sum(rows, 'requests'), tokens: sum(rows, 'tokens'), cost: sum(rows, 'cost') }
	})
	const totals = { requests: sum(daily, 'requests'), tokens: sum(daily, 'tokens'), cost: sum(daily, 'cost') }
	return { period: url.searchParams.get('period') || 'This Month', from_date: day(days - 1), to_date: day(0), as_of: ago(12 * 60_000), totals, models, daily }
}

function getAI(url) {
	const usage = getUsage(url)
	const byDay = Object.groupBy(usage.daily, (row) => row.day)
	const daily = Object.entries(byDay).map(([date, rows]) => ({
		day: date,
		requests: rows.reduce((total, row) => total + row.requests, 0),
		tokens: rows.reduce((total, row) => total + row.tokens, 0),
		cost: Number(rows.reduce((total, row) => total + row.cost, 0).toFixed(2)),
	}))
	const spend = { month_spent: usage.totals.cost, capped: 75, committed: 75, spend_limit: 200, max_keys: 10, suspended: false, log_payloads: false }
	return { enabled: true, spend, usage: { ...usage.totals, from_date: usage.from_date, to_date: usage.to_date, as_of: usage.as_of, daily }, geographies: GATEWAYS }
}

const TICKETS = [
	{ name: '48213', subject: '[Server · Slow performance or high load] erp-production is slow after the update', status: 'Open', creation: ago(3 * HOUR_MS), raised_by: 'zara@contrail.example', url: 'https://support.contrail.example/help/my-tickets/48213' },
	{ name: '48177', subject: '[Billing & plans · Invoice or tax question] GST number on the October invoice', status: 'Replied', creation: ago(2 * DAY_MS), raised_by: 'otis@contrail.example', url: null },
	{ name: '48020', subject: '[Site & app · Domain, DNS, or SSL certificate] Certificate for shop.contrail.example', status: 'Paused', creation: ago(6 * DAY_MS), raised_by: 'zara@contrail.example', url: 'https://support.contrail.example/help/my-tickets/48020' },
]

const ARTICLES = [
	{ name: 'slow-site', title: 'Find why a site is slow', excerpt: 'Check the usage charts of the server, then the slow queries in Pilot.', category: 'Servers', url: 'https://support.contrail.example/kb/slow-site' },
	{ name: 'resize', title: 'Resize a server', excerpt: 'Move a server to a plan with more CPU and memory.', category: 'Servers', url: 'https://support.contrail.example/kb/resize' },
]

const REPOSITORIES = [
	{ repository_id: 9101, full_name: 'contrail-coffee/roastery', private: true, is_admin: true },
	{ repository_id: 9102, full_name: 'contrail-coffee/loyalty', private: true, is_admin: true },
	{ repository_id: 9103, full_name: 'contrail-coffee/pos-theme', private: true, is_admin: true },
	{ repository_id: 9104, full_name: 'contrail-coffee/data-pipeline', private: true, is_admin: false },
]

/** Answers for the console reads that come from Cargo, Grove, Helpdesk, and GitHub. Each takes the request URL. */
export function serviceFixtures() {
	const bucket = (url) => BUCKETS.find((row) => row.name === url.searchParams.get('name'))
	return {
		'central.services.api.storage.get_object_storage': () => ({
			regions: [{ region: 'bom', display_name: 'Mumbai, India', provider: 'Frappe', country_code: 'IN', latitude: 19.0896, longitude: 72.8656 }],
			buckets: BUCKETS.map((row) => ({ name: row.name, bucket_name: `52-bom-${row.label}`, region: 'bom', status: 'Active', endpoint_url: ENDPOINT, access_key: 'FC7Q2M9XK4T1B8ZD', creation: ago(row.days * DAY_MS) })),
		}),
		'central.services.api.storage.get_bucket_usage': (url) => {
			const row = bucket(url)
			return { used_bytes: row.used, object_count: row.objects, quota_bytes: row.quota, quota_objects: null }
		},
		'central.services.api.storage.list_objects': (url) => {
			const prefix = url.searchParams.get('prefix') || ''
			const { folders, objects } = FILES[prefix] ?? { folders: [], objects: [] }
			return { folders, objects: objects.map(([name, size, age]) => ({ key: `${prefix}${name}`, size_bytes: Math.round(size), last_modified: ago(age), etag: '' })), next_offset: null }
		},
		'central.services.api.ai.get_ai': getAI,
		'central.services.api.ai.list_api_keys': () => KEYS,
		'central.services.api.ai.get_usage': getUsage,
		'central.services.api.ai.get_models': () => MODELS,
		'central.api.support.list_tickets': () => TICKETS,
		'central.api.support.find_related': () => ({ articles: ARTICLES, tickets: TICKETS.slice(0, 1) }),
		'central.api.integrations.github.get_connection_attempt': () => ({
			is_expired: false,
			return_url: 'https://erp.bom.frappe.cloud/admin/settings',
			server: 'erp-production',
			team: 'Contrail Coffee',
			is_authorized: true,
			authorize_url: 'https://github.com/login/oauth/authorize',
			install_url: 'https://github.com/apps/frappe-cloud/installations/new',
			installations: [{ installation_id: 7001, account: 'contrail-coffee', account_type: 'Organization', avatar_url: '' }],
			granted_repository_ids: [],
		}),
		'central.api.integrations.github.get_installation_repositories': () => REPOSITORIES,
	}
}
