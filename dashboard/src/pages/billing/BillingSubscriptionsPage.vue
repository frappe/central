<script setup lang="ts">
import { ScrollArea } from 'frappe-ui'
import PayingForCard from '@/components/billing/PayingForCard.vue'
</script>

<template>
	<ScrollArea class="h-full">
		<div class="p-3 md:p-4">
			<PayingForCard full />
		</div>
	</ScrollArea>
</template>
