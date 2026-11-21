import signingInHtml from '@/assets/signing-in.html?raw'
import { escapeHtml } from '@/components/search/utils'
import { __ } from '@/lib/translate'

const LOADING_MESSAGES = [
	'Filing the flight plan…',
	'Running preflight checks…',
	'Warming up the engines…',
	'Taxiing to the runway…',
	'Waiting for clearance…',
	'Getting ready for takeoff…',
	'Brewing your coffee…',
]

/** Calls that the loading page puts on its window. */
interface LoadingPageControls {
	hold(message: string): void
	takeoff(url: string, title: string, message: string): void
	fail(title: string, message: string): void
}

/** The loading page with its text filled in. Names are user data, so every value is escaped. */
export function getLoadingPageHtml(values: Record<string, string>): string {
	return signingInHtml.replace(/{{ (\w+) }}/g, (_, key: string) =>
		escapeHtml(values[key] ?? ''),
	)
}

/** A tab that shows the runway page while the dashboard gets a sign-in link. */
export class LoadingTab {
	private constructor(
		private readonly tab: Window,
		private readonly pageUrl: string,
		private readonly name: string,
	) {}

	/** Call inside the click, before any await, or the browser blocks the window. */
	static open(
		name: string,
		target = '_blank',
		features = '',
	): LoadingTab | null {
		const html = getLoadingPageHtml({
			title: __('Opening {0}', [name]),
			message:
				LOADING_MESSAGES[Math.floor(Math.random() * LOADING_MESSAGES.length)],
			back: __('Back to dashboard'),
		})
		const pageUrl = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
		const tab = window.open(pageUrl, target, features)
		if (tab) return new LoadingTab(tab, pageUrl, name)

		URL.revokeObjectURL(pageUrl)
		return null
	}

	get isClosed(): boolean {
		return this.tab.closed
	}

	/** Undefined until the page script runs, so every caller has a plain fallback. */
	private get controls(): LoadingPageControls | undefined {
		if (this.tab.closed) return undefined
		return (this.tab as Window & { loadingTab?: LoadingPageControls })
			.loadingTab
	}

	hold(): void {
		this.controls?.hold(__('Holding short. Pilot is starting up.'))
	}

	takeoff(url: string): void {
		const controls = this.controls
		if (!controls) {
			this.tab.location.href = url
			return
		}
		// The page runs from a blob URL, so a relative link must resolve against the dashboard.
		controls.takeoff(
			new URL(url, window.location.href).href,
			__('Cleared for takeoff'),
			__('Opening {0}…', [this.name]),
		)
	}

	/** Keeps the tab open with the reason, so a person who switched to it is not left guessing. */
	fail(title: string, message: string): void {
		const controls = this.controls
		if (controls) controls.fail(title, message)
		else this.tab.close()
	}

	/** The page is already loaded, so the object URL can go once the request settles. */
	dispose(): void {
		URL.revokeObjectURL(this.pageUrl)
	}
}
