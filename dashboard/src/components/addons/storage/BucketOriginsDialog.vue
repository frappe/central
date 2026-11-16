<script setup lang="ts">
import { Alert, Button, Dialog, Textarea } from 'frappe-ui'
import { ref, watch } from 'vue'
import { bucketLabel, useObjectStorage } from '@/composables/useObjectStorage'
import { getErrorMessage } from '@/lib/feedback'
import { __ } from '@/lib/translate'
import type { StorageBucket } from '@/types/storage'

interface Props {
	origins: string[] | undefined
}

const props = defineProps<Props>()
const bucket = defineModel<StorageBucket | null>({ required: true })

const { setOrigins } = useObjectStorage()

const text = ref('')
const saving = ref(false)
const error = ref('')

watch(bucket, (target) => {
	if (target) text.value = (props.origins ?? []).join('\n')
})

const save = async (): Promise<void> => {
	if (!bucket.value || saving.value) return

	saving.value = true
	try {
		const origins = text.value
			.split('\n')
			.map((line) => line.trim())
			.filter(Boolean)
		await setOrigins(bucket.value.name, origins)
		bucket.value = null
	} catch (e) {
		error.value = getErrorMessage(e, "The allowed origins couldn't be saved.")
	} finally {
		saving.value = false
	}
}

const saveErrorTitle = __("Couldn't update the allowed origins")
</script>

<template>
	<Dialog
		:model-value="!!bucket"
		:title="bucket ? __('Allowed origins for {0}', [bucketLabel(bucket)]) : ''"
		size="md"
		@update:model-value="(open: boolean) => !open && (bucket = null)"
		@after-leave="error = ''"
	>
		<Alert
			v-if="error"
			class="mb-4"
			theme="red"
			:title="saveErrorTitle"
			:description="error"
		/>

		<Textarea
			v-model="text"
			autofocus
			:rows="5"
			:label="__('Origins')"
			:placeholder="__('https://files.example.com')"
			:description="
				__(
					'One per line, as scheme://host or scheme://host:port, without a path. Leave it empty to allow none.',
				)
			"
		/>

		<div class="mt-6 flex justify-end gap-2">
			<Button :label="__('Cancel')" @click="bucket = null" />
			<Button
				variant="solid"
				:label="__('Save origins')"
				:loading="saving"
				@click="save"
			/>
		</div>
	</Dialog>
</template>
