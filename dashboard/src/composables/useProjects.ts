import { useCall } from 'frappe-ui'
import { ref } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { errorToast, successToast } from '@/lib/toast'
import type { Project } from '@/types/billing'

// Rename / enable-disable for Projects — the mutations ProjectsCard and
// ProjectsPanel both need (card shows the top few, panel shows all of them;
// sharing this keeps the busy/toggle state one thing, not two that could
// disagree about which row is mid-mutation).

const toggle = useCall<unknown, { name: string; enabled: boolean }>({
	url: method(API.setProjectEnabled),
	method: 'POST',
	immediate: false,
})

const busy = ref('')
const pendingRename = ref<Project | null>(null)
const pendingManageMembers = ref<Project | null>(null)

export function useProjects() {
	const { projects, reloadProjects } = useBillingOverview()

	async function onToggle(p: Project): Promise<void> {
		busy.value = p.name
		try {
			await toggle.submit({ name: p.name, enabled: !p.enabled })
			successToast(p.enabled ? 'Project disabled.' : 'Project enabled.')
			reloadProjects()
		} catch (e) {
			errorToast(e)
		} finally {
			busy.value = ''
		}
	}

	function onRename(p: Project): void {
		pendingRename.value = p
	}

	function onManageMembers(p: Project): void {
		pendingManageMembers.value = p
	}

	return {
		projects,
		busy,
		pendingRename,
		pendingManageMembers,
		onToggle,
		onRename,
		onManageMembers,
		reloadProjects,
	}
}
