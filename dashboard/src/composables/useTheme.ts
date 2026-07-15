import { useTheme as useFrappeUITheme } from 'frappe-ui'

// All theme logic for the console lives here, wrapping frappe-ui's useTheme.
// The app — including the pre-login AuthShell — defaults to light; frappe-ui
// would otherwise follow the OS theme and render dark on dark-mode machines.
// We only seed the default, so a theme the user later picks is still restored
// on every load. The first call (from main.ts) runs before frappe-ui reads the
// stored value, so the default is in place before the initial paint.
export function useTheme() {
	if (!localStorage.getItem('theme')) {
		localStorage.setItem('theme', 'light')
	}
	return useFrappeUITheme()
}
