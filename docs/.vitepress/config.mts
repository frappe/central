import path from 'node:path'
import { fileURLToPath } from 'node:url'
// The pinned release ships its Node entry as TypeScript. A relative import lets Vite bundle it.
import { defineDocsConfig } from '../node_modules/frappe-ui/vitepress/index.node'
import { sidebar } from './sidebar'

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const base = process.env.DOCS_BASE || '/'
// The Frappe Cloud v2 console. The header link to it stays hidden while this is empty.
const consoleUrl = 'https://dashboard.frappe.io'

const config = defineDocsConfig({
	rootDir,
	name: 'Frappe Cloud',
	description: 'Run virtual machines and Frappe sites in the region you choose.',
	logo: '/logo.svg',
	base,
	sidebar,
	head: [['link', { rel: 'icon', type: 'image/svg+xml', href: `${base}logo.svg` }]],
})

config.srcExclude = ['**/README.md']
config.themeConfig!.consoleUrl = consoleUrl
config.markdown!.container = { infoLabel: 'Note', warningLabel: 'Warning' }
config.vite!.plugins!.push({
	name: 'cloud-docs-search-palette',
	enforce: 'pre',
	// The theme's palette has frappe-ui library actions and matches page titles only.
	resolveId(source, importer) {
		const isThemePalette = source === './CommandPalette.vue' && importer?.includes('/vitepress/components/Docs/')
		if (isThemePalette) return path.join(rootDir, '.vitepress/theme/SearchPalette.vue')
	},
})

export default config
