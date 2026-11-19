import preset from 'frappe-ui/tailwind'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.dirname(fileURLToPath(import.meta.url))

export default {
	presets: [preset],
	content: [
		path.join(root, 'content/**/*.md'),
		path.join(root, '.vitepress/**/*.{vue,ts}'),
		path.join(root, 'node_modules/frappe-ui/vitepress/**/*.{vue,ts}'),
		path.join(root, 'node_modules/frappe-ui/src/**/*.{vue,ts}'),
	],
}
