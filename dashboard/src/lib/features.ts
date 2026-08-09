// Console feature flags, injected at page boot by central/www/dashboard.py from
// the Central Settings single (see window.features in env.d.ts). Static for the
// life of the page — a flag change takes a reload, like the rest of the boot data.
// Default on when the boot data is absent (e.g. the vite dev server, which doesn't
// run get_context), matching the DocType's default.

export interface Features {
	/** The Add-ons area (LLM / storage services). */
	addons: boolean
}

export const features: Features = {
	addons: window.features?.addons ?? true,
}
