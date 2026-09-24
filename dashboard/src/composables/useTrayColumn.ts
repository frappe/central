import { type Ref, ref, watch } from 'vue'

export function useTrayColumn<Name extends string>(): {
	tray: Ref<Name | null>
	shown: Ref<Name | null>
	onClosed: () => void
} {
	const tray = ref(null) as Ref<Name | null>

	// Trails `tray` through the slide-out so the closing panel keeps its body
	// instead of blanking; cleared once it has left, so a reopen mounts fresh.
	const shown = ref(null) as Ref<Name | null>
	watch(tray, (name) => {
		if (name) shown.value = name
	})

	function onClosed(): void {
		shown.value = null
	}

	return { tray, shown, onClosed }
}
