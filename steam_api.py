"""
Steam Store API client for fetching specials, discounts, and daily deals.
Uses official Steam Store endpoints without requiring an API key.
"""

from dataclasses import dataclass, field
import asyncio
import logging
import re
import httpx
from bs4 import BeautifulSoup
from config import (
    COUNTRY_CODE,
    MIN_DISCOUNT_PERCENT,
    FILTER_ADULT_CONTENT,
    BLOCK_ALL_NUDITY,
    MIN_PRICE_USD,
)

logger = logging.getLogger(__name__)

# Explicit adult / hentai / sexual keywords
BLOCKED_TITLE_KEYWORDS = [
    r"\bsex\b", r"\bhentai\b", r"\bporn\b", r"\berotic\b", r"\berotica\b",
    r"\bxxx\b", r"\badult only\b", r"\blust\b", r"\blewd\b", r"\becchi\b",
    r"\bboobs\b", r"\bnudity\b", r"\bfetish\b", r"\bwaifu\b", r"\byaoi\b", r"\byuri\b"
]

# Non-genre meta tags to filter out when parsing popular community tags
NON_GENRE_TAGS = {
    # Player modes
    "singleplayer", "multiplayer", "co-op", "online co-op", "local co-op",
    "pvp", "pve", "cross-platform multiplayer", "co-op campaign",
    # Hardware & features
    "vr", "vr only", "tracked controller support", "full controller support",
    "partial controller support", "controller", "remote play", "cloud", "steam cloud",
    "steam achievements", "trading cards", "captions available", "commentary available",
    # Mature / Content flags (handled separately, not genres)
    "gore", "nudity", "sexual content", "nsfw", "violent", "blood", "mature",
    # Subjective / Meta descriptors
    "great soundtrack", "soundtrack", "atmospheric", "difficult",
    "masterpiece", "memes", "funny", "female protagonist", "cinematic",
    "replay value", "moddable", "physics", "relaxing", "casual",
    # Technical / Release formats
    "2d", "3d", "realistic", "stylized", "short", "early access", "retro",
    "remake", "reboot", "sequel"
}


def clean_tags(tags: list[str], max_count: int = 3) -> list[str]:
    """Filters out non-genre meta tags and returns top genuine genre tags."""
    result = []
    for t in tags:
        clean = t.strip()
        if clean and clean.lower() not in NON_GENRE_TAGS:
            result.append(clean)
        if len(result) >= max_count:
            break
    return result


MONTH_MAP = {
    "january": "yanvar", "february": "fevral", "march": "mart", "april": "aprel",
    "may": "may", "june": "iyun", "july": "iyul", "august": "avgust",
    "september": "sentabr", "october": "oktabr", "november": "noyabr", "december": "dekabr",
    "jan": "yanvar", "feb": "fevral", "mar": "mart", "apr": "aprel",
    "jun": "iyun", "jul": "iyul", "aug": "avgust", "sep": "sentabr",
    "oct": "oktabr", "nov": "noyabr", "dec": "dekabr"
}


def parse_countdown_text(raw_text: str) -> str | None:
    """Parses Steam's discount countdown text into a localized Uzbek string."""
    if not raw_text:
        return None
    m = re.search(r"ends\s+(\d{1,2})\s+([a-zA-Z]+)", raw_text, re.IGNORECASE)
    if m:
        day = m.group(1)
        month_en = m.group(2).lower()
        for en_k, uz_v in MONTH_MAP.items():
            if en_k.startswith(month_en):
                return f"{day}-{uz_v}, 22:00 (Toshkent v.)"
    m_hours = re.search(r"ends in (\d+)\s+hours?", raw_text, re.IGNORECASE)
    if m_hours:
        h = m_hours.group(1)
        return f"{h} soatdan so'ng"
    return None


FEATURED_CATEGORIES_URL = "https://store.steampowered.com/api/featuredcategories"
FEATURED_URL = "https://store.steampowered.com/api/featured"


