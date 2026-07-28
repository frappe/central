import { test, expect } from "./fixtures";

// Set up a UPI Autopay mandate for an INR team. UPI Autopay authorises through
// Razorpay's hosted recurring sheet (the same bot-protected Checkout the top-up
// uses), so we drive the real UI until the genuine recurring sheet opens against a
// real order, then confirm the mandate at the gateway boundary (real
// checkout-callback signature; only the recurring token id is synthetic, since
// Razorpay issues one only through the bank/UPI auth flow). The mandate's ceiling
// is the team's trust-tier cap.
// TODO: legacy dashboard removed; settings/methods isn't ported to console yet.
// Un-skip once console has it.
test.describe.skip("UPI Autopay mandate", () => {
	test("authorises a mandate via the real Razorpay recurring sheet", async ({
		page,
		billing,
	}) => {
		const { team } = await billing.signIn({ scenario: "ready", currency: "INR" });
		await billing.setTrustTier({ team, maxSpend: 50000 }); // UPI cap, below the ₹1,00,000 limit

		await page.goto("/legacy-dashboard/settings/methods");
		await expect(page.getByText("No payment methods yet.")).toBeVisible();

		// Open the add dialog and choose UPI Autopay; capture the real recurring order.
		await page.getByRole("button", { name: "Add method" }).click();
		const dialog = page.getByRole("dialog");
		await expect(dialog.getByText("Recurring mandate up to")).toBeVisible();
		const setupResp = page.waitForResponse((r) =>
			r.url().includes("setup_payment_method_order")
		);
		await dialog.getByText("UPI Autopay", { exact: true }).click();
		const order = (await (await setupResp).json()).data;
		expect(order.recurring).toBe(1); // a genuine Razorpay recurring order
		expect(order.payment_method).toBeTruthy();

		// The real Razorpay recurring sheet opens against that order.
		await expect
			.poll(
				() =>
					page
						.frames()
						.some((f) => /api\.razorpay\.com\/v1\/checkout\/public/.test(f.url())),
				{ timeout: 20_000 }
			)
			.toBe(true);

		// Confirm the authorisation at the gateway boundary → mandate goes Active.
		const res = await billing.finishMandate({
			paymentMethod: order.payment_method,
			orderId: order.order_id,
		});
		expect(res.status).toBe("Active");
		expect(res.mandate_max_amount).toBe(50000);

		// The active UPI Autopay mandate now shows in the methods list as the default.
		await page.goto("/legacy-dashboard/settings/methods");
		await expect(page.getByText("No payment methods yet.")).toHaveCount(0);
		const row = page.locator("ul li").filter({ hasText: "UPI Autopay" });
		await expect(row).toHaveCount(1);
		await expect(row.getByText("Default")).toBeVisible();
	});
});
