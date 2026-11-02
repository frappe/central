from frappe.utils import now_datetime

from central.activity.changes import get_detail
from central.central.doctype.activity_event.activity_event import ActivityEvent


def record_site_created(site) -> None:
	ActivityEvent.record(
		"site.created",
		resource_type="Site",
		resource_name=site.name,
		label=_site_label(site),
		key=f"site:{site.name}:created",
		occurred_at=site.creation,
	)


def record_site_claimed(site) -> None:
	ActivityEvent.record(
		"site.claimed",
		resource_type="Site",
		resource_name=site.name,
		label=_site_label(site),
		key=f"site:{site.name}:claimed",
		occurred_at=now_datetime(),
	)


def record_site_deleted(site) -> None:
	ActivityEvent.record(
		"site.deleted",
		resource_type="Site",
		resource_name=site.name,
		label=_site_label(site),
		key=f"site:{site.name}:deleted",
	)


def _site_label(site) -> str:
	"""The name the customer chose, or the automatic address when there is none."""
	# rename_target needs a zone after the first dot; a failed label must not block the site
	return site.rename_target if site.subdomain and "." in site.name else site.site_name


def record_domain_added(domain) -> None:
	ActivityEvent.record(
		"domain.added",
		resource_type="Site Domain",
		resource_name=domain.name,
		key=f"domain:{domain.name}:added",
		occurred_at=domain.creation,
		details=[get_detail("Domain", None, domain.domain)],
	)


def record_domain_removed(domain) -> None:
	ActivityEvent.record(
		"domain.removed",
		resource_type="Site Domain",
		resource_name=domain.name,
		key=f"domain:{domain.name}:removed",
		details=[get_detail("Domain", None, domain.domain)],
	)
