<script setup>
import { ref } from 'vue'
import TeamSwitcher from '@/components/TeamSwitcher.vue'
import NavLink from '@/components/NavLink.vue'
import { useCapabilities } from '@/composables/useCapabilities'

const { canView, canViewTeam, canViewAtlas } = useCapabilities()

// Below sm: the sidebar collapses to a toggled drawer (slides from the left).
const drawerOpen = ref(false)

const billing = [
  { to: '/billing', label: 'Overview', icon: 'lucide-layout-dashboard' },
  { to: '/billing/invoices', label: 'Invoices', icon: 'lucide-file-text' },
  { to: '/billing/methods', label: 'Payment Methods', icon: 'lucide-credit-card' },
  { to: '/billing/credits', label: 'Credits', icon: 'lucide-wallet' },
  { to: '/billing/payments', label: 'Payment History', icon: 'lucide-receipt' },
  { to: '/billing/subscriptions', label: 'Subscriptions', icon: 'lucide-repeat' },
  { to: '/billing/settings', label: 'Settings', icon: 'lucide-settings' },
]
const team = [
  { to: '/team/members', label: 'Members', icon: 'lucide-user' },
  { to: '/team/roles', label: 'Roles', icon: 'lucide-shield' },
  { to: '/team/trust-tier', label: 'Trust Tier', icon: 'lucide-star' },
]
const atlas = [
  { to: '/atlas', label: 'Registry', icon: 'lucide-box' },
  { to: '/atlas/vms', label: 'Virtual Machines', icon: 'lucide-server' },
  { to: '/atlas/region', label: 'Region', icon: 'lucide-globe' },
  { to: '/atlas/access', label: 'Access Requests', icon: 'lucide-key' },
]
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-surface-white text-ink-gray-9">
    <!-- Mobile drawer backdrop -->
    <div
      v-if="drawerOpen"
      class="fixed inset-0 z-20 bg-black/30 sm:hidden"
      @click="drawerOpen = false"
    />

    <!-- Sidebar (LEFT, fixed). Drawer below sm:. -->
    <aside
      class="fixed inset-y-0 left-0 z-30 flex w-60 shrink-0 flex-col border-r border-outline-gray-1 bg-surface-gray-1 px-3 py-3 transition-transform sm:static sm:translate-x-0"
      :class="drawerOpen ? 'translate-x-0' : '-translate-x-full'"
    >
      <div class="mb-3 flex items-center gap-2 px-1">
        <span class="lucide-circle-gauge size-5 text-ink-gray-8" aria-hidden="true" />
        <span class="text-lg font-medium text-ink-gray-9">Central</span>
      </div>

      <TeamSwitcher class="mb-4" />

      <nav class="flex-1 space-y-5 overflow-y-auto" @click="drawerOpen = false">
        <div v-if="canView">
          <p class="px-2 pb-1 text-sm font-medium text-ink-gray-5">Billing</p>
          <div class="space-y-0.5">
            <NavLink v-for="i in billing" :key="i.to" v-bind="i" />
          </div>
        </div>

        <div v-if="canViewTeam">
          <p class="px-2 pb-1 text-sm font-medium text-ink-gray-5">Team</p>
          <div class="space-y-0.5">
            <NavLink v-for="i in team" :key="i.to" v-bind="i" />
          </div>
        </div>

        <div v-if="canViewAtlas">
          <p class="px-2 pb-1 text-sm font-medium text-ink-gray-5">Atlas</p>
          <div class="space-y-0.5">
            <NavLink v-for="i in atlas" :key="i.to" v-bind="i" />
          </div>
        </div>
      </nav>
    </aside>

    <!-- Main content -->
    <div class="flex min-w-0 flex-1 flex-col">
      <button
        class="flex min-h-12 items-center gap-2 border-b border-outline-gray-1 px-3 text-ink-gray-7 sm:hidden"
        aria-label="Open menu"
        @click="drawerOpen = true"
      >
        <span class="lucide-menu size-5" aria-hidden="true" />
        <span class="text-base">Menu</span>
      </button>
      <main class="min-h-0 flex-1 overflow-hidden">
        <router-view />
      </main>
    </div>
  </div>
</template>
