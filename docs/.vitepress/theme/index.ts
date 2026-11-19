import { theme } from 'frappe-ui/vitepress'
import type { Theme } from 'vitepress'
import DocsLayout from './DocsLayout.vue'
import NotFound from './NotFound.vue'
import Screenshot from './Screenshot.vue'
import Clip from './Clip.vue'
import Cards from './Cards.vue'
import Card from './Card.vue'
import Airport from './Airport.vue'
import ArchitectureDiagram from './ArchitectureDiagram.vue'
import './custom.css'

export default {
	extends: theme,
	Layout: DocsLayout,
	NotFound,
	enhanceApp({ app }) {
		app.component('Screenshot', Screenshot)
		app.component('Clip', Clip)
		app.component('Cards', Cards)
		app.component('Card', Card)
		app.component('Airport', Airport)
		app.component('ArchitectureDiagram', ArchitectureDiagram)
	},
} satisfies Theme
