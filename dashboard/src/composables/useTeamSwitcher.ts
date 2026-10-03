import { ref } from 'vue'

export const teamSwitcherOpen = ref(false)

export const openTeamSwitcher = (): void => {
	teamSwitcherOpen.value = true
}
