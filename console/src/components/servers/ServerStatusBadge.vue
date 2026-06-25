<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { statusTheme, type AssetStatus } from '@/lib/status'

const props = defineProps<{ status: AssetStatus }>()
</script>

<template>
  <Badge :theme="statusTheme(props.status)" :label="props.status" variant="subtle" />
</template>
