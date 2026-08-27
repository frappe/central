<script setup lang="ts">
import { Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { errorToast } from '@/lib/toast'
import type { BillingGroup } from '@/types/billing'

// Rename a Billing Group. Controlled by the card: pass the group being renamed
// (or null) via v-model:group, like RenamePaymentMethodDialog would. Purely
// cosmetic — renaming never changes what the group bills.
const props = defineProps<{ group: BillingGroup | null }>()
const emit = defineEmits<{
	'update:group': [group: BillingGroup | null]
	renamed: []
}>()

const open = computed({
	get: () => !!props.group,
	set: (v: boolean) => {
		if (!v) emit('update:group', null)
	},
})

const title = ref('')
watch(
	() => props.group,
	(group) => {
		if (group) title.value = group.title
	},
)

const canSubmit = computed(
	() => title.value.trim().length > 0 && title.value.trim() !== props.group?.title,
)

const rename = useCall<unknown, { name: string; title: string }>({
	url: method(API.renameBillingGroup),
	method: 'POST',
	immediate: false,
})

async function submit(): Promise<void> {
	if (!props.group || !canSubmit.value) return
	try {
		await rename.submit({ name: props.group.name, title: title.value.trim() })
		emit('update:group', null)
		emit('renamed')
	} catch (e) {
		errorToast(e)
	}
}

const dialogOptions = computed(() => ({
	title: 'Rename billing group',
	actions: [
		{
			label: 'Save',
			variant: 'solid' as const,
			loading: rename.loading,
			disabled: !canSubmit.value,
			onClick: submit,
		},
	],
}))
</script>

<template>
	<Dialog
		v-model="open"
		:title="dialogOptions.title"
		:actions="dialogOptions.actions"
	>
		<template #default>
			<FormControl v-model="title" label="Title" @keyup.enter="submit" />
		</template>
	</Dialog>
</template>
