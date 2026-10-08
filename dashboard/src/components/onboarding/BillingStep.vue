<script setup lang="ts">
import { computed, ref } from 'vue'
import BillingProfileForm from '@/components/billing/BillingProfileForm.vue'

const form = ref<InstanceType<typeof BillingProfileForm> | null>(null)

defineExpose({
	canSubmit: true,
	submitLabel: 'Save billing details',
	saving: computed(() => form.value?.saving ?? false),
	submit: async () => (await form.value?.submit()) ?? false,
})
</script>

<template>
	<BillingProfileForm ref="form" />
</template>
