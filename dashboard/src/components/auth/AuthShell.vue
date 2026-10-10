<script setup lang="ts">
import frappeCloudLogo from '@/assets/fc-logo.svg'

interface AuthShellProps {
	step?: number
	steps?: number
	showProgress?: boolean
}

withDefaults(defineProps<AuthShellProps>(), {
	step: 1,
	steps: 4,
	showProgress: false,
})
</script>

<template>
	<main class="flex min-h-screen flex-col bg-surface-base px-4">
		<section class="mx-auto w-full max-w-[384px] flex-1 pb-12 pt-16 sm:pt-24">
			<div
				v-if="showProgress"
				class="mb-12 flex gap-2"
				aria-label="Signup progress"
			>
				<span
					v-for="index in steps"
					:key="index"
					class="h-1 flex-1 rounded-4"
					:class="index <= step ? 'bg-surface-gray-6' : 'bg-surface-gray-3'"
				/>
			</div>

			<slot />
		</section>

		<footer class="flex items-center justify-center gap-2 py-8">
			<img
				:src="frappeCloudLogo"
				alt=""
				class="h-6 w-6 rounded-4 object-contain"
			/>
			<span class="text-base font-semibold text-ink-gray-8">Frappe Cloud</span>
		</footer>
	</main>
</template>