@dataclass
class SteamDeal:
    id: int
    name: str
    discount_percent: int
    original_price: float
    final_price: float
    currency: str
    image_url: str
    store_url: str
    windows: bool
    mac: bool
    linux: bool
    discount_expiration: int | str | None
    source_category: str
    genres: list[str] = field(default_factory=list)


class SteamAPI:
    def __init__(self, country_code: str = COUNTRY_CODE, language: str = "english"):
        self.country_code = country_code
        self.language = language
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _parse_item(self, item: dict, category_name: str) -> SteamDeal | None:
        """Parses a raw item dictionary from Steam API into a SteamDeal dataclass."""
        try:
            if not item.get("discounted", False):
                return None

            discount_pct = int(item.get("discount_percent", 0))
            if discount_pct < MIN_DISCOUNT_PERCENT:
                return None

            app_id = int(item.get("id"))
            name = str(item.get("name", "Noma'lum o'yin")).strip()
            
            # Currency & Prices (Steam sends in cents)
            currency = str(item.get("currency", "USD"))
            orig_price_raw = item.get("original_price", 0)
            final_price_raw = item.get("final_price", 0)

            orig_price = round(orig_price_raw / 100.0, 2) if orig_price_raw else 0.0
            final_price = round(final_price_raw / 100.0, 2) if final_price_raw else 0.0

            # Images: large_capsule_image looks best on Telegram (616x353), fallback to header_image
            image_url = (
                item.get("large_capsule_image")
                or item.get("header_image")
                or f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg"
            )

            store_url = f"https://store.steampowered.com/app/{app_id}/"
            windows = bool(item.get("windows_available", True))
            mac = bool(item.get("mac_available", False))
            linux = bool(item.get("linux_available", False))
            expiration = item.get("discount_expiration")
            expiration_ts = int(expiration) if expiration else None

            return SteamDeal(
                id=app_id,
                name=name,
                discount_percent=discount_pct,
                original_price=orig_price,
                final_price=final_price,
                currency=currency,
                image_url=image_url,
                store_url=store_url,
                windows=windows,
                mac=mac,
                linux=linux,
                discount_expiration=expiration_ts,
                source_category=category_name,
            )
        except Exception as e:
            logger.warning("Error parsing Steam item %s: %s", item.get("id"), e)
            return None

    async def fetch_featured_categories(self) -> list[SteamDeal]:
        """Fetches deals from /api/featuredcategories."""
        params = {"cc": self.country_code, "l": self.language}
        deals: list[SteamDeal] = []

        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=15.0) as client:
                resp = await client.get(FEATURED_CATEGORIES_URL, params=params)
                if resp.status_code != 200:
                    logger.error("Steam API returned %s: %s", resp.status_code, resp.text[:200])
                    return deals

                data = resp.json()
                for key, category in data.items():
                    if isinstance(category, dict) and "items" in category:
                        cat_name = category.get("name", key)
                        for it in category.get("items", []):
                            deal = self._parse_item(it, cat_name)
                            if deal:
                                deals.append(deal)

        except Exception as e:
            logger.error("Error fetching featured categories: %s", e)

        return deals

    async def fetch_featured(self) -> list[SteamDeal]:
        """Fetches deals from /api/featured."""
        params = {"cc": self.country_code, "l": self.language}
        deals: list[SteamDeal] = []

        try:
            async with httpx.AsyncClient(headers=self.headers, timeout=15.0) as client:
                resp = await client.get(FEATURED_URL, params=params)
                if resp.status_code != 200:
                    return deals

                data = resp.json()
                for key, items in data.items():
                    if isinstance(items, list):
                        for it in items:
                            if isinstance(it, dict):
                                deal = self._parse_item(it, "Featured")
                                if deal:
                                    deals.append(deal)
        except Exception as e:
            logger.error("Error fetching featured deals: %s", e)

        return deals

    async def fetch_search_specials(self, max_pages: int = 3) -> list[SteamDeal]:
        """
        Fetches top discounted games from the Steam store search catalog.
        Captures major AAA titles and top-selling deals that may not be on the front page.
        """
        deals: list[SteamDeal] = []
        try:
            from bs4 import BeautifulSoup
            async with httpx.AsyncClient(headers=self.headers, timeout=15.0) as client:
                for page in range(max_pages):
                    start = page * 50
                    url = (
                        f"https://store.steampowered.com/search/results/?query="
                        f"&start={start}&count=50&specials=1&infinite=1"
                        f"&cc={self.country_code}&l={self.language}"
                    )
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    html_content = data.get("results_html", "")
                    if not html_content:
                        continue
                    soup = BeautifulSoup(html_content, "html.parser")
                    for row in soup.find_all("a", {"class": "search_result_row"}):
                        appid_raw = row.get("data-ds-appid")
                        if not appid_raw or "," in appid_raw:
                            continue
                        try:
                            appid = int(appid_raw)
                        except ValueError:
                            continue

                        title_el = row.find("span", {"class": "title"})
                        title = title_el.text.strip() if title_el else ""
                        if not title:
                            continue

                        disc_el = row.find("div", {"class": "discount_pct"})
                        if not disc_el:
                            continue
                        disc_num = re.sub(r"[^\d]", "", disc_el.text)
                        discount_pct = int(disc_num) if disc_num else 0
                        if discount_pct < MIN_DISCOUNT_PERCENT:
                            continue

                        orig_el = row.find("div", {"class": "discount_original_price"})
                        final_el = row.find("div", {"class": "discount_final_price"})

                        orig_price = 0.0
                        if orig_el:
                            match = re.search(r"[\d.]+", orig_el.text.replace(",", ""))
                            if match:
                                orig_price = float(match.group(0))

                        final_price = 0.0
                        if final_el:
                            match = re.search(r"[\d.]+", final_el.text.replace(",", ""))
                            if match:
                                final_price = float(match.group(0))

                        win = bool(row.find("span", {"class": "win"}))
                        mac = bool(row.find("span", {"class": "mac"}))
                        linux = bool(row.find("span", {"class": "linux"}))

                        image_url = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/header.jpg"
                        store_url = f"https://store.steampowered.com/app/{appid}/"

                        deal = SteamDeal(
                            id=appid,
                            name=title,
                            discount_percent=discount_pct,
                            original_price=orig_price,
                            final_price=final_price,
                            currency="USD",
                            image_url=image_url,
                            store_url=store_url,
                            windows=win,
                            mac=mac,
                            linux=linux,
                            discount_expiration=None,
                            source_category="Top Specials",
                        )
                        deals.append(deal)
        except Exception as e:
            logger.error("Error fetching search specials catalog: %s", e)

        return deals

    async def get_all_current_deals(self) -> list[SteamDeal]:
        """
        Fetches all current deals from featured categories, featured page,
        and the top specials search catalog. Deduplicates by app ID.
        """
        cat_deals = await self.fetch_featured_categories()
        feat_deals = await self.fetch_featured()
        search_deals = await self.fetch_search_specials(max_pages=3)

        unique_deals: dict[int, SteamDeal] = {}
        for deal in cat_deals + feat_deals + search_deals:
            if deal.id not in unique_deals:
                unique_deals[deal.id] = deal
            else:
                existing = unique_deals[deal.id]
                if not existing.discount_expiration and deal.discount_expiration:
                    existing.discount_expiration = deal.discount_expiration
                if deal.discount_percent > existing.discount_percent:
                    exp = existing.discount_expiration or deal.discount_expiration
                    unique_deals[deal.id] = deal
                    unique_deals[deal.id].discount_expiration = exp

        result = list(unique_deals.values())
        return result



