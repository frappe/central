<script setup>
import { computed } from 'vue'
import { Dropdown } from 'frappe-ui'
import { useTeam } from '@/composables/useTeam'

const { currentTeam, setTeam, teams } = useTeam()

const options = computed(() =>
  (teams.data ?? []).map((t) => ({
    label: t.team,
    onClick: () => setTeam(t.team),
  })),
)
</script>

<template>
  <Dropdown :options="options" placement="left">
    <button
      class="flex w-full items-center justify-between gap-2 rounded border border-outline-gray-2 px-2 py-1.5 text-left text-base text-ink-gray-8 hover:bg-surface-gray-2"
    >
      <span class="flex items-center gap-2 truncate">
        <span class="lucide-users size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
        <span class="truncate">{{ currentTeam || 'Select team' }}</span>
      </span>
      <span class="lucide-chevrons-up-down size-4 shrink-0 text-ink-gray-5" aria-hidden="true" />
    </button>
  </Dropdown>
</template>
