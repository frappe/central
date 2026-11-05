import frappe
import requests
from frappe import _

from central.signups.doctype.product.product import get_signup_product
from central.signups.trial import Trial

ACTIVE_TASK_STATES = ("queued", "running")


class TrialAppInstall:
	"""Another product's app on an open trial site, so one free site runs both products.
	The enabled Product names the app, and its title is what the customer reads."""

	def __init__(self, trial: Trial, product: str):
		self.trial = trial
		self.product = get_signup_product(product)

	@property
	def site(self):
		return self.trial.site

	def start(self) -> dict:
		"""Install the product's app, or report it installed when the site has it already.
		Returns the bench's name for the site and the task, which `get_progress` reads."""
		from central.integrations.pilot import get_site_apps, install_site_app

		if self.trial.state != "Active":
			frappe.throw(
				_(
					"Only a running free trial site can get another app. Upgrade to keep your site, then add the app."
				)
			)

		app = self.product.signup_app
		try:
			pilot_site, apps = get_site_apps(self.site.server, self.site.get_pilot_site_names())
			if app in apps:
				return {"site": pilot_site, "task_id": None, "status": "success"}

			install = install_site_app(self.site.server, pilot_site, app)
		# A sleeping server wakes on this call, and a slow wake times out. The customer tries again.
		except requests.RequestException:
			frappe.log_error(
				title="Trial app install failed", reference_doctype="Site", reference_name=self.site.name
			)
			frappe.throw(_("Your site did not answer. Wait a minute, then try again."))

		self.site.add_comment(
			"Info", _("{0} install started (Pilot task {1}).").format(app, install["task_id"])
		)
		return install

	def get_progress(self, pilot_site: str, task_id: str) -> dict:
		"""The install's `status` (queued, running, success, failed, or unreachable when the site
		did not answer this time), its place in the queue, when it started, and customer copy for a failure."""
		from central.integrations.pilot import get_site_task

		if pilot_site not in self.site.get_pilot_site_names():
			frappe.throw(_("This install does not belong to your site."), frappe.PermissionError)

		try:
			task = get_site_task(self.site.server, pilot_site, task_id)
		# The page asks again, and gives up after a while without an answer.
		except requests.RequestException:
			return {"status": "unreachable", "queue_position": None, "started_at": None, "error": None}

		status = task.get("status")
		if status in ACTIVE_TASK_STATES or status == "success":
			return {
				"status": status,
				"queue_position": task.get("queue_position"),
				"started_at": task.get("started_at"),
				"error": None,
			}

		self.record_failure(task_id, (task.get("failure") or {}).get("message"))
		return {
			"status": "failed",
			"queue_position": None,
			"started_at": task.get("started_at"),
			"error": _("{0} could not be installed on your site. Try again in a few minutes.").format(
				self.product.title
			),
		}

	def record_failure(self, task_id: str, reason: str | None) -> None:
		"""Leave Pilot's reason on the Site, where the operator looks. The customer gets short copy."""
		app = self.product.signup_app
		reason = reason or _("Pilot gave no reason.")
		frappe.log_error(
			title="Trial app install failed",
			message=f"{app} on {self.site.name}, Pilot task {task_id}: {reason}",
			reference_doctype="Site",
			reference_name=self.site.name,
		)
		self.site.add_comment(
			"Info", _("{0} install failed (Pilot task {1}): {2}").format(app, task_id, reason)
		)
