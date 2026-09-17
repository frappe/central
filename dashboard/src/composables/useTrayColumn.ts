import { computed, type Ref, ref, type WritableComputedRef } from 'vue'

export function useTrayColumn<Name extends string>(): {
	tray: Ref<Name | null>
	trayModel: (name: Name) => WritableComputedRef<boolean>
} {
	const tray = ref(null) as Ref<Name | null>

	function trayModel(name: Name): WritableComputedRef<boolean> {
		return computed({
			get: () => tray.value === name,
			set: (open: boolean) => {
				if (open) tray.value = name
				else if (tray.value === name) tray.value = null
			},
		})
	}

	return { tray, trayModel }
}
