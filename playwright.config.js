import { defineConfig, devices } from "@playwright/test";

// End-to-end suite for billing — NO MOCKS. Specs drive the real Frappe-UI
// dashboard against a running `central.local` bench and the real gateway test
// sandboxes (Stripe/Razorpay test keys live in common_site_config.json). The
// bench must already be up (`bench start`); we don't manage it from here because
// it serves many things beyond this suite.
//
//   yarn test:e2e            # headless
//   yarn test:e2e:headed     # watch it drive a real browser
//
// Override the target with E2E_BASE_URL (host must resolve to the site, since
// Frappe routes by Host header — central.local is in /etc/hosts on the dev bench).
const BASE_URL = process.env.E2E_BASE_URL || "http://central.local:8011";

export default defineConfig({
	testDir: "./e2e",
	// The gateway round-trips (real Stripe/Razorpay test calls) are the slow part;
	// give specs and assertions generous ceilings so a live API hop never flakes.
	timeout: 90_000,
	expect: { timeout: 15_000 },
	// Real gateway sandboxes are shared mutable state and rate-limited; run serially
	// so two specs never confirm against Stripe at the same instant.
	workers: 1,
	fullyParallel: false,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 1 : 0,
	reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
	use: {
		baseURL: BASE_URL,
		trace: "retain-on-failure",
		screenshot: "only-on-failure",
		video: "retain-on-failure",
	},
	projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
