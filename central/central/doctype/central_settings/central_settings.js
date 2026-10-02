// Copyright (c) 2026, frappe and contributors
// For license information, please see license.txt

frappe.ui.form.on("Central Settings", {
	refresh(frm) {
		const wrapper = frm.fields_dict.pilot_rollout_progress.$wrapper.empty();
		const rollout = frm.doc.__onload?.pilot_rollout;
		if (!rollout) return;

		add_pilot_rollout_buttons(frm);
		const { group, updated, failed } = rollout;
		const width = (count) => `${group ? (count * 100) / group : 0}%`;
		wrapper.html(`
			<div class="progress" style="height: 12px">
				<div class="progress-bar progress-bar-success" style="width: ${width(updated)}" title="${__("Updated")}"></div>
				<div class="progress-bar progress-bar-danger" style="width: ${width(failed)}" title="${__("Failed")}"></div>
			</div>
			<p class="text-muted small mt-2">${__("{0} of {1} servers in the rollout run {2}.", [
				updated,
				group,
				frappe.utils.escape_html(frm.doc.pilot_release_tag),
			])} <a class="pilot-rollout-failed">${__("{0} failed", [failed])}</a></p>
		`);
		wrapper.find(".pilot-rollout-failed").on("click", () =>
			frappe.set_route("List", "Pilot Credential", { pilot_update_error: ["is", "set"] })
		);
	},
});

function add_pilot_rollout_buttons(frm) {
	const tag = frappe.utils.escape_html(frm.doc.pilot_release_tag);
	const confirm_and_save = (question, field, value) =>
		frappe.confirm(question, async () => {
			frm.set_value(field, value);
			await frm.save();
		});

	if (frm.doc.pilot_rollout_halted) {
		frm.add_custom_button(
			__("Resume"),
			() => confirm_and_save(__("Resume offering {0}?", [tag]), "pilot_rollout_halted", 0),
			__("Rollout")
		);
		return;
	}

	frm.add_custom_button(
		__("Halt"),
		() =>
			confirm_and_save(
				__("Stop offering {0} to servers that have not updated yet?", [tag]),
				"pilot_rollout_halted",
				1
			),
		__("Rollout")
	);
	if (frm.doc.pilot_rollout_percent < 100) {
		frm.add_custom_button(
			__("Release to everyone"),
			() => confirm_and_save(__("Release {0} to every server now?", [tag]), "pilot_rollout_percent", 100),
			__("Rollout")
		);
	}
}
