<script setup lang="ts">
import { Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { errorToast } from '@/lib/toast'
import type { SubscriptionRow } from '@/types/billing'

// Tag a subscription into a Project, or clear it back to untagged. Controlled by
// the card: pass the pending subscription (or null) via v-model:subscription,
// like PauseBillingDialog. Only the team's currently-enabled projects are
// offered — a disabled one refuses new tags server-side too
// (Subscription.validate_project), which also rejects a tag that would push the
// project's committed run-rate over its spending_limit.
const UNTAGGED = ''

const props = defineProps<{ subscription: SubscriptionRow | null }>()
const emit = defineEmits<{
	'update:subscription': [sub: SubscriptionRow | null]
	assigned: []
}>()

const { projects } = useBillingOverview()

const open = computed({
	get: () => !!props.subscription,
	set: (v: boolean) => {
		if (!v) emit('update:subscription', null)
	},
})

const selected = ref(UNTAGGED)
watch(
	() => props.subscription,
	(sub) => {
		if (sub) selected.value = sub.project || UNTAGGED
	},
)

const options = computed(() => [
	{ label: 'No project', value: UNTAGGED },
	...(projects.data ?? [])
		.filter((p) => p.enabled)
		.map((p) => ({ label: p.title, value: p.name })),
])

const canSubmit = computed(
	() => selected.value !== (props.subscription?.project || UNTAGGED),
)

const assign = useCall<unknown, { subscription: string; project: string | null }>({
	url: method(API.setSubscriptionProject),
	method: 'POST',
	immediate: false,
})

async function submit(): Promise<void> {
	if (!props.subscription || !canSubmit.value) return
	try {
		await assign.submit({
			subscription: props.subscription.name,
			project: selected.value || null,
		})
		if (assign.error) throw assign.error
		emit('update:subscription', null)
		emit('assigned')
	} catch (e) {
		errorToast(e)
	}
}

const dialogOptions = computed(() => ({
	title: 'Move to project',
	actions: [
		{
			label: 'Save',
			variant: 'solid' as const,
			loading: assign.loading,
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
				type="select"
				v-model="selected"
				:options="options"
				label="Project"
				description="Which project this subscription shows under in your cost breakdown. This doesn't change your invoice — every subscription bills on your one consolidated invoice."
			/>
		</template>
	</Dialog>
</template>
