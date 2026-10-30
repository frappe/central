from typing import NamedTuple

from frappe.utils.translations import N_


class EventType(NamedTuple):
	# English in the row; the API translates it for each reader
	title: str
	category: str
	capability: str


# Every event Central records. A row's visibility comes from here, never from the caller.
EVENTS: dict[str, EventType] = {
	"server.created": EventType(N_("Server created"), "action", "server:view"),
	"server.started": EventType(N_("Server started"), "action", "server:view"),
	"server.stopped": EventType(N_("Server stopped"), "action", "server:view"),
	"server.restarted": EventType(N_("Server restarted"), "action", "server:view"),
	"server.resized": EventType(N_("Server resized"), "action", "server:view"),
	"server.terminated": EventType(N_("Server terminated"), "action", "server:view"),
	"server.renamed": EventType(N_("Server renamed"), "configuration", "server:view"),
	"server.configured": EventType(N_("Configuration changed"), "configuration", "server:view"),
	"snapshot.taken": EventType(N_("Snapshot taken"), "snapshot", "server:view"),
	"snapshot.deleted": EventType(N_("Snapshot deleted"), "snapshot", "server:view"),
	"snapshot.failed": EventType(N_("Snapshot failed"), "snapshot", "server:view"),
	"snapshot.kept": EventType(N_("Snapshot kept"), "snapshot", "server:view"),
	"site.created": EventType(N_("Site created"), "site", "server:view"),
	"site.claimed": EventType(N_("Site claimed"), "site", "server:view"),
	"site.deleted": EventType(N_("Site deleted"), "site", "server:view"),
	"domain.added": EventType(N_("Domain added"), "site", "server:view"),
	"domain.removed": EventType(N_("Domain removed"), "site", "server:view"),
	"team.created": EventType(N_("Team created"), "team", "team:edit"),
	"team.updated": EventType(N_("Team settings changed"), "team", "team:edit"),
	"team.archived": EventType(N_("Team archived"), "team", "team:delete"),
	"team.restored": EventType(N_("Team restored"), "team", "team:delete"),
	"team.suspended": EventType(N_("Team suspended"), "team", "team:delete"),
	"team.unsuspended": EventType(N_("Team unsuspended"), "team", "team:delete"),
	"team.ownership_transferred": EventType(N_("Ownership transferred"), "team", "team:manage_members"),
	"team.impersonated": EventType(N_("Support opened the team"), "team", "team:manage_members"),
	"member.added": EventType(N_("Member added"), "member", "team:manage_members"),
	"member.removed": EventType(N_("Member removed"), "member", "team:manage_members"),
	"member.roles_changed": EventType(N_("Member roles changed"), "member", "team:manage_members"),
	"member.status_changed": EventType(N_("Member status changed"), "member", "team:manage_members"),
	"invitation.sent": EventType(N_("Invitation sent"), "member", "team:manage_members"),
	"invitation.resent": EventType(N_("Invitation resent"), "member", "team:manage_members"),
	"invitation.accepted": EventType(N_("Invitation accepted"), "member", "team:manage_members"),
	"invitation.declined": EventType(N_("Invitation declined"), "member", "team:manage_members"),
	"invitation.revoked": EventType(N_("Invitation revoked"), "member", "team:manage_members"),
	"invitation.expired": EventType(N_("Invitation expired"), "member", "team:manage_members"),
	"role.created": EventType(N_("Role created"), "member", "team:manage_members"),
	"role.updated": EventType(N_("Role changed"), "member", "team:manage_members"),
	"role.deleted": EventType(N_("Role deleted"), "member", "team:manage_members"),
	"ssh_key.added": EventType(N_("SSH key added"), "access", "server:ssh-key"),
	"ssh_key.rotated": EventType(N_("SSH key rotated"), "access", "server:ssh-key"),
	"ssh_key.renamed": EventType(N_("SSH key renamed"), "access", "server:ssh-key"),
	"ssh_key.deleted": EventType(N_("SSH key deleted"), "access", "server:ssh-key"),
}

CATEGORIES = ("action", "configuration", "snapshot", "site", "team", "member", "access")
SYSTEM_USERS = {"", None, "Administrator", "Guest"}


def get_event(event: str) -> EventType:
	"""The one registry entry for `event`; an unregistered name is a programming error."""
	if event not in EVENTS:
		raise KeyError(f"Unknown activity event: {event}")

	return EVENTS[event]
