<script setup lang="ts">
import { Alert, Button, Dialog, TextInput } from 'frappe-ui'
import { ref, watch } from 'vue'
import { bucketLabel, useObjectStorage } from '@/composables/useObjectStorage'
import { getErrorMessage } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { BucketUsage, StorageBucket } from '@/types/storage'

interface Props {
	usage: BucketUsage | null | undefined
}

const props = defineProps<Props>()
const bucket = defineModel<StorageBucket | null>({ required: true })

const { setQuota } = useObjectStorage()

const GIB = 1024 ** 3
const sizeGib = ref(0)
const maxObjects = ref(0)
const saving = ref(false)
const error = ref('')

watch(bucket, (target) => {
	if (!target) return
	sizeGib.value = Math.round((props.usage?.quota_bytes ?? 0) / GIB)
	maxObjects.value = props.usage?.quota_objects ?? 0
})

const save = async (): Promise<void> => {
	if (!bucket.value || saving.value) return

	saving.value = true
	try {
		await setQuota(
			bucket.value.name,
			Number(sizeGib.value),
			Number(maxObjects.value),
		)
		bucket.value = null
	} catch (e) {
		error.value = getErrorMessage(e, "The quota couldn't be saved.")
	} finally {
		saving.value = false
	}
}

const updateQuotaErrorTitle = __("Couldn't update the quota")
</script>

<template>
	<Dialog
		:model-value="!!bucket"
		:title="bucket ? __('Quota for {0}', [bucketLabel(bucket)]) : ''"
		size="md"
		@update:model-value="(open: boolean) => !open && (bucket = null)"
		@after-leave="error = ''"
	>
		<Alert
			v-if="error"
			class="mb-4"
			theme="red"
			:title="updateQuotaErrorTitle"
			:description="error"
		/>

		<div class="space-y-5">
			<TextInput
				v-model="sizeGib"
				autofocus
				type="number"
				:label="__('Size limit (GiB)')"
				:min="0"
				:description="__('Uploads that would pass this size are refused. 0 means no limit.')"
			/>
			<TextInput
				v-model="maxObjects"
				type="number"
				:label="__('Object limit')"
				:min="0"
				:description="__('The most objects the bucket may hold. 0 means no limit.')"
			/>
		</div>

		<div class="mt-6 flex justify-end gap-2">
			<Button :label="__('Cancel')" @click="bucket = null" />
			<Button
				variant="solid"
				:label="__('Save quota')"
				:loading="saving"
				@click="save"
			/>
		</div>
	</Dialog>
</template>
