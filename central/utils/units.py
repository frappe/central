MILLICORES_PER_VCPU = 1000
MIB_PER_GIB = 1024


def vcpus_to_millicores(vcpus: float) -> int:
	"""Atlas takes CPU in millicores, so 0.125 vCPU is 125."""
	return round(vcpus * MILLICORES_PER_VCPU)


def millicores_to_vcpus(millicores: int) -> float:
	return millicores / MILLICORES_PER_VCPU


def gigabytes_to_mebibytes(gigabytes: float) -> int:
	return round(gigabytes * MIB_PER_GIB)


def mebibytes_to_gigabytes(mebibytes: int) -> float:
	return mebibytes / MIB_PER_GIB
