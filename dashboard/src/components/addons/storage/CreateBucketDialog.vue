<script setup lang="ts">
import { Alert, Button, Dialog, Select, TextInput } from 'frappe-ui'
import { computed, ref } from 'vue'
import ServerMap from '@/components/servers/ServerMap.vue'
import { useMeteredServices } from '@/composables/useMeteredServices'
import { useObjectStorage } from '@/composables/useObjectStorage'
import { getErrorMessage } from '@/lib/feedback'
import { money } from '@/lib/format'
import {
	flagEmoji,
	hasMapCoords,
	type MapSpot,
	regionLabel,
} from '@/lib/serverMap'
import { __ } from '@/lib/translate'

import type { BucketCredentials } from '@/types/storage'

const open = defineModel<boolean>({ required: true })
const emit = defineEmits<{ created: [credentials: BucketCredentials] }>()

const { regions, createBucket } = useObjectStorage()
const { availablePlans, currency } = useMeteredServices()

const name = ref('')
const pickedRegion = ref('')
const region = computed({
	get: () => pickedRegion.value || regions.value[0]?.region || '',
	set: (value: string) => (pickedRegion.value = value),
})
const creating = ref(false)

const error = ref('')

const reset = (): void => {
	name.value = ''
	pickedRegion.value = ''
	error.value = ''
}

const regionOptions = computed(() =>
	regions.value.map((r) => ({
		label: regionLabel(r),
		value: r.region,
		icon: flagEmoji(r.country_code),
	})),
)

const markers = computed<MapSpot[]>(() =>
	regions.value.filter(hasMapCoords).map((r) => ({
		id: r.region,
		lat: r.latitude!,
		lng: r.longitude!,
		provider: r.provider || null,
		regionLabel: regionLabel(r),
		flag: flagEmoji(r.country_code),
	})),
)

const plan = computed(() =>
	availablePlans.value.find((p) => p.resource_type === 'Storage'),
)

const create = async (): Promise<void> => {
	if (creating.value) return

	creating.value = true
	error.value = ''
	try {
		emit('created', await createBucket(name.value, region.value))
		open.value = false
	} catch (e) {
		error.value = getErrorMessage(e, "The bucket couldn't be created.")
	} finally {
		creating.value = false
	}
}

const createBucketErrorTitle = __("Couldn't create the bucket")
const regionDescription = __(
	"Objects stay in this region. A bucket can't move later.",
)
</script>

<template>
	<Dialog
		v-model="open"
		:title="__('Create bucket')"
		size="lg"
		:dismissible="!creating"
		:show-close-button="!creating"
		@after-leave="reset"
	>
		<form class="space-y-5" @submit.prevent="create">
			<Alert
				v-if="error"
				theme="red"
				:title="createBucketErrorTitle"
				:description="error"
			/>

			<div
				v-if="markers.length"
				class="relative h-56 overflow-hidden rounded-6 border border-outline-gray-2"
			>
				<ServerMap
					:interactive="false"
					compact
					:markers="markers"
					:selected-id="region"
				/>
			</div>

			<TextInput
				v-model="name"
				autofocus
				:label="__('Name')"
				:placeholder="__('media')"
				:description="__('Lowercase letters, digits, dots and hyphens.')"
				required
				pattern="[a-z0-9.\-]*[a-z0-9]"
				:title="__('Lowercase letters, digits, dots and hyphens, ending in a letter or digit.')"
				autocomplete="off"
				:disabled="creating"
			/>

			<Select
				v-model="region"
				:label="__('Region')"
				:options="regionOptions"
				:description="regionDescription"
				side="bottom"
				:disabled="creating"
			/>

			<p
				v-if="plan"
				class="flex items-baseline justify-between gap-3 border-t border-outline-gray-2 pt-4 text-sm text-ink-gray-6"
			>
				{{ __('{0} {1} included', [plan.allowance, plan.unit]) }}
				<span class="shrink-0 text-base-semibold tabular-nums text-ink-gray-9">
					{{ money(plan.rate, currency, { trimTrailingZeros: true }) }}
					<span class="text-sm text-ink-gray-5">{{ __('/ month') }}</span>
				</span>
			</p>

			<div class="flex justify-end gap-2">
				<Button
					:label="__('Cancel')"
					:disabled="creating"
					@click="open = false"
				/>
				<Button
					type="submit"
					variant="solid"
					:label="__('Create bucket')"
					:loading="creating"
				/>
			</div>
		</form>
	</Dialog>
</template>
