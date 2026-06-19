<script setup lang="ts">
import { Badge } from 'frappe-ui'
import { statusTheme } from '@/lib/status'
import type { ServerStatus } from '@/types'

const props = defineProps<{ status: ServerStatus }>()
</script>

<template>
  <Badge :theme="statusTheme(props.status)" :label="props.status" variant="subtle" />
</template>
