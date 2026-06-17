<script setup>
import { FrappeUIProvider, Dialogs } from 'frappe-ui'
</script>

<template>
  <FrappeUIProvider>
    <router-view />
    <!-- Renders confirmDialog() overlays mounted imperatively. -->
    <Dialogs />
  </FrappeUIProvider>
</template>
