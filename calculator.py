from dataclasses import dataclass
from scraper import ProductInfo
from config import MARKUP_PERCENT, SHIPPING_TO_RUSSIA_PER_KG

# Approximate conversion rates to EUR
CURRENCY_TO_EUR = {
    "EUR": 1.0,
    "USD": 0.92,
    "GBP": 1.17,
    "PLN": 0.23,
    "CZK": 0.04,
    "SEK": 0.088,
    "DKK": 0.134,
    "CHF": 1.05,
    "NOK": 0.086,
}


@dataclass
class ItemCost:
    product: ProductInfo
    original_price_eur: float
    markup: float  # 25%
    shipping_portugal: float
    shipping_russia: float  # weight-based
    total_per_item: float


@dataclass
class OrderSummary:
    items: list[ItemCost]
    total_weight_kg: float
    total_cost_eur: float


def convert_to_eur(price: float, currency: str) -> float:
    """Convert price to EUR using approximate rates."""
    rate = CURRENCY_TO_EUR.get(currency, 1.0)
    return price * rate


def calculate_item_cost(product: ProductInfo) -> ItemCost:
    """Calculate full cost for a single item including all fees."""
    if product.price is None:
        original_eur = 0.0
    else:
        original_eur = convert_to_eur(product.price, product.currency)

    markup = original_eur * MARKUP_PERCENT
    shipping_portugal = product.shipping_to_portugal
    shipping_russia = product.estimated_weight_kg * SHIPPING_TO_RUSSIA_PER_KG

    total = original_eur + markup + shipping_portugal + shipping_russia

    return ItemCost(
        product=product,
        original_price_eur=round(original_eur, 2),
        markup=round(markup, 2),
        shipping_portugal=round(shipping_portugal, 2),
        shipping_russia=round(shipping_russia, 2),
        total_per_item=round(total, 2),
    )


def calculate_order(products: list[ProductInfo]) -> OrderSummary:
    """Calculate full order cost summary."""
    items = [calculate_item_cost(p) for p in products]
    total_weight = sum(p.estimated_weight_kg for p in products)
    total_cost = sum(item.total_per_item for item in items)

    return OrderSummary(
        items=items,
        total_weight_kg=round(total_weight, 2),
        total_cost_eur=round(total_cost, 2),
    )
