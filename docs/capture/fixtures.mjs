const GIB = 1024 ** 3
const DAY = 86_400

/** Answers for the console reads that need a live region. Each takes the request URL. */
export function atlasFixtures() {
	return {
		'central.api.images.list_images': (url) => ({ items: getImages(url.searchParams.get('offering')), next_offset: null }),
		'central.api.servers.server_metrics': (url) => getMetrics(url.searchParams.get('period') || '1h'),
	}
}

function getImages(offering) {
	const now = Math.floor(Date.now() / 1000)
	if (offering === 'ubuntu') {
		return [
			{ id: 'img-ubuntu-2604', title: 'Ubuntu 26.04 LTS', architecture: 'x86_64', rootfs_size_mib: 4096, created_at: now - 9 * DAY, tags: { os_version: 'Ubuntu 26.04 LTS', has_site: '0' } },
			{ id: 'img-ubuntu-2404', title: 'Ubuntu 24.04 LTS', architecture: 'x86_64', rootfs_size_mib: 4096, created_at: now - 40 * DAY, tags: { os_version: 'Ubuntu 24.04 LTS', has_site: '0' } },
		]
	}
	return [16, 15].flatMap((version) => [
		{ id: `img-frappe-v${version}`, title: `Frappe v${version}`, architecture: 'x86_64', rootfs_size_mib: 12288, created_at: now - 3 * DAY, tags: { frappe_version: `version-${version}`, has_site: '0' } },
		{ id: `img-frappe-v${version}-site`, title: `Frappe v${version} with a site`, architecture: 'x86_64', rootfs_size_mib: 14336, created_at: now - 3 * DAY, tags: { frappe_version: `version-${version}`, has_site: '1' } },
	])
}

const PERIOD_SECONDS = { '1h': 3600, '6h': 6 * 3600, '24h': DAY, '7d': 7 * DAY, '30d': 30 * DAY }

// Smooth, repeatable curves: a daily rhythm plus small deterministic noise.
function getMetrics(period) {
	const span = PERIOD_SECONDS[period] ?? 3600
	const step = Math.max(60, Math.round(span / 120))
	const end = Math.floor(Date.now() / 1000 / step) * step
	const points = []

	for (let time = end - span; time <= end; time += step) {
		const rhythm = Math.sin((time / DAY) * 2 * Math.PI - 1.2)
		const noise = Math.sin(time * 0.0137) * 0.5 + Math.sin(time * 0.0071) * 0.5
		points.push({
			time,
			is_up: true,
			cpu_percent: 24 + rhythm * 12 + noise * 6,
			memory_bytes: (2.6 + rhythm * 0.3 + noise * 0.08) * GIB,
			disk_used_bytes: 31.4 * GIB,
			disk_total_bytes: 100 * GIB,
			disk_read_bytes_per_second: (1.8 + noise) * 1024 ** 2,
			disk_write_bytes_per_second: (0.9 + rhythm * 0.4) * 1024 ** 2,
			received_bytes_per_second: (420 + rhythm * 160 + noise * 60) * 1024,
			sent_bytes_per_second: (180 + rhythm * 70 + noise * 30) * 1024,
		})
	}
	return { available: true, points, sample_interval_seconds: step }
}

const SITE_PATH = /^\/api\/v1\/sites\/([^/]+)$/
const DOMAINS_PATH = /^\/api\/v1\/sites\/([^/]+)\/domains$/
const DNS_RECORDS_PATH = /^\/api\/v1\/sites\/([^/]+)\/domains\/([^/]+)\/dns-records$/

/**
 * Pilot reads that differ on a Frappe Cloud server. Domains need nginx, which runs only in
 * production, and Frappe Cloud's domain provider answers the DNS records.
 */
export const pilotRoutes = [
	{
		// This machine shares one MariaDB and one disk with other benches. A Frappe Cloud server holds only its own.
		matches: (url) => url.pathname === '/api/v1/storage',
		async respond(route) {
			const storage = await (await route.fetch()).json()
			const databases = storage.database.databases.filter((row) => row.site || row.system)
			const coreBytes = 310 * 1024 ** 2
			const databaseBytes = databases.reduce((total, row) => total + row.bytes, 0) + coreBytes
			const database = { ...storage.database, databases, core_bytes: coreBytes, used_bytes: databaseBytes }
			const diskUsed = storage.bench.used_bytes + databaseBytes + 5.6 * GIB
			return route.fulfill({ json: { ...storage, database, disk_total: 100 * GIB, disk_used: diskUsed } })
		},
	},
	{
		// Adding a key here would change this machine's authorized_keys, so the list is shown, not created.
		matches: (url) => url.pathname === '/api/v1/ssh-keys',
		respond: (route) =>
			route.fulfill({
				json: {
					keys: [
						{ fingerprint: 'SHA256:CzDkfALoijQpCXOTyPRlRBZEmsKptsZ8O5lgku11Kmg', type: 'ssh-ed25519', comment: 'zara@contrail-macbook' },
						{ fingerprint: 'SHA256:hYBTzmNPJYU5XShpdu6w3bHrxPXLHyKIcMlMAxoKgU', type: 'ssh-ed25519', comment: 'ci-deploy' },
					],
				},
			}),
	},
	{
		matches: (url) => url.pathname === '/api/v1/sites/wildcard-domains',
		respond: (route) => route.fulfill({ json: { domains: ['.bom.frappe.cloud'] } }),
	},
	{
		matches: (url) => SITE_PATH.test(url.pathname) && !url.pathname.endsWith('/wildcard-domains'),
		async respond(route) {
			const site = await (await route.fetch()).json()
			return route.fulfill({ json: { ...site, nginx_enabled: true } })
		},
	},
	{
		matches: (url) => DOMAINS_PATH.test(url.pathname),
		respond(route, url) {
			const site = decodeURIComponent(url.pathname.match(DOMAINS_PATH)[1])
			const custom = site.replace(/\.bom\.frappe\.cloud$/, '.contrail.example')
			const domains = [
				{ domain: site, is_site: true, is_primary: false, public_scheme: 'https', tls: true },
				{ domain: custom, is_site: false, is_primary: true, public_scheme: 'https', tls: true },
			]
			return route.fulfill({ json: { domains, primary: custom, certificate_email_required: false } })
		},
	},
	{
		matches: (url) => DNS_RECORDS_PATH.test(url.pathname),
		respond(route, url) {
			const domain = decodeURIComponent(url.pathname.match(DNS_RECORDS_PATH)[2])
			const cname = [
				{ type: 'CNAME', host: domain, value: 'proxy.bom.frappe.cloud' },
				{ type: 'TXT', host: `_frappe-verification.${domain}`, value: 'frappe-verification=7c41e9a2d05b' },
			]
			return route.fulfill({ json: { cname } })
		},
	},
]
