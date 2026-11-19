<script setup lang="ts">
import { ref, watch } from 'vue'
import AddMethodDialog from '@/components/AddMethodDialog.vue'
import EditBillingProfileDialog from '@/components/billing/EditBillingProfileDialog.vue'
import { useBillingSetup } from '@/composables/useBillingSetup'

const emit = defineEmits<{ done: [] }>()

const { complete, refresh } = useBillingSetup()
// Its own dialog state, so a page that already shows billing details never gets a second one.
const showProfile = ref(false)
const showAddMethod = ref(false)

function start(): void {
	if (complete.value) showAddMethod.value = true
	else showProfile.value = true
}

watch(showProfile, (open, wasOpen) => {
	if (wasOpen && !open && complete.value) showAddMethod.value = true
})

async function onAdded(): Promise<void> {
	await refresh()
	emit('done')
}

defineExpose({ start })
</script>

<template>
	<EditBillingProfileDialog v-model="showProfile" />
	<AddMethodDialog v-model="showAddMethod" @done="onAdded" />
</template>
