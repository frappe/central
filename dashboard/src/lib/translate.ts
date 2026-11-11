let translations: Record<string, string> = {}

/** Load the catalog of the reader's language once, before the app mounts. The URL carries
 *  the translation version, so the browser keeps the catalog until a translation changes.
 *  A failed load leaves the console in English. */
export async function loadTranslations(): Promise<void> {
	const query = new URLSearchParams({
		v: window.translations_version ?? '',
		lang: window.lang ?? '',
	})
	try {
		const response = await fetch(
			`/api/method/frappe.translate.get_boot_translations?${query}`,
			{ credentials: 'same-origin', signal: AbortSignal.timeout(5000) },
		)
		if (!response.ok) throw new Error(`HTTP ${response.status}`)
		translations = (await response.json()).message ?? {}
	} catch (error) {
		console.warn('Translations did not load. The console shows English.', error)
	}
}

/** The translation of `text` in the reader's language, with `{0}`, `{1}` filled from
 *  `values`, as Frappe's own `__` does. Pass a string literal, so the translation
 *  catalog can extract it: `__('{0} servers', [count])`, not `__(`${count} servers`)`.
 *  `context` tells apart two meanings of the same English text. */
export function __(
	text: string,
	values: readonly unknown[] = [],
	context?: string,
): string {
	const translated =
		(context && translations[`${text}:${context}`]) ||
		translations[text] ||
		text

	return translated.replace(/\{(\d+)\}/g, (placeholder, index: string) => {
		const value = values[Number(index)]
		return value === undefined ? placeholder : String(value)
	})
}

declare module 'vue' {
	interface ComponentCustomProperties {
		__: typeof __
	}
}
