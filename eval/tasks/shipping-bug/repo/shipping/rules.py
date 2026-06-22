"""Business rules: the price multiplier for each loyalty tier.

gold customers get 10% off, silver get 5% off, and bronze customers pay full price.
"""

_MULTIPLIERS = {
    "gold": 1.1,
    "silver": 0.95,
    "bronze": 1.0,
}


def tier_multiplier(tier: str) -> float:
    """Return the price multiplier for a loyalty tier (defaults to full price)."""
    return _MULTIPLIERS.get(tier, 1.0)
