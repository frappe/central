<script setup lang="ts">
import { Dialog, FormControl, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { errorToast } from '@/lib/toast'
import type { Project } from '@/types/billing'

// Edit a Project: its title and its spending_limit are the only two knobs a
// team member has over an existing one, so one dialog covers both rather than
// splitting rename from limit-editing across two entry points. Controlled by
// the card: pass the project being edited (or null) via v-model:project.
// Neither field changes what the project bills — title is cosmetic, and the
// limit only gates tagging NEW resources in (Subscription.validate_project);
// it never touches resources already tagged into the project.
const props = defineProps<{ project: Project | null }>()
const emit = defineEmits<{
	'update:project': [project: Project | null]
	saved: []
}>()

const open = computed({
	get: () => !!props.project,
	set: (v: boolean) => {
		if (!v) emit('update:project', null)
	},
})

const title = ref('')
const spendingLimit = ref<number | null>(null)
watch(
	() => props.project,
	(project) => {
		if (project) {
			title.value = project.title
			spendingLimit.value = project.spending_limit || null
		}
	},
)

const titleChanged = computed(
	() =>
		title.value.trim().length > 0 && title.value.trim() !== props.project?.title,
)
const limitChanged = computed(
	() => (spendingLimit.value || 0) !== (props.project?.spending_limit || 0),
)
const canSubmit = computed(
	() => title.value.trim().length > 0 && (titleChanged.value || limitChanged.value),
)

const rename = useCall<unknown, { name: string; title: string }>({
	url: method(API.renameProject),
	method: 'POST',
	immediate: false,
})
const setLimit = useCall<unknown, { name: string; spending_limit: number }>({
	url: method(API.setProjectSpendingLimit),
	method: 'POST',
	immediate: false,
})
const saving = computed(() => rename.loading || setLimit.loading)

async function submit(): Promise<void> {
	if (!props.project || !canSubmit.value) return
	try {
		if (titleChanged.value)
			await rename.submit({ name: props.project.name, title: title.value.trim() })
		if (rename.error) throw rename.error
		if (limitChanged.value)
			await setLimit.submit({
				name: props.project.name,
				spending_limit: spendingLimit.value || 0,
			})
		if (setLimit.error) throw setLimit.error
		emit('update:project', null)
		emit('saved')
	} catch (e) {
		errorToast(e)
	}
}

const dialogOptions = computed(() => ({
	title: 'Edit project',
	actions: [
		{
			label: 'Save',
			variant: 'solid' as const,
			loading: saving.value,
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
				<FormControl v-model="title" label="Title" @keyup.enter="submit" />
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
