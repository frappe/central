<script setup lang="ts">
import {
	Alert,
	Button,
	Checkbox,
	Dialog,
	LoadingText,
	ScrollArea,
	TextInput,
} from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { useTeamRoles } from '@/composables/useTeamRoles'
import {
	capabilityLabel,
	groupCapabilitiesByCategory,
} from '@/lib/capabilities'
import { getErrorMessage } from '@/lib/feedback'
import { __ } from '@/lib/translate'

interface RoleBuilderDialogProps {
	open: boolean
}

const props = defineProps<RoleBuilderDialogProps>()
const emit = defineEmits<{ 'update:open': [v: boolean]; created: [] }>()

const {
	capabilities,
	capabilitiesLoading,
	capabilitiesError,
	reloadCapabilities,
	creating,
	createRole,
} = useTeamRoles()

const open = computed({
	get: () => props.open,
	set: (v: boolean) => emit('update:open', v),
})

const roleName = ref('')
const picked = ref<string[]>([])
const formError = ref('')

watch(open, (isOpen) => {
	if (isOpen) {
		roleName.value = ''
		picked.value = []
		formError.value = ''
	}
})
watch([roleName, picked], () => (formError.value = ''), { deep: true })

const groups = computed(() => groupCapabilitiesByCategory(capabilities.value))

function toggle(cap: string, checked: boolean) {
	if (checked) {
		if (!picked.value.includes(cap)) picked.value = [...picked.value, cap]
	} else {
		picked.value = picked.value.filter((c) => c !== cap)
	}
}

const canSubmit = computed(
	() => roleName.value.trim().length > 0 && picked.value.length > 0,
)

const dialogOptions = computed(() => ({
	title: __('New custom role'),
	size: 'xl' as const,
	actions: [
		{
			label: __('Create role'),
			variant: 'solid' as const,
			disabled: !canSubmit.value || creating.value,
			loading: creating.value,
			onClick: submit,
		},
	],
}))

async function submit() {
	if (!canSubmit.value || creating.value) return
	try {
		await createRole(roleName.value.trim(), picked.value)
		emit('created')
		open.value = false
	} catch (e) {
		formError.value = getErrorMessage(e, "The role couldn't be created.")
	}
}

const createRoleErrorTitle = __("Couldn't create the role")
const loadPermissionsErrorTitle = __("Couldn't load the permissions")
</script>

<template>
	<Dialog
		v-model="open"
		:title="dialogOptions.title"
		:size="dialogOptions.size"
		:actions="dialogOptions.actions"
		:dismissible="!creating"
		:show-close-button="!creating"
	>
		<template #default>
			<div class="space-y-5">
				<Alert
					v-if="formError"
					theme="red"
					:title="createRoleErrorTitle"
					:description="formError"
				/>
				<TextInput
					v-model="roleName"
					autofocus
					:label="__('Role name')"
					:placeholder="__('e.g. Release Manager')"
					:disabled="creating"
				/>

				<div>
					<p class="mb-1 text-base-medium text-ink-gray-7">
						{{ __('Permissions') }}
					</p>
					<p class="mb-3 text-p-sm text-ink-gray-5">
						{{ __('Choose what members with this role can do. Required view permissions are included.') }}
					</p>
					<Alert
						v-if="capabilitiesError"
						theme="red"
						:title="loadPermissionsErrorTitle"
						:description="capabilitiesError"
					/>
					<Button
						v-if="capabilitiesError"
						:label="__('Retry')"
						@click="reloadCapabilities"
						class="mt-2"
					/>
					<LoadingText
						v-else-if="capabilitiesLoading && !groups.length"
						:lines="3"
					/>
					<p v-else-if="!groups.length" class="text-p-sm text-ink-gray-6">
						{{ __('No permissions are available. Contact your administrator.') }}
					</p>
					<ScrollArea
						v-else
						class="-mr-4 sm:-mr-6"
						viewport-class="max-h-[50vh] pr-4 sm:pr-6"
					>
						<div class="space-y-4">
							<section v-for="group in groups" :key="group.label">
								<h4 class="mb-2 text-xs-medium uppercase text-ink-gray-4">
									{{ group.label }}
								</h4>
								<ul class="space-y-2.5">
									<li v-for="cap in group.caps" :key="cap.name">
										<Checkbox
											:label="capabilityLabel(cap)"
											:disabled="creating"
											:model-value="picked.includes(cap.name)"
											@update:model-value="toggle(cap.name, Boolean($event))"
										/>
									</li>
								</ul>
							</section>
						</div>
					</ScrollArea>
				</div>
			</div>
		</template>
	</Dialog>
</template>
