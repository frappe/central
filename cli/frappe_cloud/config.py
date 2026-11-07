import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from frappe_cloud.errors import CentralError

SAVED_FIELDS = ("url", "session_id", "csrf_token", "team")


def get_default_path() -> Path:
	"""`$FRAPPE_CLOUD_CONFIG`, else `frappe-cloud/config.json` under the XDG config directory."""
	if path := os.environ.get("FRAPPE_CLOUD_CONFIG"):
		return Path(path)

	base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
	return Path(base) / "frappe-cloud" / "config.json"


@dataclass
class Config:
	"""The site you signed in to, its session and the default team. Central holds everything else."""

	path: Path = field(default_factory=get_default_path)
	url: str | None = None
	session_id: str | None = None
	csrf_token: str | None = None
	team: str | None = None

	@classmethod
	def load(cls, path: Path | None = None) -> "Config":
		path = path or get_default_path()
		if not path.exists():
			return cls(path=path)

		try:
			values = json.loads(path.read_text())
		except (OSError, ValueError) as error:
			raise CentralError(f"Could not read {path}: {error}. Fix or remove the file.")
		if not isinstance(values, dict):
			raise CentralError(f"{path} is not a Central config. Fix or remove the file.")

		return cls(path=path, **{key: values.get(key) for key in SAVED_FIELDS})

	def save(self) -> None:
		"""Replace the file in one step with one that only its owner can read, because it holds a session."""
		self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
		descriptor, temporary_path = tempfile.mkstemp(dir=self.path.parent, prefix=".config-")
		try:
			with os.fdopen(descriptor, "w") as file:
				json.dump({key: getattr(self, key) for key in SAVED_FIELDS}, file, indent=2)
			os.replace(temporary_path, self.path)
		except BaseException:
			os.unlink(temporary_path)
			raise

	def get_saved_for(self, url: str | None) -> "Config":
		"""This config when it was saved for `url`, else an empty one, so a session never goes to another site."""
		if url and url.rstrip("/") == self.url:
			return self
		return Config(path=self.path)

	def clear_session(self) -> None:
		self.session_id = None
		self.csrf_token = None
		self.team = None
