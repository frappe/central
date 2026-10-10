<script setup lang="ts">
import { Button, Dialog } from 'frappe-ui'
import { computed, ref } from 'vue'
import BillingProfileForm from '@/components/billing/BillingProfileForm.vue'

// Edit the billing profile, shared by the Billing contact and Tax & compliance cards.
const open = defineModel<boolean>({ default: false })
const form = ref<InstanceType<typeof BillingProfileForm> | null>(null)
const saving = computed(() => form.value?.saving ?? false)

async function save(): Promise<void> {
	if (await form.value?.submit()) open.value = false
}
</script>

<template>
	<Dialog v-model:open="open" title="Billing details" size="xl">
		<template #default>
			<BillingProfileForm ref="form" />
		</template>
		<template #actions>
			<div class="flex items-center justify-end gap-2">
				<Button label="Cancel" @click="open = false" />
				<Button variant="solid" label="Save" :loading="saving" @click="save" />
			</div>
		</template>
	</Dialog>
</template>
