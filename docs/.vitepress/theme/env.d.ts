declare module '*.vue' {
	import type { DefineComponent } from 'vue'
	const component: DefineComponent
	export default component
}
declare module '@localSearchIndex' {
	const index: Record<string, () => Promise<{ default: string }>>
	export default index
}
