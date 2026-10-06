import { useCall } from 'frappe-ui'
import { computed } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { teamParams, whenTeamReady } from '@/composables/useTeamScope'
import { money } from '@/lib/format'
import type { CollectionStatus, InvoiceDetail } from '@/types/billing'

export function useInvoiceDetail() {
	const { activeTeam } = useSession()
	const collection = useCall<CollectionStatus, { team: string }>({
		url: method(API.collectionStatus),
		params: teamParams,
		immediate: false,
		refetch: true,
	})
	const detail = useCall<InvoiceDetail, { name: string }>({
		url: method(API.invoice),
		immediate: false,
	})
	whenTeamReady(() => collection.reload())

	const isPayable = computed(() =>
		['open', 'overdue'].includes(String(detail.data?.status).toLowerCase()),
	)
	const isOverdue = computed(
		() =>
			String(detail.data?.status).toLowerCase() === 'overdue' &&
			Boolean(detail.data?.due_date),
	)
	const settling = computed(
		() => isPayable.value && Boolean(detail.data?.payment_in_progress),
	)
	const hasDue = computed(() => Number(detail.data?.expected_collection) > 0)
	const manualMode = computed(
		() => collection.data?.collection_mode === 'Manual Checkout',
	)
	const paidWithIcon = computed(() =>
		/upi/i.test(detail.data?.paid_with?.method_type ?? '')
			? 'lucide-smartphone'
			: 'lucide-credit-card',
	)

	function load(name: string): Promise<InvoiceDetail | null> {
		return detail.submit({ name })
	}
	function reload(name?: string): void {
		if (name) void detail.submit({ name })
	}
	function eventDetail(event: {
		detail: string | null
		amount: number
		currency?: string
	}): string {
		const parts: string[] = []
		if (event.amount)
			parts.push(money(event.amount, event.currency || detail.data?.currency))
		if (event.detail) parts.push(event.detail)
		return parts.join(' · ')
	}

	return {
		activeTeam,
		collection,
		detail,
		isPayable,
		isOverdue,
		settling,
		hasDue,
		manualMode,
		paidWithIcon,
		load,
		reload,
		eventDetail,
	}
}
