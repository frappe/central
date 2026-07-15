<script setup lang="ts">
import { Button } from 'frappe-ui'
import type { ProviderLogin } from '@/types/api'

defineProps<{
	providers: readonly ProviderLogin[]
	prefix: string
}>()

function openProvider(url: string) {
	window.location.href = url
}
</script>

<template>
	<template v-if="providers.length">
		<div class="my-6 flex items-center gap-3">
			<span class="h-px flex-1 bg-surface-gray-3" />
			<span class="text-p-sm text-ink-gray-5">or</span>
			<span class="h-px flex-1 bg-surface-gray-3" />
		</div>

		<div class="space-y-3">
			<Button
				v-for="provider in providers"
				:key="provider.name"
				variant="outline"
				size="md"
				class="w-full"
				@click="openProvider(provider.auth_url)"
			>
				<template #prefix>
					<img
						v-if="provider.icon"
						:src="provider.icon"
						alt=""
						class="size-4 object-contain"
					/>
				</template>
				{{ prefix }} {{ provider.label }}
			</Button>
		</div>
	</template>
</template>
