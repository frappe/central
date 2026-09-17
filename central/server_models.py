from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, model_validator


class ResourceQuantity(BaseModel):
	model_config = ConfigDict(extra="forbid", strict=True)

	resource_type: Literal["Compute", "Memory", "Disk", "Transfer"]
	quantity: float = Field(gt=0, allow_inf_nan=False)
	unit: str

	@model_validator(mode="after")
	def validate_unit(self):
		units = {"Compute": "vCPU", "Memory": "GB", "Disk": "GB", "Transfer": "GB"}
		if self.unit != units[self.resource_type]:
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
	includes: list[ResourceQuantity] = Field(default_factory=list, max_length=3)
	sub_category: str | None = None
	hostname: str = Field(default="", max_length=63)
	ssh_keys: list[str] = Field(default_factory=list, max_length=20)


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
	ssh_keys: list[str]
	image_tags: dict[str, str]
	virtual_cpu_count: PositiveInt
	memory_mib: PositiveInt
	disk_mib: PositiveInt


class ActionStatus(TypedDict):
	action: str
	status: str
	resource_id: str | None
	title: str
	error: dict | None
