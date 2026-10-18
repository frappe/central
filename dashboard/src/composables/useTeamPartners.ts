import { call, frappeRequest } from 'frappe-ui'
import { ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { TeamPartners } from '@/types/api'

/** The active team's partner and clients, and the calls that change a link. */
export function useTeamPartners() {
	const { activeTeam } = useSession()
	const partners = ref<TeamPartners | null>(null)
	const loading = ref(false)
	const error = ref('')
	let generation = 0

	async function reload() {
		const current = ++generation
		partners.value = null
		error.value = ''
		if (!activeTeam.value) return

		loading.value = true
		try {
			const result = await frappeRequest<TeamPartners>({
				url: methodV1(API.teamPartners),
				method: 'GET',
				params: { team: activeTeam.value },
			})
			if (current === generation) partners.value = result
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(failure, "Partners couldn't be loaded.")
		} finally {
			if (current === generation) loading.value = false
		}
	}

	watch(activeTeam, reload, { immediate: true })

	async function end(link: string, reason?: string) {
		await call(API.endTeamPartnerLink, {
			team: activeTeam.value,
			link,
			...(reason ? { reason } : {}),
		})
		await reload()
	}

	async function setAccess(link: string, partnerAccess: boolean) {
		await call(API.setTeamPartnerAccess, {
			team: activeTeam.value,
			link,
			partner_access: partnerAccess ? 1 : 0,
		})
		await reload()
	}

	return { partners, loading, error, reload, end, setAccess }
}
