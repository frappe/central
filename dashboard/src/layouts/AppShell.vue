<script setup lang="ts">
import { ToastProvider } from "frappe-ui";
import Sidebar from "@/components/navigation/Sidebar.vue";
import { useNotificationsRealtime } from "@/composables/useNotifications";

// App shell: the new frappe-ui Sidebar (collapsible, Espresso design system) +
// the routed page. The header doubles as the team switcher — switching re-drives

// Live notification badge — subscribe once from the app's single stable mount
// (needs a component instance for the socket, so it can't run at module scope).
useNotificationsRealtime();
</script>

<template>
  <!-- `isolate`: a stacking context here contains the sidebar's z-10 (below), so it
       can't leak to the body level and paint over body-teleported popovers — the team
       switcher dropdown was rendering behind the sidebar without this. -->
  <div class="isolate flex h-screen overflow-hidden bg-surface-base text-ink-gray-9">
    <!-- Collapse control: the whole right edge is the trigger; the chevron
         rides the cursor. The built-in bottom item is hidden below. z-10 lifts
         the sidebar's whole stacking context above the main pane — pages that
         isolate themselves (the map) otherwise paint over the knob's overhang,
         since later DOM order wins at equal z. -->
    <Sidebar/>

    <main class="flex min-w-0 flex-1 flex-col overflow-hidden">
      <router-view />
    </main>
    <ToastProvider />
  </div>
</template>
