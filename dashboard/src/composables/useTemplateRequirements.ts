import { frappeRequest } from 'frappe-ui'
import { type Ref, ref, watch } from 'vue'
import { API, methodV1 } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { getErrorMessage } from '@/lib/feedback'
import type { Template, TemplateRequirements } from '@/types/serverCreation'

/** What the selected template asks the user for, and the answers given so far. */
export function useTemplateRequirements(
	region: Ref<string | null>,
	template: Ref<Template | null>,
) {
	const { activeTeam } = useSession()
	const requirements = ref<TemplateRequirements | null>(null)
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
		if (!activeTeam.value || !region.value || !template.value) return

		loading.value = true
		try {
			const result = await frappeRequest<TemplateRequirements>({
				url: methodV1(API.templateRequirements),
				method: 'GET',
				params: {
					team: activeTeam.value,
					region: region.value,
					application: template.value.application,
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
					'Template settings could not be loaded.',
				)
		} finally {
			if (current === generation) loading.value = false
		}
	}

	watch([activeTeam, region, () => template.value?.application], reload, {
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
