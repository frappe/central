from frappe.utils import now_datetime

from central.activity.changes import get_detail
from central.central.doctype.activity_event.activity_event import ActivityEvent

TEAM_STATUS_EVENTS = {
	("Active", "Archived"): "team.archived",
	("Archived", "Active"): "team.restored",
	("Active", "Suspended"): "team.suspended",
	("Suspended", "Active"): "team.unsuspended",
}


def record_team_update(team) -> None:
	"""Record one Team save: its lifecycle, its settings, and each member whose grants changed."""
	previous = team.get_doc_before_save()
	if previous is None:
		_record(team, "team.created", key="created", occurred_at=team.creation)
		return

	if team.owner_user != previous.owner_user:
		_record(
			team,
			"team.ownership_transferred",
			key=f"ownership:{team.modified}",
			details=[get_detail("Owner", previous.owner_user, team.owner_user)],
		)
		return

	status_event = TEAM_STATUS_EVENTS.get((previous.status, team.status))
	if status_event:
		_record(team, status_event, key=f"status:{team.modified}", status=team.status)

	details = _setting_changes(team, previous)
	if details:
		_record(team, "team.updated", key=f"settings:{team.modified}", details=details)

	_record_member_changes(team, previous)


def record_invitation_sent(invitation) -> None:
	_record_invitation(invitation, "invitation.sent", key="sent", occurred_at=invitation.creation)


def record_invitation_action(invitation, action: str) -> None:
	# A resend repeats, so each save is its own event; the other actions happen once.
	_record_invitation(invitation, f"invitation.{action}", key=f"{action}:{invitation.modified}")


def record_team_impersonation(team) -> None:
	_record(team, "team.impersonated", key=f"impersonation:{now_datetime()}")


def record_role_created(role) -> None:
	if role.is_system:
		return

	ActivityEvent.record(
		"role.created",
		resource_type="Team Role",
		resource_name=role.name,
		key=f"created:{role.name}",
		occurred_at=role.creation,
		details=[get_detail("Role", None, role.role_name)],
	)


def record_role_updated(role) -> None:
	if role.is_system:
		return

	previous = role.get_doc_before_save()
	if previous is None:
		return

	details = []
	if role.role_name != previous.role_name:
		details.append(get_detail("Role name", previous.role_name, role.role_name))
	if _capabilities(role) != _capabilities(previous):
		details.append(get_detail("Capabilities"))
	if not details:
		return

	ActivityEvent.record(
		"role.updated",
		resource_type="Team Role",
		resource_name=role.name,
		key=f"updated:{role.modified}",
		details=details,
	)


def record_role_deleted(role) -> None:
	if role.is_system:
		return

	ActivityEvent.record(
		"role.deleted",
		resource_type="Team Role",
		resource_name=role.name,
		key=f"deleted:{role.modified}",
		details=[get_detail("Role", None, role.role_name)],
	)


def record_ssh_key_added(key) -> None:
	ActivityEvent.record(
		"ssh_key.added",
		resource_type="Team SSH Key",
		resource_name=key.name,
		key=f"created:{key.name}",
		occurred_at=key.creation,
		details=[get_detail("SSH key", None, key.title)],
	)


def record_ssh_key_updated(key) -> None:
	previous = key.get_doc_before_save()
	if previous is None:
		return

	if key.public_key != previous.public_key:
		event = "ssh_key.rotated"
	elif key.title != previous.title:
		event = "ssh_key.renamed"
	else:
		return

	ActivityEvent.record(
		event,
		resource_type="Team SSH Key",
		resource_name=key.name,
		key=f"updated:{key.modified}",
		details=[get_detail("SSH key", None, key.title)],
	)


def record_ssh_key_deleted(key) -> None:
	ActivityEvent.record(
		"ssh_key.deleted",
		resource_type="Team SSH Key",
		resource_name=key.name,
		key=f"deleted:{key.modified}",
		details=[get_detail("SSH key", None, key.title)],
	)


def _record(team, event: str, *, key: str, **kwargs) -> None:
	ActivityEvent.record(
		event,
		resource_type="Team",
		resource_name=team.name,
		key=f"team:{team.name}:{key}",
		**kwargs,
	)


def _record_invitation(invitation, event: str, *, key: str, occurred_at=None) -> None:
	ActivityEvent.record(
		event,
		resource_type="Team Invitation",
		resource_name=invitation.name,
		key=f"{invitation.name}:{key}",
		occurred_at=occurred_at,
		status=invitation.status,
		details=[
			get_detail("Email", None, invitation.email),
			get_detail("Role", None, invitation.role_name),
		],
		reference=("Team Invitation", invitation.name),
	)


def _setting_changes(team, previous) -> list[dict]:
	details = []
	if team.team_name != previous.team_name:
		details.append(get_detail("Team name", previous.team_name, team.team_name))
	if team.team_logo != previous.team_logo:
		details.append(get_detail("Logo"))

	return details


def _record_member_changes(team, previous) -> None:
	before = _member_rows(previous)
	after = _member_rows(team)
	for user in sorted(before.keys() | after.keys()):
		event, details = _member_event(user, before.get(user, ()), after.get(user, ()))
		if event:
			_record(team, event, key=f"member:{user}:{team.modified}", details=details)


def _member_rows(team) -> dict[str, list]:
	rows: dict[str, list] = {}
	# The stored document can keep a row a wildcard grant already covers; compare the grants.
	for row in team._effective_grants(team):
		rows.setdefault(row.user, []).append(row)

	return rows


def _member_event(user: str, before, after) -> tuple[str | None, list[dict]]:
	if not before:
		return "member.added", [get_detail("Member", None, user)]
	if not after:
		return "member.removed", [get_detail("Member", None, user)]

	if _has_grant_changes(before, after):
		return "member.roles_changed", [
			get_detail("Member", None, user),
			get_detail("Roles", _roles(before), _roles(after)),
		]

	if _has_status_changes(before, after):
		before_status = {row.status for row in before}
		after_status = {row.status for row in after}
		return "member.status_changed", [
			get_detail("Member", None, user),
			get_detail("Status", ", ".join(sorted(before_status)), ", ".join(sorted(after_status))),
		]

	return None, []


def _has_grant_changes(before, after) -> bool:
	return {_grant(row) for row in before} != {_grant(row) for row in after}


def _has_status_changes(before, after) -> bool:
	return {row.status for row in before} != {row.status for row in after}


def _grant(row) -> tuple[str, str, str]:
	return (row.role, row.resource_type or "*", row.resource_name or "")


def _roles(rows) -> str:
	labels = set()
	for row in rows:
		scope = row.resource_name if row.resource_type and row.resource_type != "*" else None
		labels.add(f"{row.role} ({scope})" if scope else row.role)

	return ", ".join(sorted(labels))


def _capabilities(role) -> frozenset[str]:
	return frozenset(row.capability for row in role.capabilities)
