<script setup lang="ts">
import { Button } from 'frappe-ui'
import { computed, ref } from 'vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import UsageAlertsDialog from '@/components/servers/UsageAlertsDialog.vue'
import { useServerUsageAlerts } from '@/composables/useServerUsageAlerts'
import { successToast } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { UsageAlertLimits } from '@/types/servers'

interface Props {
	resourceId: string
	/** The viewer holds server:resize on this server. */
	canChange: boolean
	/** A resize or power action is running on the server. */
	isLocked: boolean
}

const props = defineProps<Props>()
const { limits, loading, saving, error, save } = useServerUsageAlerts(
	computed(() => props.resourceId),
)
const isDialogOpen = ref(false)

const percent = (value: number): string => (value ? `${value}%` : __('off'))

const summary = computed(() => {
	const value = limits.value
	if (!value)
		return __('Get notified when CPU, memory, or disk use stays high.')
	if (
		!value.cpu_usage_limit &&
		!value.memory_usage_limit &&
		!value.disk_space_limit
	)
		return __(
			'Off. Turn on to get notified when CPU, memory, or disk use stays high.',
		)
	return __('Alerts at CPU {0}, memory {1}, disk {2}.', [
		percent(value.cpu_usage_limit),
		percent(value.memory_usage_limit),
		percent(value.disk_space_limit),
	])
})

async function submit(next: UsageAlertLimits): Promise<void> {
	if (!(await save(next))) return
	successToast(__('Usage alerts saved'))
	isDialogOpen.value = false
}
</script>

<template>
	<SettingsSection :title="__('Usage alerts')">
		<template #description>
			{{ summary }}
			<span
				v-if="error && !isDialogOpen"
				role="alert"
				class="mt-1 block text-ink-red-5"
			>
				{{ error }}
			</span>
		</template>

		<template #actions>
			<Button
				:label="__('Edit')"
				:disabled="!canChange || isLocked || loading || !limits"
				@click="isDialogOpen = true"
			/>
		</template>
	</SettingsSection>

	<UsageAlertsDialog
		v-if="limits"
		v-model:open="isDialogOpen"
		:limits="limits"
		:saving="saving"
		:error="error"
		@save="submit"
	/>
</template>
