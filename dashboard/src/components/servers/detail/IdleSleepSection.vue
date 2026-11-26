<script setup lang="ts">
import { Select, Switch } from 'frappe-ui'
import { computed } from 'vue'
import SettingsSection from '@/components/common/SettingsSection.vue'
import { useServerIdleSleep } from '@/composables/useServerIdleSleep'
import { successToast } from '@/lib/feedback'
import { __ } from '@/lib/translate'

interface Props {
	resourceId: string
	/** The viewer holds server:resize on this server. */
	canChange: boolean
	/** An open free trial owns the server's sleep setting. */
	isTrial: boolean
	/** A resize or power action is running on the server. */
	isLocked: boolean
}

const props = defineProps<Props>()
const { seconds, loading, saving, error, save } = useServerIdleSleep(
	computed(() => props.resourceId),
)

const DEFAULT_SECONDS = 30 * 60
const PRESETS = [15 * 60, 30 * 60, 60 * 60, 2 * 60 * 60, 4 * 60 * 60]

function formatIdleTime(value: number): string {
	const minutes = Math.round(value / 60)
	if (minutes % 60 !== 0) return __('{0} minutes', [minutes])
	return minutes === 60 ? __('1 hour') : __('{0} hours', [minutes / 60])
}

const isOn = computed(() => !!seconds.value)

const isDisabled = computed(
	() =>
		!props.canChange ||
		props.isTrial ||
		props.isLocked ||
		loading.value ||
		saving.value ||
		seconds.value === null,
)

// An operator can set a time outside the presets in Desk, so keep it selectable.
const options = computed(() => {
	const values =
		seconds.value && !PRESETS.includes(seconds.value)
			? [...PRESETS, seconds.value].sort((first, second) => first - second)
			: PRESETS
	return values.map((value) => ({
		label: formatIdleTime(value),
		value: String(value),
	}))
})

async function change(value: number): Promise<void> {
	if (value === seconds.value || !(await save(value))) return
	successToast(
		value
			? __('Server sleeps after {0} idle', [formatIdleTime(value)])
			: __('Sleep when idle is off'),
	)
}
</script>

<template>
	<SettingsSection :title="__('Sleep when idle')">
		<template #description>
			<template v-if="isTrial">
				{{ __('Free trial servers sleep when idle. Upgrade to change this.') }}
			</template>
			<template v-else>
				{{ __(
						'Save the server\'s memory and stop it when it gets no incoming requests. The next request wakes it, with every process as it was.',
					) }}
			</template>
			<span v-if="error" role="alert" class="mt-1 block text-ink-red-5">
				{{ error }}
			</span>
		</template>

		<div v-if="isOn" class="space-y-4">
			<div class="flex flex-wrap items-center gap-2">
				<label for="idle-sleep-time" class="text-p-sm text-ink-gray-7">
					{{ __('Sleep after') }}
				</label>
				<Select
					id="idle-sleep-time"
					class="w-36"
					:model-value="String(seconds)"
					:options="options"
					:disabled="isDisabled"
					@update:model-value="change(Number($event))"
				/>
			</div>
			<ul class="list-disc space-y-1 pl-5 text-p-sm text-ink-gray-6">
				<li>
					{{ __(
							'Incoming SSH, HTTP and WireGuard VPN traffic keeps the server awake. Ping and outbound traffic do not.',
						) }}
				</li>
				<li>
					{{ __(
							'A sleeping server shows as Sleeping. Cron jobs and background workers do not run until it wakes.',
						) }}
				</li>
			</ul>
		</div>

		<template #actions>
			<Switch
				:model-value="isOn"
				:disabled="isDisabled"
				@update:model-value="change($event ? DEFAULT_SECONDS : 0)"
			>
				<template #label>
					<span class="sr-only">{{ __('Sleep when idle') }}</span>
				</template>
			</Switch>
		</template>
	</SettingsSection>
</template>
