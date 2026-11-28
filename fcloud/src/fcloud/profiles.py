import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import keyring
import keyring.errors

from fcloud.errors import FcloudError, LoginError

KEYRING_SERVICE = "fcloud"
LoginMethod = Literal["oauth", "api_key"]


def get_config_path() -> Path:
	directory = os.environ.get("FCLOUD_CONFIG_DIR") or Path.home() / ".config" / "fcloud"
	return Path(directory) / "config.json"


@dataclass
class Profile:
	"""A Central site the CLI is logged in to. Its secret lives in the system keyring, not in the config file."""

	name: str
	url: str
	method: LoginMethod
	client_id: str | None = None

	def get_secret(self) -> str:
		secret = keyring.get_password(KEYRING_SERVICE, self.name)
		if secret is None:
			raise LoginError(f"No credentials for {self.name}. Run `fcloud auth login {self.url}`.")
		return secret

	def set_secret(self, secret: str) -> None:
		keyring.set_password(KEYRING_SERVICE, self.name, secret)

	def delete_secret(self) -> None:
		try:
			keyring.delete_password(KEYRING_SERVICE, self.name)
		except keyring.errors.PasswordDeleteError:
			pass


class ProfileStore:
	"""The profiles in the config file, and which one is the default."""

	def __init__(self, path: Path | None = None):
		self.path = path or get_config_path()
		self.default_name: str | None = None
		self.profiles: dict[str, Profile] = {}
		if self.path.exists():
			config = json.loads(self.path.read_text())
			self.default_name = config["default"]
			self.profiles = {
				name: Profile(name=name, **fields) for name, fields in config["profiles"].items()
			}

	def get(self, name: str | None = None) -> Profile:
		"""The named profile, or the default one."""
		name = name or self.default_name
		if not name:
			raise FcloudError("Run `fcloud auth login <url>` first, or set FCLOUD_URL.")
		if name not in self.profiles:
			raise FcloudError(f"No profile {name}. See `fcloud auth list`.")
		return self.profiles[name]

	def save(self, profile: Profile, make_default: bool = False) -> None:
		self.profiles[profile.name] = profile
		if make_default or not self.default_name:
			self.default_name = profile.name
		self.write()

	def remove(self, name: str) -> Profile:
		profile = self.get(name)
		del self.profiles[name]
		if self.default_name == name:
			self.default_name = next(iter(self.profiles), None)
		self.write()
		return profile

	def set_default(self, name: str) -> None:
		self.default_name = self.get(name).name
		self.write()

	def write(self) -> None:
		profiles = {name: asdict(profile) for name, profile in self.profiles.items()}
		for fields in profiles.values():
			del fields["name"]
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.path.write_text(json.dumps({"default": self.default_name, "profiles": profiles}, indent=2))
