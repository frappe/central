import frappe

from central.signups.trial import Trial


def execute() -> None:
	"""Start the trial of a trial site that was still being set up when trials moved to insert:
	it had not answered and nobody had opened it, so its first readiness would have started it.
	A site from before trials existed was already ready or opened, and stays as it is."""
	filters = {
		"trial_state": ["is", "not set"],
		"ready_at": ["is", "not set"],
		"claimed_at": ["is", "not set"],
		"server.status": ["!=", "Terminated"],
	}
	for name in frappe.get_all("Site", filters=filters, pluck="name"):
		site = frappe.get_doc("Site", name)
		Trial(site).start()
		if site.trial_state:
			site.db_set({"trial_state": site.trial_state, "trial_ends_on": site.trial_ends_on})