async def is_deal_safe(deal: SteamDeal, client: httpx.AsyncClient | None = None) -> tuple[bool, str]:
    """
    Checks whether a deal is safe to post to the public Telegram channel.
    Filters:
    - 18+ Adult-Only / Explicit Sexual / Hentai content
    - Titles with explicit adult keywords
    - Optional: Min price USD filter
    Mainstream games with mature themes (GTA, Witcher, Cyberpunk) are NOT blocked.
    """
    if MIN_PRICE_USD > 0 and deal.final_price < MIN_PRICE_USD:
        return False, f"Narx minimal chegara (${MIN_PRICE_USD}) dan past (${deal.final_price})"

    if not FILTER_ADULT_CONTENT:
        return True, "OK"

    # 1. Check title keywords
    deal_name_lower = deal.name.lower()
    for pattern in BLOCKED_TITLE_KEYWORDS:
        if re.search(pattern, deal_name_lower, re.IGNORECASE):
            return False, f"Nomi taqiqlangan so'z o'z ichiga olgan ({pattern})"

    # 2. Check Steam official content descriptors & enrich deal details (tags, image, regional price, expiration)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    cookies = {"birthtime": "788918401", "wants_mature_content": "1"}

    try:
        should_close = False
        if client is None:
            client = httpx.AsyncClient(timeout=15.0)
            should_close = True

        app_url = f"https://store.steampowered.com/api/appdetails?appids={deal.id}&cc={COUNTRY_CODE}&l=english"
        store_url = f"https://store.steampowered.com/app/{deal.id}/"

        app_res, store_res = await asyncio.gather(
            client.get(app_url, headers=headers),
            client.get(store_url, headers=headers, cookies=cookies),
            return_exceptions=True,
        )

        if should_close:
            await client.aclose()

        publisher_genres: list[str] = []
        if not isinstance(app_res, Exception) and getattr(app_res, "status_code", 0) == 200:
            app_data = app_res.json().get(str(deal.id), {}).get("data", {})
            # Populate real CDN header image with hash
            real_header = app_data.get("header_image")
            if real_header:
                deal.image_url = real_header

            # Populate exact regional price for target country if available
            price_info = app_data.get("price_overview")
            if price_info:
                init_cents = price_info.get("initial", 0)
                final_cents = price_info.get("final", 0)
                if init_cents:
                    deal.original_price = round(init_cents / 100.0, 2)
                if final_cents:
                    deal.final_price = round(final_cents / 100.0, 2)
                if price_info.get("currency"):
                    deal.currency = price_info.get("currency")

            # Fallback publisher genres
            raw_genres = app_data.get("genres", [])
            publisher_genres = [g.get("description", "").strip() for g in raw_genres if g.get("description")]

            cd = app_data.get("content_descriptors", {})
            ids = set(cd.get("ids", []))

            # Descriptor 3: Adult Only Sexual Content
            # Descriptor 4: Frequent Nudity or Sexual Content
            blocked_ids = {3, 4}
            if BLOCK_ALL_NUDITY:
                blocked_ids.add(1)

            inter = ids.intersection(blocked_ids)
            if inter:
                return False, f"Steam 18+/Behayo kontent deskriptori ({inter})"

        # Extract genuine community tags & discount countdown from Steam store page
        community_genres: list[str] = []
        if not isinstance(store_res, Exception) and getattr(store_res, "status_code", 0) == 200:
            try:
                soup = BeautifulSoup(store_res.text, "html.parser")
                raw_tags = [t.text.strip() for t in soup.find_all("a", {"class": "app_tag"})]
                community_genres = clean_tags(raw_tags, max_count=3)

                # Extract countdown if expiration not already known
                if not deal.discount_expiration:
                    countdown_el = soup.find("p", {"class": "game_purchase_discount_countdown"})
                    if countdown_el and countdown_el.text:
                        parsed_exp = parse_countdown_text(countdown_el.text.strip())
                        if parsed_exp:
                            deal.discount_expiration = parsed_exp
            except Exception as e_tag:
                logger.debug("Could not parse store page for %s: %s", deal.id, e_tag)

        # Prioritize accurate community tags, fallback to publisher genres
        if community_genres:
            deal.genres = community_genres
        elif publisher_genres:
            deal.genres = publisher_genres[:3]

    except Exception as e:
        logger.warning("Could not check content descriptors for %s: %s", deal.id, e)

    return True, "OK"

