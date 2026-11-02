from typing import NamedTuple

from frappe.utils.translations import N_


class EventType(NamedTuple):
	# English in the row; the API translates it for each reader
	title: str
	# {actor} and {resource} mark the names the dashboard shows in bold
	sentence: str
	category: str
	capability: str


# Every event Central records. A row's visibility comes from here, never from the caller.
EVENTS: dict[str, EventType] = {
	"server.created": EventType(
		N_("Server created"), N_("{actor} created {resource}"), "action", "server:view"
	),
	"server.started": EventType(
		N_("Server started"), N_("{actor} started {resource}"), "action", "server:view"
	),
	"server.stopped": EventType(
		N_("Server stopped"), N_("{actor} stopped {resource}"), "action", "server:view"
	),
	"server.restarted": EventType(
		N_("Server restarted"), N_("{actor} restarted {resource}"), "action", "server:view"
	),
	"server.resized": EventType(
		N_("Server resized"), N_("{actor} resized {resource}"), "action", "server:view"
	),
	"server.terminated": EventType(
		N_("Server terminated"), N_("{actor} terminated {resource}"), "action", "server:view"
	),
	"server.renamed": EventType(
		N_("Server renamed"), N_("{actor} renamed {resource}"), "configuration", "server:view"
	),
	"server.configured": EventType(
		N_("Configuration changed"),
		N_("{actor} changed the configuration of {resource}"),
		"configuration",
		"server:view",
	),
	"server.ssh_keys_changed": EventType(
		N_("SSH keys changed"), N_("{actor} changed the SSH keys on {resource}"), "access", "server:ssh-key"
	),
	"snapshot.taken": EventType(
		N_("Snapshot taken"), N_("{actor} took a snapshot of {resource}"), "snapshot", "server:view"
	),
	"snapshot.deleted": EventType(
		N_("Snapshot deleted"), N_("{actor} deleted a snapshot of {resource}"), "snapshot", "server:view"
	),
	"snapshot.failed": EventType(
		N_("Snapshot failed"), N_("A snapshot of {resource} failed"), "snapshot", "server:view"
	),
	"snapshot.kept": EventType(
		N_("Snapshot kept"), N_("{actor} kept a snapshot of {resource}"), "snapshot", "server:view"
	),
	"site.created": EventType(
		N_("Site created"), N_("{actor} created site {resource}"), "site", "server:view"
	),
	"site.claimed": EventType(
		N_("Site claimed"), N_("{actor} claimed site {resource}"), "site", "server:view"
	),
	"site.deleted": EventType(
		N_("Site deleted"), N_("{actor} deleted site {resource}"), "site", "server:view"
	),
	"domain.added": EventType(
		N_("Domain added"), N_("{actor} added domain {resource}"), "site", "server:view"
	),
	"domain.removed": EventType(
		N_("Domain removed"), N_("{actor} removed domain {resource}"), "site", "server:view"
	),
	"team.created": EventType(N_("Team created"), N_("{actor} created team {resource}"), "team", "team:edit"),
	"team.updated": EventType(
		N_("Team settings changed"), N_("{actor} changed the team settings"), "team", "team:edit"
	),
	"team.archived": EventType(N_("Team archived"), N_("{actor} archived the team"), "team", "team:delete"),
	"team.restored": EventType(N_("Team restored"), N_("{actor} restored the team"), "team", "team:delete"),
	"team.suspended": EventType(
		N_("Team suspended"), N_("{actor} suspended the team"), "team", "team:delete"
	),
	"team.unsuspended": EventType(
		N_("Team unsuspended"), N_("{actor} lifted the team suspension"), "team", "team:delete"
	),
	"team.ownership_transferred": EventType(
		N_("Ownership transferred"),
		N_("{actor} transferred ownership of the team"),
		"team",
		"team:manage_members",
	),
	"team.impersonated": EventType(
		N_("Support opened the team"), N_("{actor} opened the team as support"), "team", "team:manage_members"
	),
	"member.added": EventType(
		N_("Member added"), N_("{actor} added {resource} to the team"), "member", "team:manage_members"
	),
	"member.removed": EventType(
		N_("Member removed"), N_("{actor} removed {resource} from the team"), "member", "team:manage_members"
	),
	"member.roles_changed": EventType(
		N_("Member roles changed"),
		N_("{actor} changed the roles of {resource}"),
		"member",
		"team:manage_members",
	),
	"member.status_changed": EventType(
		N_("Member status changed"),
		N_("{actor} changed the status of {resource}"),
		"member",
		"team:manage_members",
	),
	"invitation.sent": EventType(
		N_("Invitation sent"), N_("{actor} invited {resource}"), "member", "team:manage_members"
	),
	"invitation.resent": EventType(
		N_("Invitation resent"),
		N_("{actor} resent the invitation to {resource}"),
		"member",
		"team:manage_members",
	),
	"invitation.accepted": EventType(
		N_("Invitation accepted"), N_("{actor} accepted the invitation"), "member", "team:manage_members"
	),
	"invitation.declined": EventType(
		N_("Invitation declined"), N_("{actor} declined the invitation"), "member", "team:manage_members"
	),
	"invitation.revoked": EventType(
		N_("Invitation revoked"),
		N_("{actor} revoked the invitation to {resource}"),
		"member",
		"team:manage_members",
	),
	"invitation.expired": EventType(
		N_("Invitation expired"), N_("The invitation to {resource} expired"), "member", "team:manage_members"
	),
	"role.created": EventType(
		N_("Role created"), N_("{actor} created role {resource}"), "member", "team:manage_members"
	),
	"role.updated": EventType(
		N_("Role changed"), N_("{actor} changed role {resource}"), "member", "team:manage_members"
	),
	"role.deleted": EventType(
		N_("Role deleted"), N_("{actor} deleted role {resource}"), "member", "team:manage_members"
	),
	"ssh_key.added": EventType(
		N_("SSH key added"), N_("{actor} added SSH key {resource}"), "access", "server:ssh-key"
	),
	"ssh_key.rotated": EventType(
		N_("SSH key rotated"), N_("{actor} rotated SSH key {resource}"), "access", "server:ssh-key"
	),
	"ssh_key.renamed": EventType(
		N_("SSH key renamed"), N_("{actor} renamed SSH key {resource}"), "access", "server:ssh-key"
	),
	"ssh_key.deleted": EventType(
		N_("SSH key deleted"), N_("{actor} deleted SSH key {resource}"), "access", "server:ssh-key"
	),
}

CATEGORIES = ("action", "configuration", "snapshot", "site", "team", "member", "access")
SYSTEM_USERS = {"", None, "Administrator", "Guest"}


def get_event(event: str) -> EventType:
	"""The one registry entry for `event`; an unregistered name is a programming error."""
	if event not in EVENTS:
		raise KeyError(f"Unknown activity event: {event}")

	return EVENTS[event]
