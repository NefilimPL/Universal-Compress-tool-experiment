from .models import CostLevel


def classify_operation_cost(total_bytes: int, encrypted: bool, media_mode: bool) -> CostLevel:
    if media_mode:
        return CostLevel.HIGH if total_bytes >= 2 * 1024**3 else CostLevel.MEDIUM

    if encrypted and total_bytes >= 2 * 1024**3:
        return CostLevel.HIGH

    if total_bytes >= 512 * 1024**2:
        return CostLevel.MEDIUM

    return CostLevel.LOW
