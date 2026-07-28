import { test, expect } from "./fixtures";

// Refunds (issue #15). Both paths start from a real charge: a card is charged to a
// genuine PaymentIntent and the invoice settles via the real webhook. A full
// dispute then issues a real Stripe refund of that PaymentIntent (the attempt goes
// Refunded; the invoice stays Paid). A partial overcharge instead books the
// difference as a wallet credit, applied next cycle. Refunds are an operator action
// (no customer button), so the spec issues them via the backend and asserts the
// customer-visible result on the dashboard.
const open = (page) => page.locator("ul.divide-y > li");

async function chargeAndSettle(billing) {
	const { team } = await billing.signIn({ scenario: "ready", currency: "USD" });
	await billing.saveCard({ team });
	const { invoice } = await billing.makeInvoice({ team, total: 1180, linkCard: 1 });
	const res = await billing.settle({ team, invoice, collect: 1 }); // real PaymentIntent
	await billing.deliverWebhook({ attempt: res.attempt }); // Open → Paid
	return { team, invoice, attempt: res.attempt };
}

// TODO: legacy dashboard removed; these flows (billing/invoices, billing/credits)
// aren't ported to console yet. Un-skip once console has them.
test.describe.skip("Refunds", () => {
	test("full dispute refunds to source; the invoice stays Paid", async ({ page, billing }) => {
		const { invoice, attempt } = await chargeAndSettle(billing);

		const res = await billing.refund({ attempt, destination: "Source" }); // real Stripe refund
		expect(res.status).toBe("Completed");

		// The invoice is still Paid, and its activity timeline records the refund.
		await page.goto("/legacy-dashboard/billing/invoices");
		await open(page).filter({ hasText: "Paid" }).click();
		await expect(page.getByText("Payment refunded")).toBeVisible();
	});

	test("partial overcharge is credited back to the wallet", async ({ page, billing }) => {
		const { attempt } = await chargeAndSettle(billing);

		const res = await billing.refund({ attempt, amount: 200, destination: "Wallet" });
		expect(res.status).toBe("Completed");

		// The $200 overcharge correction shows as a wallet credit, applied next cycle.
		await page.goto("/legacy-dashboard/billing/credits");
		await expect(page.getByText("$200.00").first()).toBeVisible();
		await expect(page.getByText(/Overcharge refund/)).toBeVisible();
	});
});
