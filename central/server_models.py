from __future__ import annotations

import ipaddress
import re
from typing import Annotated, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, StringConstraints, model_validator

from central.billing.catalog.rate_card import COMPONENT_UNITS

SSHKey = Annotated[str, Field(min_length=1, max_length=16_384)]


DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
# Atlas refuses larger cloud-init user data.
MAXIMUM_USER_DATA_BYTES = 16 * 1024
PORTS = re.compile(r"([1-9][0-9]{0,4})(?:-([1-9][0-9]{0,4}))?")


class ResourceQuantity(BaseModel):
	model_config = ConfigDict(extra="forbid", strict=True)

	# The plan catalog decides which resource types a plan may include.
	resource_type: str = Field(min_length=1)
	quantity: float = Field(gt=0, allow_inf_nan=False)
	unit: str

	@model_validator(mode="after")
	def validate_unit(self):
		# The server shape is read from these units, so they must match.
		unit = COMPONENT_UNITS.get(self.resource_type)
		if unit and self.unit != unit:
			raise ValueError("The unit must match the selected resource type.")

		return self


class CreateServerInput(BaseModel):
	"""Customer-owned inputs, independent of the HTTP transport."""

	model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

	team: str = Field(min_length=1)
	region: str = Field(min_length=1)
	title: str = Field(min_length=1, max_length=140)
	offering: str = Field(min_length=1)
	image_id: str = Field(min_length=1)
	request_key: str = Field(pattern=r"^[A-Za-z0-9-]{16,100}$")
	plan: str | None = None
	includes: list[ResourceQuantity] = Field(default_factory=list, max_length=4)
	sub_category: str | None = None
	hostname: str = Field(default="", max_length=63)
	ssh_keys: list[SSHKey] = Field(default_factory=list, max_length=20)
	ssh_key_ids: list[str] = Field(default_factory=list, max_length=20)
	has_public_ipv4: bool = False
	has_public_ipv6: bool = False
	is_firewall_enabled: bool = False
	# Cloud-init reads the script as sent, so keep its whitespace.
	user_data: Annotated[str, StringConstraints(strip_whitespace=False)] = ""
	# The answers to an app's inputs, as `AppAnswers`. Central turns them into the user data, and
	# routes a `site_name` answer to the server.
	app_inputs: dict[str, str] = Field(default_factory=dict, max_length=20)


class SiteCreation(BaseModel):
	"""What a trial site needs beyond its machine: the product it is for."""

	model_config = ConfigDict(extra="forbid", strict=True)

	product: str | None = None


class ServerCreation(BaseModel):
	"""Validated, non-secret creation inputs saved on Resource Action."""

	model_config = ConfigDict(extra="forbid", strict=True)

	offering: str
	image_id: str
	plan: str | None
	currency: str
	billing_cycle: Literal["Monthly", "Annual"]
	includes: list[ResourceQuantity]
	sub_category: str | None
	hostname: str
	ssh_keys: list[SSHKey]
	ssh_key_ids: list[str] = Field(default_factory=list)
	has_public_ipv4: bool = False
	has_public_ipv6: bool = False
	is_firewall_enabled: bool = False
	user_data: str = ""
	image_tags: dict[str, str]
	site: SiteCreation | None = None
	cpu_millicores: int = Field(ge=100, le=32000)
	memory_mib: PositiveInt
	disk_mib: PositiveInt


class ServerShape(BaseModel):
	model_config = ConfigDict(extra="forbid", strict=True)

	vcpus: float = Field(gt=0, le=32)
	memory_megabytes: PositiveInt
	disk_gigabytes: PositiveInt


class ResizeConfiguration(BaseModel):
	"""Validated resize target saved on Resource Action."""

	model_config = ConfigDict(extra="forbid", strict=True)

	# None for a converted trial's move off its trial plan: its subscription opens once the move lands.
	subscription: str | None = Field(default=None, min_length=1)
	plan: str | None = None
	includes: list[ResourceQuantity] = Field(default_factory=list)
	sub_category: str | None = None
	override_rate: float | None = Field(default=None, ge=0, allow_inf_nan=False)
	preset_plan: str | None = None
	shape: ServerShape
	# The plan and size before the resize, so its progress page can show both after it lands.
	from_plan: str | None = None
	from_shape: ServerShape | None = None


class FirewallRule(BaseModel):
	"""One allow rule, in the form Atlas stores it."""

	model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

	protocol: Literal["any", "tcp", "udp", "icmp"]
	ports: str = ""
	cidrs: list[str] = Field(min_length=1, max_length=50)

	@model_validator(mode="after")
	def validate_rule(self):
		if self.ports and self.protocol not in ("tcp", "udp"):
			raise ValueError("Ports apply only to TCP and UDP rules.")

		match = PORTS.fullmatch(self.ports) if self.ports else None
		if self.ports and not match:
			raise ValueError("Enter one port, such as 8000, or one range, such as 8000-8100.")
		if match and not int(match[1]) <= int(match[2] or match[1]) <= 65535:
			raise ValueError("Ports go from 1 to 65535, with the smaller number first.")

		for cidr in self.cidrs:
			try:
				network = ipaddress.ip_network(cidr)
			except ValueError:
				raise ValueError(f"{cidr} is not an IP address range, such as 198.51.100.0/24.") from None
			if str(network) != cidr:
				raise ValueError(f"Write {cidr} as {network}.")

		return self


class FirewallChange(BaseModel):
	"""A change to a customer's firewall. A field left as None keeps its value on Atlas."""

	model_config = ConfigDict(extra="forbid", strict=True)

	enabled: bool | None = None
	inbound: list[FirewallRule] | None = None
	outbound: list[FirewallRule] | None = None

	@model_validator(mode="after")
	def validate_unique_rules(self):
		if self.enabled is None and self.inbound is None and self.outbound is None:
			raise ValueError("Send the firewall state or a rule list to change.")

		for rules in (self.inbound or [], self.outbound or []):
			keys = [(rule.protocol, rule.ports, tuple(sorted(rule.cidrs))) for rule in rules]
			if len(keys) != len(set(keys)):
				raise ValueError("Each rule can appear only once.")

		return self


class AppInput(TypedDict):
	"""One entry of `inputs` in an app's template.yaml, as Cargo sends it."""

	name: str
	label: NotRequired[str]
	type: NotRequired[Literal["string", "email", "domain", "password"]]
	required: NotRequired[bool]
	max_length: NotRequired[int]
	pattern: NotRequired[str]
	description: NotRequired[str]


class AppMinimumSize(TypedDict):
	cpu_millicores: int
	memory_mib: int
	disk_mib: int


class AppPort(TypedDict):
	port: int
	protocol: Literal["tcp", "udp"]


class AppRequirements(TypedDict):
	"""What Cargo's `get_one_click_image_requirements` returns for an app."""

	inputs: list[AppInput]
	minimum_size: AppMinimumSize
	ports: list[AppPort]


# The customer's answer to each app input, by input name.
AppAnswers = dict[str, str]


class ActionStatus(TypedDict):
	action: str
	status: str
	resource_id: str | None
	title: str
	error: dict | None
