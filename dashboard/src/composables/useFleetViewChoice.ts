import { computed, ref } from 'vue'

export type FleetView = 'map' | 'list'
export type FleetViewChoice = FleetView | 'auto'

const FLEET_VIEW_KEY = 'central.console.serverFleetView'

const readChoice = (): FleetViewChoice => {
	const stored = localStorage.getItem(FLEET_VIEW_KEY)

	return stored === 'map' || stored === 'list' ? stored : 'auto'
}

const choice = ref<FleetViewChoice>(readChoice())

export const fleetViewChoice = computed({
	get: () => choice.value,
	set: (next: FleetViewChoice) => {
		choice.value = next

		if (next === 'auto') localStorage.removeItem(FLEET_VIEW_KEY)
		else localStorage.setItem(FLEET_VIEW_KEY, next)
	},
})
