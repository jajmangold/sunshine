"""Order model and top-level order processing."""
from dataclasses import dataclass, field
from typing import List
from .pricing import total_cost


@dataclass
class Order:
    items: List[float] = field(default_factory=list)
    tier: str = "bronze"


def process_order(order: "Order") -> float:
    """Process an order and return the final amount the customer owes."""
    return total_cost(order.items, order.tier)
