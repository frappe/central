<script setup lang="ts">
import { TextInput } from 'frappe-ui'
import type { SubdomainAvailability } from '@/types/serverCreation'

interface TemplateSiteNameProps {
	zone: string
	required: boolean
	checking: boolean
	availability: SubdomainAvailability | null
	error: string
}

defineProps<TemplateSiteNameProps>()

const siteName = defineModel<string>({ required: true })
</script>

<template>
	<div class="space-y-1.5">
		<TextInput
			v-model="siteName"
			:label="required ? 'Site name' : 'Site name (optional)'"
			:required="required"
			size="md"
			placeholder="yourapp"
			autocomplete="off"
			autocapitalize="off"
			spellcheck="false"
		>
			<template #suffix>
				<span class="text-base text-ink-gray-5">.{{ zone }}</span>
			</template>
		</TextInput>
		<p v-if="checking" role="status" class="text-p-xs text-ink-gray-5">
			Checking…
		</p>
		<p v-else-if="error" class="text-p-xs text-ink-red-6">{{ error }}</p>
		<p
			v-else-if="availability && !availability.available"
			class="text-p-xs text-ink-red-6"
		>
			{{ availability.reason }}
		</p>
		<p v-else-if="availability?.available" class="text-p-xs text-ink-green-7">
			{{ availability.subdomain }}.{{ zone }}
			is available.
		</p>
		<p v-else class="text-p-xs text-ink-gray-5">
			The web address of the application. You can connect a custom domain later.
		</p>
	</div>
</template>
