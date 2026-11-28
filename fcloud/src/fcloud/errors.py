class FcloudError(Exception):
	"""A failure the person running the command reads and can act on."""

	def __init__(self, message: str):
		super().__init__(message)
		self.message = message


class CentralError(FcloudError):
	"""A request that Central refused."""

	def __init__(self, message: str, status: int = 0, kind: str = ""):
		super().__init__(message)
		self.status = status
		self.kind = kind


class LoginError(FcloudError):
	"""Missing, expired, or rejected credentials. Logging in again fixes it."""
