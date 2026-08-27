import { useCall } from 'frappe-ui'
import { ref } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { errorToast, successToast } from '@/lib/toast'
import type { BillingGroup } from '@/types/billing'

// Rename / enable-disable for Billing Groups — the mutations BillingGroupsCard
// and BillingGroupsPanel both need (card shows the top few, panel shows all of
// them; sharing this keeps the busy/toggle state one thing, not two that could
// disagree about which row is mid-mutation).

const toggle = useCall<unknown, { name: string; enabled: boolean }>({
	url: method(API.setBillingGroupEnabled),
	method: 'POST',
	immediate: false,
})

const busy = ref('')
const pendingRename = ref<BillingGroup | null>(null)
const pendingManageMembers = ref<BillingGroup | null>(null)

export function useBillingGroups() {
	const { groups, reloadGroups } = useBillingOverview()

	async function onToggle(g: BillingGroup): Promise<void> {
		busy.value = g.name
		try {
			await toggle.submit({ name: g.name, enabled: !g.enabled })
			successToast(g.enabled ? 'Billing group disabled.' : 'Billing group enabled.')
			reloadGroups()
		} catch (e) {
			errorToast(e)
		} finally {
			busy.value = ''
		}
	}

	function onRename(g: BillingGroup): void {
		pendingRename.value = g
	}

	function onManageMembers(g: BillingGroup): void {
		pendingManageMembers.value = g
	}

	return {
		groups,
		busy,
		pendingRename,
		pendingManageMembers,
		onToggle,
		onRename,
		onManageMembers,
		reloadGroups,
	}
}
