"""Apply tier-based discounts to a subtotal."""
from .rules import tier_multiplier


def apply_discount(amount: float, tier: str) -> float:
    """Scale the amount by the loyalty tier's multiplier."""
    return round(amount * tier_multiplier(tier), 2)
