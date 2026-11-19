<script setup lang="ts">
import { Alert, Button, Dialog, TextInput } from 'frappe-ui'
import { computed, ref } from 'vue'
import CopyButton from '@/components/common/CopyButton.vue'
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

	reportError(
		`Could not copy ${label.toLowerCase()}. Select it and copy it manually.`,
	)
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
			<Alert
				theme="amber"
				title="The secret key is shown only now"
				description="Copy it somewhere safe. If you lose it, rotate the credentials to get a new one."
			/>

			<TextInput
				v-for="field in fields"
				:key="field.label"
				:label="field.label"
				:model-value="field.value"
				readonly
				class="field"
			>
				<template #suffix>
					<CopyButton
						size="sm"
						:text="field.value"
						:label="`Copy ${field.label.toLowerCase()}`"
					/>
				</template>
			</TextInput>

			<TextInput
				label="Secret key"
				:model-value="maskedSecret"
				readonly
				class="field secret"
			>
				<template #suffix>
					<Button
						variant="ghost"
						size="sm"
						:icon="secretRevealed ? 'lucide-eye-off' : 'lucide-eye'"
						:label="secretRevealed ? 'Hide secret key' : 'Show secret key'"
						:tooltip="secretRevealed ? 'Hide' : 'Show'"
						@click="secretRevealed = !secretRevealed"
					/>
					<CopyButton
						size="sm"
						:text="credentials.secret_access_key"
						label="Copy secret key"
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

<style scoped>
.field :deep(input) {
	@apply pe-10 text-ellipsis;
}

.secret :deep(input) {
	@apply pe-16;
}
</style>
