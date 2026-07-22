<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Dialog, Spinner } from 'frappe-ui'
import ConnectionDetails from '@/components/services/ConnectionDetails.vue'
import { useServices } from '@/composables/useServices'
import { getErrorMessage } from '@/lib/toast'
import type { ServiceModel, SiteCredential } from '@/composables/useServices'

// A site's connection details: fetch its stored credential (service:manage) on open,
// then render the shared ConnectionDetails body (URL + key + curl).
const props = defineProps<{
	open: boolean
	managedService: string
	site: string
	models: ServiceModel[]
}>()

const emit = defineEmits<{ 'update:open': [value: boolean] }>()

const open = computed({
	get: () => props.open,
	set: (v: boolean) => emit('update:open', v),
})

const { fetchCredential } = useServices()

const loading = ref(false)
const error = ref('')
const credential = ref<SiteCredential | null>(null)

watch(
	() => props.open,
	async (isOpen) => {
		if (!isOpen) return
		error.value = ''
		loading.value = true
		try {
			credential.value = await fetchCredential(props.managedService, props.site)
		} catch (e) {
			error.value = getErrorMessage(e)
		} finally {
			loading.value = false
		}
	},
)
</script>

<template>
	<Dialog v-model="open" :title="`Connect to ${site}`" size="2xl">
		<template #default>
			<div v-if="loading" class="flex items-center gap-2 py-8 text-ink-gray-5">
				<Spinner class="size-4" />
				<span class="text-p-sm">Loading connection details…</span>
			</div>
			<p v-else-if="error" class="py-6 text-p-sm text-ink-red-3">{{ error }}</p>
			<ConnectionDetails
				v-else-if="credential"
				:gateway-url="credential.gateway_url"
				:api-key="credential.api_key"
				:models="models"
			/>
		</template>
	</Dialog>
</template>
