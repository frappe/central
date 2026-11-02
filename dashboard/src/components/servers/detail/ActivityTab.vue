<script setup lang="ts">
import ActivityFeed from '@/components/activity/ActivityFeed.vue'

interface Props {
	resourceId: string
}

defineProps<Props>()
</script>

<template>
	<ActivityFeed scope="server" :resource-id="resourceId" />
</template>
