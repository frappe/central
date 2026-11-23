<script setup lang="ts">
import { Alert, Dialog, TextInput } from 'frappe-ui'
import { computed, reactive, watch } from 'vue'
import {
	parseUsageAlertLimit,
	USAGE_ALERT_MAXIMUM,
} from '@/composables/useServerUsageAlerts'
import { __ } from '@/lib/translate'
import type { UsageAlertLimits } from '@/types/servers'

interface Props {
	limits: UsageAlertLimits
	saving: boolean
	error: string
}

const props = defineProps<Props>()
const open = defineModel<boolean>('open', { default: false })
const emit = defineEmits<{ save: [limits: UsageAlertLimits] }>()

const fields = [
	{ key: 'cpu_usage_limit', label: __('CPU') },
	{ key: 'memory_usage_limit', label: __('Memory') },
	{ key: 'disk_space_limit', label: __('Disk') },
] as const

const values = reactive<Record<keyof UsageAlertLimits, string>>({
	cpu_usage_limit: '',
	memory_usage_limit: '',
	disk_space_limit: '',
})

watch(open, (isOpen) => {
	if (!isOpen) return
	for (const field of fields)
		values[field.key] = String(props.limits[field.key])
})

const invalidMessage = __(
	'Set a percentage from 1 to {0}, or 0 to turn it off.',
	[USAGE_ALERT_MAXIMUM],
)

const next = computed<UsageAlertLimits | null>(() => {
	const parsed = {} as UsageAlertLimits
	for (const field of fields) {
		const limit = parseUsageAlertLimit(values[field.key])
		if (limit === null) return null
		parsed[field.key] = limit
	}
	return parsed
})

const canSave = computed(
	() =>
		!props.saving &&
		!!next.value &&
		fields.some((field) => next.value?.[field.key] !== props.limits[field.key]),
)

function save(): void {
	if (canSave.value && next.value) emit('save', next.value)
}
</script>

<template>
	<Dialog
		v-model="open"
		:title="__('Usage alerts')"
		:actions="[
			{
				label: __('Save'),
				variant: 'solid',
				disabled: !canSave,
				loading: saving,
				onClick: save,
			},
		]"
	>
		<template #default>
			<div class="space-y-4">
				<p class="text-p-sm text-ink-gray-6">
					{{ __('Get an email and a notification when use stays above the percentage. Set 0 to turn an alert off.') }}
				</p>

				<Alert
					v-if="error"
					theme="red"
					:title="__('Couldn\'t save the usage alerts')"
					:description="error"
				/>

				<div v-for="field in fields" :key="field.key" class="space-y-1.5">
					<TextInput
						v-model="values[field.key]"
						type="number"
						:label="field.label"
						:min="0"
						:max="USAGE_ALERT_MAXIMUM"
						@keyup.enter="save"
					>
						<template #suffix>
							<span class="text-sm text-ink-gray-5">%</span>
						</template>
					</TextInput>
					<p
						v-if="parseUsageAlertLimit(values[field.key]) === null"
						class="text-p-sm text-ink-red-5"
					>
						{{ invalidMessage }}
					</p>
				</div>
			</div>
		</template>
	</Dialog>
</template>
