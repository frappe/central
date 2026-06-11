<script setup>
import { ref, computed } from 'vue'
import { useCall } from 'frappe-ui'
import SwitchTeamDialog from '@/components/SwitchTeamDialog.vue'
import { API, m } from '@/api/endpoints'
import { useTeam } from '@/composables/useTeam'

// The clickable team chip in the sidebar; opens the full Switch Team dialog.
const { currentTeam, homeTeam, isOperator } = useTeam()
const teams = useCall({ url: m(API.myTeams) })

const label = computed(() => {
  const t = (teams.data || []).find((x) => x.name === currentTeam.value)
  return t?.label || currentTeam.value || '…'
})
const impersonating = computed(
  () => currentTeam.value && homeTeam.value && currentTeam.value !== homeTeam.value,
)

const showDialog = ref(false)
</script>

<template>
  <!-- Single root so the parent's spacing class (mb-4) binds; the dialog teleports
       to <body>, so it doesn't affect layout here. -->
  <div>
    <button
      class="flex w-full items-center gap-2 rounded border border-outline-gray-2 bg-surface-white px-2.5 py-2 text-left hover:border-outline-gray-3"
      @click="showDialog = true"
    >
      <span class="flex size-7 shrink-0 items-center justify-center rounded bg-surface-gray-3 text-sm text-ink-gray-7">
        {{ (label || '?').charAt(0).toUpperCase() }}
      </span>
      <span class="min-w-0 flex-1">
        <span class="block truncate text-sm text-ink-gray-8">{{ label }}</span>
        <span class="block text-p-sm" :class="impersonating ? 'text-ink-amber-3' : 'text-ink-gray-5'">
          {{ impersonating ? 'Impersonating' : 'Change team' }}
        </span>
      </span>
      <span class="lucide-chevrons-up-down size-4 text-ink-gray-5" />
    </button>

    <SwitchTeamDialog v-model="showDialog" />
  </div>
</template>
