from collections.abc import Mapping
from types import MappingProxyType
from typing import NamedTuple

from frappe.utils.translations import N_

NO_FIELDS = MappingProxyType({})


class EventKind(NamedTuple):
	"""Who sees an event, and where the console files it."""

	verb: str
	category: str
	capability: str


class Tracked(NamedTuple):
	"""How one DocType shows in the activity feed.

	Frappe writes a Version for every save of a DocType that tracks changes. The feed keeps
	only `fields`, and a change to a field in `field_events` becomes its own event. A status
	that moves into `statuses` is an event named after the status."""

	prefix: str
	category: str
	capability: str
	fields: Mapping[str, str] = NO_FIELDS
	field_events: Mapping[str, EventKind] = NO_FIELDS
	statuses: tuple[str, ...] = ()
	# The fields that name a child row in a detail, per table field.
	row_fields: Mapping[str, tuple[str, ...]] = NO_FIELDS
	# Check fields stored as the opposite of their label, such as skip_automatic_snapshot.
	inverted: tuple[str, ...] = ()
	label_field: str | None = None
	lifecycle: bool = True

	def get_kind(self, fieldname: str | None = None) -> EventKind:
		return self.field_events.get(fieldname) or EventKind("updated", self.category, self.capability)


TEAM_MEMBERS = "team:manage_members"

TRACKED: dict[str, Tracked] = {
	"Virtual Machine": Tracked(
		"server",
		"configuration",
		"server:view",
		fields={
			"title": "Server name",
			"plan": "Plan",
			"is_firewall_enabled": "Firewall",
			"firewall_rules": "Firewall rules",
			"has_ipv4_internet": "IPv4 internet access",
			"public_ipv4": "Public IPv4",
			"public_ipv6": "Public IPv6",
			"is_termination_protected": "Termination protection",
			"skip_automatic_snapshot": "Automatic snapshots",
			"ssh_keys": "SSH keys",
		},
		field_events={
			"title": EventKind("renamed", "configuration", "server:view"),
			"ssh_keys": EventKind("ssh_keys_changed", "access", "server:ssh-key"),
		},
		row_fields={"ssh_keys": ("team_ssh_key",)},
		inverted=("skip_automatic_snapshot",),
		# A Resource Action records the creation and termination of a server.
		lifecycle=False,
	),
	"VM Snapshot": Tracked(
		"snapshot",
		"snapshot",
		"server:view",
		statuses=("Available", "Failed", "Deleted"),
	),
	"Site": Tracked(
		"site",
		"site",
		"server:view",
		fields={"claimed_at": "Claimed"},
		field_events={"claimed_at": EventKind("claimed", "site", "server:view")},
	),
	"Site Domain": Tracked("domain", "site", "server:view"),
	"Team": Tracked(
		"team",
		"team",
		"team:edit",
		fields={"team_name": "Team name", "team_logo": "Logo", "owner_user": "Owner", "members": "Members"},
		field_events={
			"owner_user": EventKind("ownership_transferred", "team", TEAM_MEMBERS),
			"members": EventKind("members_changed", "member", TEAM_MEMBERS),
		},
		statuses=("Active", "Suspended", "Archived"),
		row_fields={"members": ("user", "role", "status")},
	),
	"Team Role": Tracked(
		"role",
		"member",
		TEAM_MEMBERS,
		fields={"role_name": "Role name", "capabilities": "Capabilities"},
		row_fields={"capabilities": ("capability",)},
	),
	"Team Invitation": Tracked(
		"invitation",
		"member",
		TEAM_MEMBERS,
		fields={"expires_on": "Expires on"},
		field_events={"expires_on": EventKind("resent", "member", TEAM_MEMBERS)},
		statuses=("Accepted", "Declined", "Revoked", "Expired"),
		label_field="email",
	),
	"Team SSH Key": Tracked(
		"ssh_key",
		"access",
		"server:ssh-key",
		fields={"title": "Name", "public_key": "Public key"},
		field_events={
			"title": EventKind("renamed", "access", "server:ssh-key"),
			"public_key": EventKind("rotated", "access", "server:ssh-key"),
		},
	),
}

# The end state of a server action, recorded on the server.
ACTION_EVENTS = {
	"create": "server.created",
	"start": "server.started",
	"stop": "server.stopped",
	"restart": "server.restarted",
	"resize": "server.resized",
	"terminate": "server.terminated",
}

# {actor} and {resource} mark the names the console shows in bold. The API translates
# each sentence for the reader.
SENTENCES = {
	"server.created": N_("{actor} created {resource}"),
	"server.started": N_("{actor} started {resource}"),
	"server.stopped": N_("{actor} stopped {resource}"),
	"server.restarted": N_("{actor} restarted {resource}"),
	"server.resized": N_("{actor} resized {resource}"),
	"server.terminated": N_("{actor} terminated {resource}"),
	"server.renamed": N_("{actor} renamed {resource}"),
	"server.updated": N_("{actor} changed the configuration of {resource}"),
	"server.ssh_keys_changed": N_("{actor} changed the SSH keys on {resource}"),
	"snapshot.created": N_("{actor} requested snapshot {resource}"),
	"snapshot.available": N_("Snapshot {resource} is ready"),
	"snapshot.failed": N_("Snapshot {resource} failed"),
	"snapshot.deleted": N_("{actor} deleted snapshot {resource}"),
	"site.created": N_("{actor} created site {resource}"),
	"site.claimed": N_("{actor} claimed site {resource}"),
	"site.deleted": N_("{actor} deleted site {resource}"),
	"domain.created": N_("{actor} added domain {resource}"),
	"domain.deleted": N_("{actor} removed domain {resource}"),
	"team.created": N_("{actor} created team {resource}"),
	"team.updated": N_("{actor} changed the team settings"),
	"team.archived": N_("{actor} archived the team"),
	"team.suspended": N_("{actor} suspended the team"),
	"team.active": N_("{actor} reactivated the team"),
	"team.ownership_transferred": N_("{actor} transferred ownership of the team"),
	"team.members_changed": N_("{actor} changed the team members"),
	"team.impersonated": N_("{actor} opened the team as support"),
	"role.created": N_("{actor} created role {resource}"),
	"role.updated": N_("{actor} changed role {resource}"),
	"role.deleted": N_("{actor} deleted role {resource}"),
	"invitation.created": N_("{actor} invited {resource}"),
	"invitation.resent": N_("{actor} resent the invitation to {resource}"),
	"invitation.accepted": N_("{actor} accepted the invitation"),
	"invitation.declined": N_("{actor} declined the invitation"),
	"invitation.revoked": N_("{actor} revoked the invitation to {resource}"),
	"invitation.expired": N_("The invitation to {resource} expired"),
	"ssh_key.created": N_("{actor} added SSH key {resource}"),
	"ssh_key.renamed": N_("{actor} renamed SSH key {resource}"),
	"ssh_key.rotated": N_("{actor} rotated SSH key {resource}"),
	"ssh_key.deleted": N_("{actor} deleted SSH key {resource}"),
}

GENERIC_SENTENCES = {
	"created": N_("{actor} created {resource}"),
	"deleted": N_("{actor} deleted {resource}"),
}
DEFAULT_SENTENCE = N_("{actor} changed {resource}")


def get_sentence(event: str) -> str:
	"""The English sentence for an event; a verb without its own sentence reads generically."""
	return SENTENCES.get(event) or GENERIC_SENTENCES.get(event.rpartition(".")[2]) or DEFAULT_SENTENCE
