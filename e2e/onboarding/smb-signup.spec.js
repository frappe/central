import { test, expect } from "@playwright/test";

// Signup routing, driven against the real bench with NO MOCKS. It uses the
// developer_mode OTP bypass (any 6 digits), so no mailbox is needed.
//
// The site-provisioning screens (subdomain availability + the Running handoff)
// need a configured Atlas region — an active Root Domain and a golden bench
// snapshot — which a laptop bench usually lacks. That half is covered by the live
// Central→Atlas backend check and Atlas's host-proven self_serve_site e2e; this
// spec stops once onboarding reaches "Name your site".
//
//   yarn test:e2e e2e/onboarding   # needs `bench start` and developer_mode on

// Unique per run: sign_up rejects an existing User, so a fixed email would only
// pass once.
const uniqueEmail = () => `smb-${Date.now()}@example.com`;

test("product signup → OTP verify → reaches Name your site", async ({ page }) => {
	const email = uniqueEmail();

	await page.goto("/dashboard/signup?product=erpnext");
	await page.getByLabel("Full name").fill("SMB Tester");
	await page.getByLabel("Work email").fill(email);
	await page.getByRole("button", { name: "Continue" }).click();

	await expect(page.getByRole("heading", { name: "Verify your email" })).toBeVisible();
	await expect(page.getByText(email)).toBeVisible();

	// Typing 6 digits fills the PIN inputs and fires @complete → verify().
	await page.locator("[data-otp-input]").first().click();
	await page.keyboard.type("123456");

	// verify() creates the User + personal Team, logs in, and full-navigates to the
	// authenticated onboarding route.
	await expect(page.getByRole("heading", { name: "Name your site" })).toBeVisible();
});

test("central signup → OTP verify → reaches Servers", async ({ page }) => {
	const email = uniqueEmail();

	await page.goto("/dashboard/signup");
	await page.getByLabel("Full name").fill("Central Tester");
	await page.getByLabel("Work email").fill(email);
	await page.getByRole("button", { name: "Continue" }).click();

	await expect(page.getByRole("heading", { name: "Verify your email" })).toBeVisible();

	await page.locator("[data-otp-input]").first().click();
	await page.keyboard.type("123456");

	await expect(page).toHaveURL(/\/dashboard\/servers$/);
	await expect(page.getByRole("heading", { name: "Servers" })).toBeVisible();
});
