<script setup lang="ts">
import { Skeleton } from 'frappe-ui'
</script>

<template>
	<section
		class="rounded-7 border border-outline-gray-2 p-5"
		aria-busy="true"
		aria-label="Loading snapshots"
	>
		<div class="mb-5 flex items-center justify-between gap-3">
			<Skeleton class="h-4 w-24 rounded-4" />
			<div class="flex items-center gap-2">
				<Skeleton class="h-7 w-28 rounded-4" />
				<Skeleton class="h-7 w-16 rounded-4" />
			</div>
		</div>
		<div class="space-y-3.5">
			<div
				v-for="n in 3"
				:key="n"
				class="flex items-center justify-between gap-4"
			>
				<Skeleton class="h-3 w-20 rounded-4" />
				<Skeleton class="h-3 w-40 rounded-4" />
			</div>
		</div>
	</section>
</template>
