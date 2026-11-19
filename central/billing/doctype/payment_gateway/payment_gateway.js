// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Payment Gateway", {
	refresh(frm) {
		// A PayPal gateway that settles through Razorpay has no webhook of its own.
		const via_razorpay = frm.doc.adapter_key === "Paypal" && frm.doc.paypal_settlement_mode === "Via Razorpay";
		if (frm.is_new() || via_razorpay) return;

		const label = frm.doc.webhook_endpoint_id ? __("Re-register Webhook") : __("Register Webhook");
		frm.add_custom_button(label, () => reregister(frm));

		const group = __("Webhook Events");
		frm.add_custom_button(__("Pull"), () => run(frm, "pull_webhook_events"), group);
		frm.add_custom_button(__("Update"), () => run(frm, "update_webhook_events"), group);
	},
});

function run(frm, method) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the gateway first."));
		return;
	}
	frm.call({ method, doc: frm.doc, freeze: true }).then(({ message }) => {
		frm.reload_doc();
		show_report(message);
	});
}

function reregister(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the gateway first."));
		return;
	}
	const message = frm.doc.webhook_endpoint_id
		? __(
				"Create a new webhook endpoint with a new signing secret? The current endpoint is not deleted at the gateway. Its events will fail the signature check until you remove it."
			)
		: __("Register a webhook endpoint at the gateway for this site?");
	frappe.confirm(message, () =>
		frm.call({ method: "revalidate_and_register_webhook", doc: frm.doc, freeze: true }).then(({ message: result }) => {
			frm.reload_doc();
			if (result?.registered) {
				frappe.show_alert({ message: __("Webhook {0} registered", [result.webhook_endpoint_id]), indicator: "green" });
			} else {
				frappe.msgprint({
					title: __("Webhook Not Registered"),
					indicator: "orange",
					message: __("No new endpoint was registered, so the current one is kept."),
				});
			}
		})
	);
}

function show_report(report) {
	if (!report) return;
	const problems = [];
	if (!report.is_active) problems.push(__("The endpoint is disabled at the gateway."));
	if (!report.url_matches) {
		problems.push(__("The endpoint sends events to another URL. Central expects {0}.", [report.expected_url]));
	}
	if (report.missing.length) {
		problems.push(__("Missing events: {0}. Use Update Webhook Events.", [report.missing.join(", ")]));
	}
	frappe.msgprint({
		title: __("Webhook Events"),
		indicator: problems.length ? "orange" : "green",
		message: problems.length
			? problems.map((line) => frappe.utils.escape_html(line)).join("<br>")
			: __("The endpoint is active and sends every event Central needs."),
	});
}
