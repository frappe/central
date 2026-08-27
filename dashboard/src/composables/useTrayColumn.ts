import { computed, provide, ref, type Ref, type WritableComputedRef } from 'vue'
import { SIDE_PANEL_SWITCHING } from '@/components/common/SidePanel.vue'

export function useTrayColumn<Name extends string>(): {
	tray: Ref<Name | null>
	trayModel: (name: Name) => WritableComputedRef<boolean>
} {
	const tray = ref(null) as Ref<Name | null>
	const switching = ref(false)
	provide(SIDE_PANEL_SWITCHING, switching)

	function trayModel(name: Name): WritableComputedRef<boolean> {
		return computed({
			get: () => tray.value === name,
			set: (open: boolean) => {
				if (open) {
					switching.value = tray.value !== null && tray.value !== name
					tray.value = name
				} else if (tray.value === name) {
					switching.value = false
					tray.value = null
				}
			},
		})
	}

	return { tray, trayModel }
}
