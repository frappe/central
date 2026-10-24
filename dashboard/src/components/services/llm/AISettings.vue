<script setup lang="ts">
import { SettingsRow, Switch } from 'frappe-ui'
import { computed, ref } from 'vue'
import { useAI } from '@/composables/useAI'
import { reportError, successToast } from '@/lib/feedback'

interface AISettingsProps {
	canManage: boolean
}

const props = defineProps<AISettingsProps>()

const { ai, setPromptLogging } = useAI()

// The switch shows the value asked for while Grove saves it, then what Grove read back.
const requested = ref<boolean | null>(null)
const logging = computed(
	() => requested.value ?? !!ai.value?.spend?.log_payloads,
)

const description = computed(
	() =>
		'Keep prompts and model replies, so support can look into a failed request.' +
		(props.canManage ? '' : ' Ask a team admin to change this.'),
)

const setLogging = async (enabled: boolean): Promise<void> => {
	requested.value = enabled
	try {
		await setPromptLogging(enabled)
		successToast(
			enabled ? 'Prompt logging turned on.' : 'Prompt logging turned off.',
		)
	} catch (e) {
		reportError(e, { title: 'Could not change prompt logging' })
	} finally {
		requested.value = null
	}
}
</script>

<template>
	<section>
		<SettingsRow title="Log prompts and outputs" :description="description">
			<Switch
				:model-value="logging"
				:disabled="!canManage || requested !== null"
				@update:model-value="setLogging"
			/>
		</SettingsRow>
	</section>
</template>
