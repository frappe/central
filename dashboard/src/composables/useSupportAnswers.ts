import { useCall } from 'frappe-ui'
import { computed, type Ref, ref } from 'vue'
import { API, method } from '@/api/methods'
import { escapeHtml } from '@/components/search/utils'
import type {
	SupportCategoryKey,
	SupportContext,
	SupportRelatedResults,
} from '@/composables/useSupport'

export interface ContactSupportState {
	query: string
	isLoading: boolean
}

export interface OutageIssue {
	category: SupportCategoryKey
	issue: string
}

export type ContactAction = 'disabled' | 'dismiss' | 'contact'

export function canContactSupport({
	query,
	isLoading,
}: ContactSupportState): boolean {
	return query.trim().length >= 3 && !isLoading
}

export function contactAction({
	query,
	isLoading,
	hasResults,
}: ContactSupportState & { hasResults: boolean }): ContactAction {
	if (!canContactSupport({ query, isLoading })) return 'disabled'

	return hasResults ? 'dismiss' : 'contact'
}

export function getOutageIssue(context: SupportContext): OutageIssue {
	if (context.Site) {
		return {
			category: 'site',
			issue: 'Site setup or provisioning failed',
		}
	}
	return {
		category: 'server',
		issue: 'Unreachable or down',
	}
}

export function highlightWords(text: string, query: string): string {
	const safeText = escapeHtml(text)
	const words = query
		.trim()
		.split(/\s+/)
		.filter((word) => word.length >= 3)
		.map((word) => word.toLowerCase())

	if (words.length === 0) return safeText

	const pattern = [...new Set(words)]
		.sort((first, second) => second.length - first.length)
		.map((word) => escapeHtml(word).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
		.join('|')

	return safeText.replace(new RegExp(`(${pattern})`, 'gi'), '<mark>$1</mark>')
}

const SEARCH_TIMEOUT_MS = 10_000

export function useSupportAnswers(team: Ref<string | null | undefined>) {
	const query = ref('')
	const results = ref<SupportRelatedResults | null>(null)
	const loading = ref(false)
	const error = ref(false)
	let timer: number | undefined
	let request = 0

	const call = useCall<SupportRelatedResults, { team: string; query: string }>({
		url: method(API.findRelated),
		params: () => ({ team: team.value ?? '', query: query.value }),
		immediate: false,
	})

	const articles = computed(() => results.value?.articles ?? [])
	const tickets = computed(() => results.value?.tickets ?? [])
	const resultCount = computed(
		() => articles.value.length + tickets.value.length,
	)

	function reset(): void {
		request += 1
		query.value = ''
		results.value = null
		error.value = false
		loading.value = false
	}

	function refresh(searchText: string): void {
		window.clearTimeout(timer)
		const trimmed = searchText.trim()

		if (trimmed.length < 3 || !team.value) {
			reset()
			return
		}

		query.value = trimmed
		results.value = null
		error.value = false
		loading.value = true
		timer = window.setTimeout(() => search(trimmed), 400)
	}

	async function search(searchText: string): Promise<void> {
		const current = ++request
		let timeout: number | undefined
		try {
			const data = await Promise.race([
				call.reload(),
				new Promise<null>((resolve) => {
					timeout = window.setTimeout(() => resolve(null), SEARCH_TIMEOUT_MS)
				}),
			])
			window.clearTimeout(timeout)
			if (current !== request || searchText !== query.value) return
			loading.value = false
			if (data === null || call.error) {
				error.value = true
				results.value = null
				return
			}
			results.value = data ?? { articles: [], tickets: [] }
		} catch {
			window.clearTimeout(timeout)
			if (current !== request || searchText !== query.value) return
			loading.value = false
			error.value = true
			results.value = null
		}
	}

	function stop(): void {
		window.clearTimeout(timer)
	}

	return {
		articles,
		tickets,
		resultCount,
		query,
		results,
		loading,
		error,
		refresh,
		search,
		stop,
	}
}
