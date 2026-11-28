"""Sample Python module for Sakura Code live demonstration."""


def compute_discount(price: float, percent: float) -> float:
    """Apply a percentage discount to a non-negative price."""
    if price < 0:
        raise ValueError("price must be non-negative")
    if not (0 <= percent <= 100):
        raise ValueError("percent must be between 0 and 100")
    return round(price * (1.0 - percent / 100.0), 2)


def batch_total(items: list[tuple[float, float]]) -> float:
    """Sum discounted prices for (price, percent) pairs."""
    return round(sum(compute_discount(p, pct) for p, pct in items), 2)
