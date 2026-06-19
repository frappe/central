<script setup lang="ts">
import { computed } from 'vue'
import { Sidebar, ToastProvider } from 'frappe-ui'
import { useSession } from '@/composables/useSession'
import { useCapabilities } from '@/composables/useCapabilities'

// App shell: the new frappe-ui Sidebar (collapsible, Espresso design system) +
// the routed page. Sections are capability-gated — we only surface what the
// signed-in user can act on. Servers is the only surface for now.
const { activeTeamLabel } = useSession()
const { canViewServers } = useCapabilities()

const header = computed(() => ({
  title: 'Central Console',
  subtitle: activeTeamLabel.value,
}))

const sections = computed(() => [
  {
    label: 'Compute',
    items: [
      {
        label: 'Servers',
        icon: 'lucide-server',
        to: '/servers',
        condition: () => canViewServers.value,
      },
    ],
  },
])
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-surface-white text-ink-gray-9">
    <Sidebar :header="header" :sections="sections" />
    <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <router-view />
    </main>
    <ToastProvider />
  </div>
</template>
