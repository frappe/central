import { frappeRequest } from 'frappe-ui'
import { type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { App, AppRequirements } from '@/types/serverCreation'

/** What the selected app asks the user for, and the answers given so far. */
export function useAppRequirements(
	region: Ref<string | null>,
	app: Ref<App | null>,
) {
	const { activeTeam } = useSession()
	const requirements = ref<AppRequirements | null>(null)
	const answers = ref<Record<string, string>>({})
	const loading = ref(false)
	const error = ref('')
	let generation = 0

	async function reload() {
		const current = ++generation
		requirements.value = null
		answers.value = {}
		error.value = ''
		loading.value = false
		if (!activeTeam.value || !region.value || !app.value) return

		loading.value = true
		try {
			const result = await frappeRequest<AppRequirements>({
				url: methodV1(API.appRequirements),
				method: 'GET',
				params: {
					team: activeTeam.value,
					region: region.value,
					application: app.value.application,
				},
			})
			if (current !== generation) return
			requirements.value = result
			answers.value = Object.fromEntries(
				result.inputs.map((input) => [input.name, '']),
			)
		} catch (failure) {
			if (current === generation)
				error.value = getErrorMessage(
					failure,
					'App settings could not be loaded.',
				)
		} finally {
			if (current === generation) loading.value = false
		}
	}

	watch([activeTeam, region, () => app.value?.application], reload, {
		immediate: true,
	})

	// Every required answer is filled; Cargo checks each value's type at launch.
	function isComplete(): boolean {
		return (requirements.value?.inputs ?? []).every(
			(input) => !input.required || !!answers.value[input.name]?.trim(),
		)
	}

	return { requirements, answers, loading, error, reload, isComplete }
}
