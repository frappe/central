import frappeUIPreset from 'frappe-ui/tailwind'

/** @type {import('tailwindcss').Config} */
export default {
	presets: [frappeUIPreset],
	content: [
		'./index.html',
		'./src/**/*.{vue,js,ts,jsx,tsx}',
		'./node_modules/frappe-ui/src/**/*.{vue,js,ts,jsx,tsx}',
		'./node_modules/frappe-ui/frappe/**/*.{vue,js,ts,jsx,tsx}',
		// The experimental family (ListView, Accordion, CodeEditor …) ships its own
		// utilities. Left unscanned, classes used only there — min-w-full on ListView's
		// grid, for one — never compile, and the component silently mis-sizes.
		'./node_modules/frappe-ui/experimental/**/*.{vue,js,ts,jsx,tsx}',
	],
}
