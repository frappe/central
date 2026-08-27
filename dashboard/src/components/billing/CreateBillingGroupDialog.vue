<script setup lang="ts">
import { Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { errorToast } from '@/lib/toast'

// Create a new Billing Group for the active team — a partition it can tag
// subscriptions/cards/credits into to bill and settle them on their own,
// separate from the team's consolidated one (ARCHITECTURE.md §2.1). Controlled
// by the card via v-model; emits `created` with the new group's name so the
// card can, say, immediately offer to tag a subscription into it.
const open = defineModel<boolean>({ default: false })
const emit = defineEmits<{ created: [name: string] }>()
const { activeTeam } = useSession()

const title = ref('')
watch(open, (isOpen) => {
	if (isOpen) title.value = ''
})

const canSubmit = computed(() => title.value.trim().length > 0)

const create = useCall<{ name: string }, { title: string; team: string }>({
	url: method(API.createBillingGroup),
	method: 'POST',
	immediate: false,
})

async function submit(): Promise<void> {
	if (!canSubmit.value) return
	try {
		await create.submit({
			title: title.value.trim(),
			team: activeTeam.value!,
		})
		if (create.error) throw create.error
		open.value = false
		emit('created', create.data!.name)
	} catch (e) {
		errorToast(e)
	}
}

const dialogOptions = computed(() => ({
	title: 'Create billing group',
	actions: [
		{
			label: 'Create',
			variant: 'solid' as const,
			loading: create.loading,
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
			<FormControl
				v-model="title"
				label="Title"
				placeholder="e.g. Acme Corp"
				description="Subscriptions, cards, and credits tagged into this group bill and settle on their own."
				@keyup.enter="submit"
			/>
		</template>
	</Dialog>
</template>
