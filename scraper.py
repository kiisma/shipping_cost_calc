import re
import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Optional

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,pt;q=0.8",
}


@dataclass
class ProductInfo:
    url: str
    name: str
    price: Optional[float]  # EUR
    currency: str
    shipping_to_portugal: float  # 0 if free
    estimated_weight_kg: float


def fetch_page(url: str) -> Optional[BeautifulSoup]:
    """Fetch a web page and return parsed HTML."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "lxml")
    except Exception:
        return None


def _extract_price_from_text(text: str) -> Optional[float]:
    """Try to extract a numeric price from text."""
    # Remove spaces inside numbers like "1 299,99"
    cleaned = re.sub(r"(\d)\s+(\d)", r"\1\2", text)
    # Match patterns like 29.99, 29,99, 1299.99, 1299,99
    match = re.search(r"(\d+[.,]?\d*)", cleaned)
    if match:
        price_str = match.group(1).replace(",", ".")
        try:
            return float(price_str)
        except ValueError:
            return None
    return None


def _detect_currency(soup: BeautifulSoup, text: str) -> str:
    """Detect currency from page content."""
    full_text = soup.get_text().lower() + text.lower()
    if "€" in full_text or "eur" in full_text:
        return "EUR"
    if "$" in full_text or "usd" in full_text:
        return "USD"
    if "£" in full_text or "gbp" in full_text:
        return "GBP"
    return "EUR"  # default


def _find_price(soup: BeautifulSoup) -> tuple[Optional[float], str]:
    """Extract product price from page HTML."""
    # Common price selectors used by e-commerce sites
    price_selectors = [
        '[class*="price" i]',
        '[class*="Price" i]',
        '[id*="price" i]',
        '[data-price]',
        '[itemprop="price"]',
        '[class*="cost" i]',
        '[class*="amount" i]',
    ]

    # First try structured data (JSON-LD)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0]
            # Look for price in offers
            offers = data.get("offers", data)
            if isinstance(offers, list):
                offers = offers[0]
            price_val = offers.get("price") or offers.get("lowPrice")
            if price_val:
                currency = offers.get("priceCurrency", "EUR")
                return float(price_val), currency
        except Exception:
            continue

    # Try meta tags
    meta_price = soup.find("meta", {"property": "product:price:amount"})
    if meta_price and meta_price.get("content"):
        try:
            price = float(meta_price["content"])
            meta_currency = soup.find("meta", {"property": "product:price:currency"})
            currency = meta_currency["content"] if meta_currency else "EUR"
            return price, currency
        except (ValueError, TypeError):
            pass

    # Try common CSS selectors
    for selector in price_selectors:
        elements = soup.select(selector)
        for el in elements:
            text = el.get_text(strip=True)
            price = _extract_price_from_text(text)
            if price and 0.01 < price < 100000:
                currency = _detect_currency(soup, text)
                return price, currency

    return None, "EUR"


def _find_name(soup: BeautifulSoup) -> str:
    """Extract product name from page."""
    # Try structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0]
            name = data.get("name")
            if name:
                return name[:200]
        except Exception:
            continue

    # Try og:title
    og_title = soup.find("meta", {"property": "og:title"})
    if og_title and og_title.get("content"):
        return og_title["content"][:200]

    # Try h1
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)[:200]

    # Fallback to title
    title = soup.find("title")
    if title:
        return title.get_text(strip=True)[:200]

    return "Unknown product"


def _check_free_shipping_to_portugal(soup: BeautifulSoup) -> float:
    """Check if shipping to Portugal is free. Returns estimated shipping cost."""
    text = soup.get_text().lower()
    free_indicators = [
        "free shipping", "free delivery",
        "frete gratis", "frete grátis", "envio gratuito", "envio grátis",
        "kostenloser versand", "livraison gratuite",
        "entrega gratuita", "entrega gratis",
    ]
    for indicator in free_indicators:
        if indicator in text:
            return 0.0
    # If no free shipping found, estimate ~5 EUR for shipping to Portugal
    return 5.0


# Approximate weight estimation by product category keywords
WEIGHT_ESTIMATES = {
    # Clothing
    "t-shirt": 0.2, "tshirt": 0.2, "shirt": 0.3, "blouse": 0.2,
    "dress": 0.4, "jeans": 0.6, "pants": 0.5, "trousers": 0.5,
    "jacket": 0.8, "coat": 1.2, "sweater": 0.5, "hoodie": 0.6,
    "skirt": 0.3, "shorts": 0.3, "underwear": 0.1, "socks": 0.1,
    "scarf": 0.15, "hat": 0.15, "cap": 0.15, "gloves": 0.1,
    "suit": 1.0, "blazer": 0.7,
    # Shoes
    "shoes": 0.8, "boots": 1.2, "sneakers": 0.8, "sandals": 0.5,
    "heels": 0.6, "slippers": 0.3,
    # Bags
    "bag": 0.5, "backpack": 0.7, "handbag": 0.6, "wallet": 0.15,
    "purse": 0.3, "luggage": 3.0, "suitcase": 4.0,
    # Electronics
    "phone": 0.3, "laptop": 2.0, "tablet": 0.6, "headphones": 0.3,
    "earbuds": 0.1, "charger": 0.15, "cable": 0.1, "watch": 0.2,
    "camera": 0.8, "speaker": 0.5,
    # Beauty
    "perfume": 0.3, "cream": 0.2, "serum": 0.15, "makeup": 0.2,
    "lipstick": 0.05, "mascara": 0.05, "foundation": 0.15,
    # Home
    "pillow": 0.8, "towel": 0.4, "blanket": 1.5, "candle": 0.3,
    "mug": 0.3, "plate": 0.5, "cup": 0.2, "vase": 0.5,
    # Sports
    "ball": 0.4, "yoga": 1.0, "dumbbell": 2.0,
    # Toys
    "toy": 0.3, "puzzle": 0.4, "game": 0.5, "lego": 0.5,
    # Accessories
    "ring": 0.05, "necklace": 0.1, "bracelet": 0.1, "earring": 0.05,
    "belt": 0.2, "tie": 0.1, "sunglasses": 0.1,
    # Portuguese keywords
    "camiseta": 0.2, "camisa": 0.3, "vestido": 0.4,
    "calca": 0.5, "calças": 0.5, "jaqueta": 0.8, "casaco": 1.0,
    "sapato": 0.8, "sapatos": 0.8, "bota": 1.2, "botas": 1.2,
    "tenis": 0.8, "tênis": 0.8, "mochila": 0.7, "bolsa": 0.5,
    "carteira": 0.15, "relogio": 0.2, "relógio": 0.2,
    # Russian keywords
    "футболка": 0.2, "рубашка": 0.3, "платье": 0.4,
    "джинсы": 0.6, "брюки": 0.5, "куртка": 0.8, "пальто": 1.2,
    "свитер": 0.5, "толстовка": 0.6, "юбка": 0.3,
    "обувь": 0.8, "кроссовки": 0.8, "сумка": 0.5, "рюкзак": 0.7,
    "часы": 0.2, "телефон": 0.3, "ноутбук": 2.0,
}

DEFAULT_WEIGHT_KG = 0.5


def _estimate_weight(name: str) -> float:
    """Estimate product weight based on its name."""
    name_lower = name.lower()
    for keyword, weight in WEIGHT_ESTIMATES.items():
        if keyword in name_lower:
            return weight
    return DEFAULT_WEIGHT_KG


def scrape_product(url: str) -> Optional[ProductInfo]:
    """Scrape product information from a URL."""
    soup = fetch_page(url)
    if soup is None:
        return None

    name = _find_name(soup)
    price, currency = _find_price(soup)
    shipping_to_portugal = _check_free_shipping_to_portugal(soup)
    estimated_weight = _estimate_weight(name)

    return ProductInfo(
        url=url,
        name=name,
        price=price,
        currency=currency,
        shipping_to_portugal=shipping_to_portugal,
        estimated_weight_kg=estimated_weight,
    )
