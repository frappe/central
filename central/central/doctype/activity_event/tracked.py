from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import NamedTuple

import frappe
from frappe.model.document import Document
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
	# A change to a row of these tables is an event about the person the row names.
	row_subjects: Mapping[str, str] = NO_FIELDS
	# A guest session acts for the person this returns, such as the owner signing up.
	guest_actor: Callable[[Document], str | None] | None = None
	label_field: str | None = None
	lifecycle: bool = True

	def get_kind(self, fieldname: str | None = None) -> EventKind:
		return self.field_events.get(fieldname) or EventKind("updated", self.category, self.capability)


TEAM_MEMBERS = "team:manage_members"


def get_team_owner(doc: Document) -> str | None:
	return frappe.db.get_value("Team", doc.team, "owner_user")


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
		guest_actor=get_team_owner,
	),
	"Site Domain": Tracked("domain", "site", "server:view", guest_actor=get_team_owner),
	"Team": Tracked(
		"team",
		"team",
		"team:edit",
		fields={"team_name": "Team name", "team_logo": "Logo", "owner_user": "Owner", "members": "Access"},
		field_events={
			"team_name": EventKind("renamed", "team", "team:edit"),
			"team_logo": EventKind("logo_changed", "team", "team:edit"),
			"owner_user": EventKind("ownership_transferred", "team", TEAM_MEMBERS),
			"members": EventKind("member", "member", TEAM_MEMBERS),
		},
		statuses=("Active", "Suspended", "Archived"),
		row_fields={"members": ("role", "status")},
		row_subjects={"members": "user"},
		guest_actor=lambda team: team.owner_user,
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
		guest_actor=lambda invitation: invitation.accepted_by,
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

# The end state of a server action, recorded on the server: (succeeded, failed).
ACTION_EVENTS = {
	"create": ("server.created", "server.create_failed"),
	"start": ("server.started", "server.start_failed"),
	"stop": ("server.stopped", "server.stop_failed"),
	"restart": ("server.restarted", "server.restart_failed"),
	"resize": ("server.resized", "server.resize_failed"),
	"terminate": ("server.terminated", "server.terminate_failed"),
}


class Sentence(NamedTuple):
	"""How the console says what happened. {actor} and {resource} mark the names it shows in
	bold. An event without a person, such as a job or a schedule, reads without an actor."""

	by_person: str
	by_nobody: str


SENTENCES = {
	"server.created": Sentence(N_("{actor} created {resource}"), N_("{resource} was created")),
	"server.create_failed": Sentence(
		N_("{actor} tried to create {resource}"), N_("{resource} could not be created")
	),
	"server.started": Sentence(N_("{actor} started {resource}"), N_("{resource} started")),
	"server.start_failed": Sentence(N_("{actor} tried to start {resource}"), N_("{resource} did not start")),
	"server.stopped": Sentence(N_("{actor} stopped {resource}"), N_("{resource} stopped")),
	"server.stop_failed": Sentence(N_("{actor} tried to stop {resource}"), N_("{resource} did not stop")),
	"server.restarted": Sentence(N_("{actor} restarted {resource}"), N_("{resource} restarted")),
	"server.restart_failed": Sentence(
		N_("{actor} tried to restart {resource}"), N_("{resource} did not restart")
	),
	"server.resized": Sentence(N_("{actor} resized {resource}"), N_("{resource} was resized")),
	"server.resize_failed": Sentence(
		N_("{actor} tried to resize {resource}"), N_("{resource} was not resized")
	),
	"server.terminated": Sentence(N_("{actor} terminated {resource}"), N_("{resource} was terminated")),
	"server.terminate_failed": Sentence(
		N_("{actor} tried to terminate {resource}"), N_("{resource} was not terminated")
	),
	"server.renamed": Sentence(N_("{actor} renamed {resource}"), N_("{resource} was renamed")),
	"server.updated": Sentence(
		N_("{actor} changed settings on {resource}"), N_("Settings on {resource} changed")
	),
	"server.ssh_keys_changed": Sentence(
		N_("{actor} changed the SSH keys that can sign in to {resource}"),
		N_("The SSH keys that can sign in to {resource} changed"),
	),
	"snapshot.created": Sentence(
		N_("{actor} started snapshot {resource}"), N_("Automatic snapshot {resource} started")
	),
	"snapshot.available": Sentence(N_("Snapshot {resource} is ready"), N_("Snapshot {resource} is ready")),
	"snapshot.failed": Sentence(N_("Snapshot {resource} failed"), N_("Snapshot {resource} failed")),
	"snapshot.deleted": Sentence(
		N_("{actor} deleted snapshot {resource}"), N_("Snapshot {resource} was deleted")
	),
	"site.created": Sentence(N_("{actor} created site {resource}"), N_("Site {resource} was created")),
	"site.claimed": Sentence(
		N_("{actor} opened site {resource} for the first time"),
		N_("Site {resource} was opened for the first time"),
	),
	"site.deleted": Sentence(N_("{actor} deleted site {resource}"), N_("Site {resource} was deleted")),
	"domain.created": Sentence(N_("{actor} added domain {resource}"), N_("Domain {resource} was added")),
	"domain.deleted": Sentence(N_("{actor} removed domain {resource}"), N_("Domain {resource} was removed")),
	"team.created": Sentence(N_("{actor} created the team"), N_("The team was created")),
	"team.renamed": Sentence(N_("{actor} renamed the team"), N_("The team was renamed")),
	"team.logo_changed": Sentence(N_("{actor} changed the team logo"), N_("The team logo changed")),
	"team.archived": Sentence(N_("{actor} archived the team"), N_("The team was archived")),
	"team.suspended": Sentence(N_("{actor} suspended the team"), N_("The team was suspended")),
	"team.active": Sentence(N_("{actor} restored the team"), N_("The team was restored")),
	"team.ownership_transferred": Sentence(
		N_("{actor} transferred team ownership"), N_("Team ownership was transferred")
	),
	"team.member_added": Sentence(
		N_("{actor} added {resource} to the team"), N_("{resource} joined the team")
	),
	"team.member_joined": Sentence(N_("{actor} joined the team"), N_("{resource} joined the team")),
	"team.member_removed": Sentence(
		N_("{actor} removed {resource} from the team"), N_("{resource} was removed from the team")
	),
	"team.member_left": Sentence(N_("{actor} left the team"), N_("{resource} left the team")),
	"team.member_changed": Sentence(
		N_("{actor} changed the access of {resource}"), N_("The access of {resource} changed")
	),
	"team.impersonated": Sentence(N_("{actor} opened the team for support"), N_("Support opened the team")),
	"role.created": Sentence(N_("{actor} created role {resource}"), N_("Role {resource} was created")),
	"role.updated": Sentence(N_("{actor} changed role {resource}"), N_("Role {resource} changed")),
	"role.deleted": Sentence(N_("{actor} deleted role {resource}"), N_("Role {resource} was deleted")),
	"invitation.created": Sentence(N_("{actor} invited {resource}"), N_("{resource} was invited")),
	"invitation.resent": Sentence(
		N_("{actor} sent the invitation to {resource} again"),
		N_("The invitation to {resource} was sent again"),
	),
	"invitation.accepted": Sentence(
		N_("{actor} accepted the invitation"), N_("{resource} accepted the invitation")
	),
	"invitation.declined": Sentence(
		N_("{actor} declined the invitation"), N_("{resource} declined the invitation")
	),
	"invitation.revoked": Sentence(
		N_("{actor} revoked the invitation to {resource}"), N_("The invitation to {resource} was revoked")
	),
	"invitation.expired": Sentence(
		N_("The invitation to {resource} expired"), N_("The invitation to {resource} expired")
	),
	"ssh_key.created": Sentence(N_("{actor} added SSH key {resource}"), N_("SSH key {resource} was added")),
	"ssh_key.renamed": Sentence(
		N_("{actor} renamed SSH key {resource}"), N_("SSH key {resource} was renamed")
	),
	"ssh_key.rotated": Sentence(
		N_("{actor} rotated SSH key {resource}"), N_("SSH key {resource} was rotated")
	),
	"ssh_key.deleted": Sentence(
		N_("{actor} deleted SSH key {resource}"), N_("SSH key {resource} was deleted")
	),
}

GENERIC_SENTENCES = {
	"created": Sentence(N_("{actor} created {resource}"), N_("{resource} was created")),
	"deleted": Sentence(N_("{actor} deleted {resource}"), N_("{resource} was deleted")),
}
DEFAULT_SENTENCE = Sentence(N_("{actor} changed {resource}"), N_("{resource} changed"))


def get_sentence(event: str, has_actor: bool) -> str:
	"""The English sentence for an event; a verb without its own sentence reads generically."""
	sentence = SENTENCES.get(event) or GENERIC_SENTENCES.get(event.rpartition(".")[2]) or DEFAULT_SENTENCE
	return sentence.by_person if has_actor else sentence.by_nobody
