<script setup lang="ts">
import { Button, Select } from 'frappe-ui'

defineProps<{
  page: number
  pageCount: number
  pageSize: number
  canPrevious: boolean
  canNext: boolean
}>()

defineEmits<{
  first: []
  previous: []
  next: []
  last: []
  pageSizeChange: [pageSize: number]
}>()
</script>

<template>
  <footer
    class="flex flex-wrap items-center justify-end gap-3 border-t border-outline-gray-1 py-2.5"
  >
    <div class="flex items-center gap-1.5">
      <Select
        :model-value="pageSize"
        class="mr-2 w-24"
        variant="ghost"
        :options="[10, 20, 50].map((value) => ({ label: `${value} rows`, value }))"
        @update:model-value="$emit('pageSizeChange', Number($event))"
      />
      <span class="mr-2 text-p-sm text-ink-gray-5">
        Page {{ page }} of {{ Math.max(pageCount, 1) }}
      </span>
      <Button
        icon="lucide-chevrons-left"
        variant="ghost"
        tooltip="First page"
        :disabled="!canPrevious"
        @click="$emit('first')"
      />
      <Button
        icon="lucide-chevron-left"
        variant="ghost"
        tooltip="Previous page"
        :disabled="!canPrevious"
        @click="$emit('previous')"
      />
      <Button
        icon="lucide-chevron-right"
        variant="ghost"
        tooltip="Next page"
        :disabled="!canNext"
        @click="$emit('next')"
      />
      <Button
        icon="lucide-chevrons-right"
        variant="ghost"
        tooltip="Last page"
        :disabled="!canNext"
        @click="$emit('last')"
      />
    </div>
  </footer>
</template>
