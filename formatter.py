"""
Formatter module for preparing Telegram post captions and interactive buttons in Uzbek.
"""

import html
from datetime import datetime, timezone, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from steam_api import SteamDeal
import config

UZ_MONTHS = [
    "", "yanvar", "fevral", "mart", "aprel", "may", "iyun",
    "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"
]

UZ_TZ = timezone(timedelta(hours=5))  # Uzbekistan Time (UTC+5)


def format_expiration_date(timestamp: int | str | None) -> str | None:
    """Converts a Unix timestamp or pre-formatted date string into a readable date string in Uzbek."""
    if not timestamp:
        return None
    if isinstance(timestamp, str):
        return timestamp
    try:
        dt = datetime.fromtimestamp(int(timestamp), tz=UZ_TZ)
        month_name = UZ_MONTHS[dt.month]
        return f"{dt.day}-{month_name}, {dt.strftime('%H:%M')} (Toshkent v.)"
    except Exception:
        return None


def format_deal_caption(deal: SteamDeal, channel_id: str | None = None) -> str:
    """
    Builds a beautifully styled HTML caption for a Steam deal post in Uzbek.
    Includes spacious, well-separated blocks so elements don't stick together.
    """
    if channel_id is None:
        channel_id = config.CHANNEL_ID

    safe_name = html.escape(deal.name)

    # 1. Header block: Title, Category badge, Genres
    header_lines = [f"🎮 <b><a href=\"{deal.store_url}\">{safe_name}</a></b>"]
    if "daily" in deal.source_category.lower():
        header_lines.append("⚡️ <b>Kun taklifi (Daily Deal)!</b>")
    elif "spotlight" in deal.source_category.lower():
        header_lines.append("🌟 <b>Hafta tavsiyasi (Spotlight)!</b>")
    if deal.genres:
        top_genres = ", ".join(deal.genres[:3])
        header_lines.append(f"🎭 <b>Janr:</b> {top_genres}")

    blocks = ["\n".join(header_lines)]

    # 2. Price block: Discount & Price
    if deal.discount_percent >= 100 or deal.final_price == 0:
        price_str = f"<s>${deal.original_price:.2f}</s> ➡️ <b>BEPUL! (100% chegirma) 🎁</b>"
        savings = round(deal.original_price, 2)
    else:
        savings = round(deal.original_price - deal.final_price, 2)
        price_str = f"<s>${deal.original_price:.2f}</s> ➡️ <b>${deal.final_price:.2f} {deal.currency}</b>"

    price_lines = [
        f"🔥 <b>Chegirma:</b> -{deal.discount_percent}%",
        f"💵 <b>Narx:</b> {price_str}"
    ]
    blocks.append("\n".join(price_lines))

    # 3. Savings block (if savings > 0)
    if savings > 0:
        blocks.append(f"💰 <b>Tejaladi:</b> ${savings:.2f} {deal.currency}")

    # 4. Platforms block
    platforms = []
    if deal.windows:
        platforms.append("Windows 🖥️")
    if deal.mac:
        platforms.append("macOS 🍏")
    if deal.linux:
        platforms.append("Linux/SteamOS 🐧")
    platform_str = " | ".join(platforms) if platforms else "PC"
    blocks.append(f"💻 <b>Platforma:</b> {platform_str}")

    # 5. Expiration block (if available)
    if deal.discount_expiration:
        formatted_date = format_expiration_date(deal.discount_expiration)
        if formatted_date:
            suffix = " tugaydi" if "soatdan so'ng" in formatted_date else " gacha"
            blocks.append(f"⏳ <b>Chegirma muddati:</b> {formatted_date}{suffix}")

    # 6. Footer block
    if channel_id and channel_id.startswith("@"):
        ch_clean = channel_id.lstrip("@")
        channel_link = f"https://t.me/{ch_clean}"
        footer = f"📢 <b>Kanalimiz:</b> <a href=\"{channel_link}\">@{ch_clean}</a>"
    else:
        footer = "📢 <i>Kanalimizga obuna bo'ling va eng qaynoq o'yin chegirmalaridan xabardor bo'ling!</i>"

    blocks.append(f"━━━━━━━━━━━━━━━━━━━\n{footer}")

    return "\n\n".join(blocks)


def get_deal_keyboard(deal: SteamDeal, channel_id: str | None = None) -> InlineKeyboardMarkup:
    """Returns an inline keyboard with only the Steam store link button."""
    row = [
        InlineKeyboardButton("🎮 Steam'da ochish", url=deal.store_url)
    ]
    return InlineKeyboardMarkup([row])


def format_digest_caption(deals: list[SteamDeal], channel_id: str | None = None) -> str:
    """
    Builds a clean, mobile-optimized HTML caption for a multi-deal digest post in Uzbek.
    Prevents awkward text wrapping on mobile phone screens.
    """
    if channel_id is None:
        channel_id = config.CHANNEL_ID

    lines = []

    for i, deal in enumerate(deals, 1):
        safe_name = html.escape(deal.name)

        if deal.discount_percent >= 100 or deal.final_price == 0:
            price_txt = f"<s>${deal.original_price:.2f}</s> ➡️ <b>BEPUL! 🎁</b>"
        else:
            price_txt = f"<s>${deal.original_price:.2f}</s> ➡️ <b>${deal.final_price:.2f} {deal.currency}</b>"

        lines.append(
            f"{i}. 🎮 <b><a href=\"{deal.store_url}\">{safe_name}</a></b>\n"
            f"🔥 <b>-{deal.discount_percent}%</b> | {price_txt}\n"
        )

    # Telegram channel footer
    if channel_id and channel_id.startswith("@"):
        ch_clean = channel_id.lstrip("@")
        channel_link = f"https://t.me/{ch_clean}"
        footer = f"📢 <b>Kanalimiz:</b> <a href=\"{channel_link}\">@{ch_clean}</a>"
    else:
        footer = "📢 <i>Kanalimizga obuna bo'ling va chegirmalarni o'tkazib yubormang!</i>"

    lines.append("━━━━━━━━━━━━━━━━━━━")
    lines.append(footer)

    caption = "\n".join(lines)
    if len(caption) > 1024:
        caption = caption[:1020] + "..."
    return caption

