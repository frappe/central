import os
from argparse import Namespace
from dataclasses import dataclass

from frappe_cloud.client import CentralClient
from frappe_cloud.config import Config
from frappe_cloud.output import Output


@dataclass
class Context:
	"""What a command handler works with: the client, the saved config and the output."""

	client: CentralClient
	config: Config
	output: Output

	@classmethod
	def create(cls, args: Namespace, config: Config | None = None) -> "Context":
		"""Flags win over the environment, and the environment wins over the saved config."""
		config = config or Config.load()
		client = CentralClient(
			args.url or os.environ.get("FRAPPE_CLOUD_URL") or config.url,
			session_id=config.session_id,
			csrf_token=config.csrf_token,
			api_key=os.environ.get("FRAPPE_CLOUD_API_KEY"),
			api_secret=os.environ.get("FRAPPE_CLOUD_API_SECRET"),
			team=args.team or os.environ.get("FRAPPE_CLOUD_TEAM") or config.team,
		)
		return cls(client=client, config=config, output=Output(is_json=args.json))
