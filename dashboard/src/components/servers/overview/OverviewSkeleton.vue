<script setup lang="ts">
import { Skeleton } from 'frappe-ui'
</script>

<template>
	<div class="space-y-4" aria-busy="true" aria-label="Loading server overview">
		<section class="rounded-7 border border-outline-gray-2 p-5">
			<div class="mb-5 flex items-center justify-between gap-3">
				<Skeleton class="h-4 w-28 rounded-4" />
				<Skeleton class="h-3 w-24 rounded-4" />
			</div>
			<div class="space-y-5">
				<div v-for="n in 3" :key="n" class="space-y-2">
					<div class="flex items-center justify-between gap-4">
						<Skeleton class="h-3 w-16 rounded-4" />
						<Skeleton class="h-3 w-28 rounded-4" />
					</div>
					<Skeleton class="h-1 w-full rounded-full" />
				</div>
			</div>
		</section>

		<div class="grid gap-4 md:grid-cols-2">
			<section class="rounded-7 border border-outline-gray-2 p-5">
				<Skeleton class="mb-5 h-4 w-36 rounded-4" />
				<div class="space-y-3.5">
					<div
						v-for="n in 6"
						:key="n"
						class="flex items-center justify-between gap-4"
					>
						<Skeleton class="h-3 w-20 rounded-4" />
						<Skeleton class="h-3 w-32 rounded-4" />
					</div>
				</div>
			</section>

			<section class="rounded-7 border border-outline-gray-2 p-5">
				<div class="mb-4 flex items-center justify-between gap-3">
					<Skeleton class="h-4 w-28 rounded-4" />
					<Skeleton class="h-3 w-16 rounded-4" />
				</div>
				<Skeleton class="h-40 w-full rounded-6" />
				<div class="mt-4 flex gap-4">
					<Skeleton v-for="n in 3" :key="n" class="h-3 w-16 rounded-4" />
				</div>
			</section>
		</div>
	</div>
</template>
