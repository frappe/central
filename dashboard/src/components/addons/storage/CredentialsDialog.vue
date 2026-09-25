<script setup lang="ts">
import { Button, Dialog, TextInput } from 'frappe-ui'
import { computed, ref } from 'vue'
import { copyToClipboard } from '@/lib/clipboard'
import { reportError, successToast } from '@/lib/feedback'
import type { BucketCredentials } from '@/types/storage'

const credentials = defineModel<BucketCredentials | null>({ required: true })

const secretRevealed = ref(false)

const fields = computed(() => {
	const value = credentials.value
	if (!value) return []

	return [
		{ label: 'Endpoint URL', value: value.endpoint_url },
		{ label: 'Bucket', value: value.bucket_name },
		{ label: 'Access key', value: value.access_key },
	]
})

const maskedSecret = computed(() => {
	const secret = credentials.value?.secret_access_key ?? ''
	return secretRevealed.value
		? secret
		: `${secret.slice(0, 4)}${'•'.repeat(28)}${secret.slice(-4)}`
})

const environment = computed(() => {
	const value = credentials.value
	if (!value) return ''

	return [
		`S3_ENDPOINT_URL=${value.endpoint_url}`,
		`S3_BUCKET=${value.bucket_name}`,
		`AWS_ACCESS_KEY_ID=${value.access_key}`,
		`AWS_SECRET_ACCESS_KEY=${value.secret_access_key}`,
	].join('\n')
})

const copy = async (value: string, label: string): Promise<void> => {
	if (await copyToClipboard(value)) {
		successToast(`${label} copied`)
		return
	}

	reportError(`${label} could not be copied. Select it and copy by hand.`)
}
</script>

<template>
	<Dialog
		:model-value="!!credentials"
		title="Save your credentials"
		size="xl"
		@update:model-value="(open: boolean) => !open && (credentials = null)"
		@after-leave="secretRevealed = false"
	>
		<div v-if="credentials" class="space-y-5">
			<div
				class="flex items-start gap-3 rounded-4 bg-surface-amber-1 p-3 text-p-sm text-ink-amber-6"
			>
				<span
					class="lucide-key-round mt-0.5 size-4 shrink-0"
					aria-hidden="true"
				/>
				The secret key is shown only now. Copy it somewhere safe. If you lose
				it, rotate the credentials to get a new one.
			</div>

			<TextInput
				v-for="field in fields"
				:key="field.label"
				:label="field.label"
				:model-value="field.value"
				readonly
			>
				<template #suffix>
					<Button
						variant="ghost"
						size="sm"
						icon="lucide-copy"
						:label="`Copy ${field.label.toLowerCase()}`"
						tooltip="Copy"
						@click="copy(field.value, field.label)"
					/>
				</template>
			</TextInput>

			<TextInput label="Secret key" :model-value="maskedSecret" readonly>
				<template #suffix>
					<Button
						variant="ghost"
						size="sm"
						:icon="secretRevealed ? 'lucide-eye-off' : 'lucide-eye'"
						:label="secretRevealed ? 'Hide secret key' : 'Show secret key'"
						:tooltip="secretRevealed ? 'Hide' : 'Show'"
						@click="secretRevealed = !secretRevealed"
					/>
					<Button
						variant="ghost"
						size="sm"
						icon="lucide-copy"
						label="Copy secret key"
						tooltip="Copy"
						@click="copy(credentials.secret_access_key, 'Secret key')"
					/>
				</template>
			</TextInput>
		</div>

		<div class="mt-6 flex justify-between gap-2">
			<Button
				icon-left="lucide-file-code"
				label="Copy as .env"
				@click="copy(environment, 'Environment variables')"
			/>
			<Button variant="solid" label="Done" @click="credentials = null" />
		</div>
	</Dialog>
</template>
