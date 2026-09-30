<script setup lang="ts">
import { Alert } from 'frappe-ui'
import { computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useErrorAlert } from '@/lib/feedback'

const route = useRoute()
const { error, dismissError } = useErrorAlert()

const primaryAction = computed(() => {
	const current = error.value
	if (!current?.action) return undefined
	return {
		label: current.action.label,
		onClick: () => {
			const action = current.action
			dismissError(current.id)
			void action?.onClick()
		},
	}
})

watch(
	() => route.fullPath,
	() => dismissError(),
)
</script>

<template>
	<Teleport to="body">
		<div
			v-if="error"
			class="pointer-events-none fixed inset-x-0 top-4 z-[200] flex justify-center px-4"
			aria-live="assertive"
		>
			<Alert
				:key="error.id"
				class="pointer-events-auto w-full max-w-xl shadow-sm"
				theme="red"
				:title="error.title"
				:description="error.description"
				:primary-action="primaryAction"
				dismissible
				@dismiss="dismissError(error.id)"
			/>
		</div>
	</Teleport>
</template>
