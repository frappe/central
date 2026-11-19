let translations: Record<string, string> = {}

/** The catalog of the reader's language. The URL carries the translation version, so the
 *  browser keeps the catalog until a translation changes. A failed load gives English. */
async function loadTranslations(): Promise<Record<string, string>> {
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
		return (await response.json()).message ?? {}
	} catch (error) {
		console.warn('Translations did not load. The console shows English.', error)
		return {}
	}
}

// Top-level await: the browser fetches the app's modules meanwhile, and a module that
// imports __ runs only after the catalog is in, so a module-level __() is translated.
if (typeof window !== 'undefined' && window.lang)
	translations = await loadTranslations()

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
