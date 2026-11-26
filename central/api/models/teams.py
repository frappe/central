from typing import TypedDict


class Profile(TypedDict):
	user: str
	full_name: str | None
	user_image: str | None
	email: str | None


class UpdateProfileResponse(TypedDict):
	full_name: str


class SetProfilePhotoResponse(TypedDict):
	user_image: str | None


class TeamSummary(TypedDict):
	"""A team the signed-in user can switch to."""

	name: str
	label: str
	logo: str | None
	owner: str
	role: str
	members: int
	created: str
	status: str
	onboarding: list[str]


class ReceivedInvitation(TypedDict):
	"""A pending invitation addressed to the signed-in user."""

	name: str
	team: str
	team_name: str
	role: str
	role_name: str
	invited_by: str | None
	expires_on: str
	creation: str


class RoleGrant(TypedDict):
	role: str
	resource_type: str
	resource_name: str | None


class TeamMember(TypedDict):
	user: str
	full_name: str | None
	user_image: str | None
	roles: list[RoleGrant]
	status: str
	is_owner: bool


class TeamRole(TypedDict):
	name: str
	role_name: str
	is_system: bool
	team: str | None
	capabilities: list[str]


class TeamName(TypedDict):
	name: str
	team_name: str


class SetOnboardingStepResponse(TypedDict):
	step: str
	status: str


class SetTeamLogoResponse(TypedDict):
	team_logo: str | None


class TransferTeamOwnershipResponse(TypedDict):
	team: str
	owner: str


class ArchiveCheck(TypedDict):
	key: str
	passed: bool
	count: int


class CreditBalance(TypedDict):
	currency: str
	balance: float


class ArchiveChecks(TypedDict):
	checks: list[ArchiveCheck]
	credit_balances: list[CreditBalance]


class ArchiveTeamResponse(TypedDict):
	team: str
	archived: bool


class SentInvitation(TypedDict):
	"""One row of a bulk invite. `invitation` is empty and `error` says why when the row was refused."""

	email: str
	invitation: str | None
	error: str | None


class ResendInvitationResponse(TypedDict):
	name: str
	expires_on: str


class RevokeInvitationResponse(TypedDict):
	invitation: str
	revoked: bool


class AcceptInvitationResponse(TypedDict):
	team: str
	role: str
	accepted: bool


class DeclineInvitationResponse(TypedDict):
	invitation: str
	declined: bool


class SetTeamMemberRolesResponse(TypedDict):
	team: str
	user: str
	roles: list[RoleGrant]


class SetTeamMemberStatusResponse(TypedDict):
	team: str
	user: str
	status: str


class RemoveTeamMemberResponse(TypedDict):
	team: str
	user: str
	removed: bool


class LeaveTeamResponse(TypedDict):
	team: str
	left: bool


class CustomRole(TypedDict):
	role: str
	role_name: str


class DeleteCustomRoleResponse(TypedDict):
	role: str
	deleted: bool


class ActivityActor(TypedDict):
	label: str
	kind: str
	image: str | None


class ActivityResource(TypedDict):
	type: str
	name: str
	label: str


class ActivityEvent(TypedDict):
	id: str
	event: str
	category: str
	occurred_at: str
	actor: ActivityActor
	sentence: str
	initiator: ActivityActor | None
	resource: ActivityResource
	status: str | None
	details: list[dict]
	error: dict | None


class ActivityFeed(TypedDict):
	"""Newest first. Pass `next_cursor` as `cursor` for the next page while it is set."""

	events: list[ActivityEvent]
	next_cursor: str | None


class Ticket(TypedDict):
	name: str
	subject: str
	status: str
	priority: str | None
	creation: str | None
	url: str


class TicketIssue(TypedDict):
	label: str
	is_critical: bool


class TicketCategory(TypedDict):
	"""Pass `key` as `category` and an issue `label` as `issue_type` to `create_ticket`."""

	key: str
	label: str
	issues: list[TicketIssue]


class HelpArticle(TypedDict):
	name: str
	title: str
	excerpt: str
	category: str | None
	url: str


class RelatedTicket(TypedDict):
	"""`url` is empty for a teammate's ticket, which the portal opens only for the person who raised it."""

	name: str
	subject: str
	status: str
	raised_by: str
	url: str | None


class RelatedHelp(TypedDict):
	articles: list[HelpArticle]
	tickets: list[RelatedTicket]


class TeamTicket(TypedDict):
	"""`url` is empty for a teammate's ticket, which the portal opens only for the person who raised it."""

	name: str
	subject: str
	status: str
	status_category: str | None
	priority: str | None
	ticket_type: str | None
	raised_by: str
	creation: str
	modified: str
	url: str | None
