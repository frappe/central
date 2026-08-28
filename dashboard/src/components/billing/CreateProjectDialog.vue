<script setup lang="ts">
import { Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { errorToast } from '@/lib/toast'

// Create a new Project for the active team — a tag it can attach to
// subscriptions so they show grouped under it in the invoice/forecast cost
// breakdown. Controlled by the card via v-model; emits `created` with the new
// project's name so the card can, say, immediately offer to tag a subscription
// into it.
const open = defineModel<boolean>({ default: false })
const emit = defineEmits<{ created: [name: string] }>()
const { activeTeam } = useSession()

const title = ref('')
const spendingLimit = ref<number | null>(null)
watch(open, (isOpen) => {
	if (isOpen) {
		title.value = ''
		spendingLimit.value = null
	}
})

const canSubmit = computed(() => title.value.trim().length > 0)

const create = useCall<
	{ name: string },
	{ title: string; team: string; spending_limit?: number }
>({
	url: method(API.createProject),
	method: 'POST',
	immediate: false,
})

async function submit(): Promise<void> {
	if (!canSubmit.value) return
	try {
		await create.submit({
			title: title.value.trim(),
			team: activeTeam.value!,
			spending_limit: spendingLimit.value || 0,
		})
		if (create.error) throw create.error
		open.value = false
		emit('created', create.data!.name)
	} catch (e) {
		errorToast(e)
	}
}

const dialogOptions = computed(() => ({
	title: 'Create project',
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
			<div class="space-y-4">
				<FormControl
					v-model="title"
					label="Title"
					placeholder="e.g. Acme Corp"
					description="Subscriptions tagged into this project show grouped under it in your cost breakdown."
					@keyup.enter="submit"
				/>
				<FormControl
					v-model="spendingLimit"
					type="number"
					label="Spending limit"
					placeholder="No limit"
					description="Blocks tagging new resources into this project once its committed monthly run-rate would exceed this. Leave blank for unlimited."
					min="0"
				/>
			</div>
		</template>
	</Dialog>
</template>
