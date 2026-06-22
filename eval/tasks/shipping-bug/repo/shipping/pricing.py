"""Pricing: turn a basket of items plus a loyalty tier into a final cost."""
from typing import List
from .discount import apply_discount


def subtotal(items: List[float]) -> float:
    """Sum of all line items before any discount."""
    return float(sum(items))


def total_cost(items: List[float], tier: str) -> float:
    """Final cost after the customer's tier discount is applied."""
    return apply_discount(subtotal(items), tier)
