"""
Image generator module that creates official Steam-style discount banners.
Uses official platform logos (Windows, Apple, Linux Tux, SteamOS) provided in assets/.
Appends the iconic Steam bottom bar with OS icons, green discount percent badge,
strikethrough original price, and bright discounted price.
"""

import io
import os
import logging
from pathlib import Path
import httpx
from PIL import Image, ImageDraw, ImageFont

from steam_api import SteamDeal

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"

# Fonts directory on Windows
FONT_DIR = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")
FONT_BOLD = os.path.join(FONT_DIR, "segoeuib.ttf") if os.path.exists(os.path.join(FONT_DIR, "segoeuib.ttf")) else "arialbd.ttf"
FONT_REGULAR = os.path.join(FONT_DIR, "segoeui.ttf") if os.path.exists(os.path.join(FONT_DIR, "segoeui.ttf")) else "arial.ttf"

# Steam Official Palette
STEAM_BLACK = (0, 0, 0)
STEAM_GREEN_BG = (76, 107, 34)       # #4c6b22
STEAM_LIME_TEXT = (186, 237, 22)     # #bced16 / #a4d007
STEAM_PRICE_BG = (49, 65, 80)        # #314150
STEAM_GREY_TEXT = (115, 136, 151)    # #738897
WHITE = (255, 255, 255)


def get_os_icons(deal: SteamDeal, max_height: int = 20) -> list[Image.Image]:
    """Loads and resizes official OS logos based on game platform support."""
    icons: list[Image.Image] = []

    if deal.windows:
        win_path = ASSETS_DIR / "windows.png"
        if win_path.exists():
            try:
                img = Image.open(win_path).convert("RGBA")
                scale = max_height / float(img.height)
                icons.append(img.resize((int(img.width * scale), max_height), Image.Resampling.LANCZOS))
            except Exception as e:
                logger.warning("Could not load windows.png: %s", e)

    if deal.mac:
        mac_path = ASSETS_DIR / "apple.png"
        if mac_path.exists():
            try:
                img = Image.open(mac_path).convert("RGBA")
                scale = max_height / float(img.height)
                icons.append(img.resize((int(img.width * scale), max_height), Image.Resampling.LANCZOS))
            except Exception as e:
                logger.warning("Could not load apple.png: %s", e)

    if deal.linux:
        # 1. Linux Tux Penguin Logo
        linux_path = ASSETS_DIR / "linux.png"
        if linux_path.exists():
            try:
                img = Image.open(linux_path).convert("RGBA")
                scale = max_height / float(img.height)
                icons.append(img.resize((int(img.width * scale), max_height), Image.Resampling.LANCZOS))
            except Exception as e:
                logger.warning("Could not load linux.png: %s", e)

        # 2. SteamOS Logo
        steamos_path = ASSETS_DIR / "steamos.png"
        if steamos_path.exists():
            try:
                img = Image.open(steamos_path).convert("RGBA")
                scale = max_height / float(img.height)
                icons.append(img.resize((int(img.width * scale), max_height), Image.Resampling.LANCZOS))
            except Exception as e:
                logger.warning("Could not load steamos.png: %s", e)

    return icons


async def generate_deal_banner(deal: SteamDeal, target_width: int = 800) -> bytes:
    """
    Downloads the game artwork and attaches the official Steam discount bar.
    Renders official OS logos (Windows, Apple, Linux Tux, SteamOS).
    Returns JPEG image bytes.
    """
    try:
        # 1. Download image
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(deal.image_url)
            if resp.status_code != 200:
                # Query appdetails for exact hash image URL
                app_res = await client.get(f"https://store.steampowered.com/api/appdetails?appids={deal.id}&cc=us&l=english")
                if app_res.status_code == 200:
                    real_img = app_res.json().get(str(deal.id), {}).get("data", {}).get("header_image")
                    if real_img:
                        resp = await client.get(real_img)
                if resp.status_code != 200:
                    fallback_url = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{deal.id}/header.jpg"
                    resp = await client.get(fallback_url)
                    if resp.status_code != 200:
                        raise ValueError(f"Could not download artwork: {resp.status_code}")

        art = Image.open(io.BytesIO(resp.content)).convert("RGB")

        # 2. Resize artwork to target_width
        scale = target_width / float(art.width)
        art_h = int(art.height * scale)
        art = art.resize((target_width, art_h), Image.Resampling.LANCZOS)

        # 3. Create canvas with bottom bar
        bar_h = 56
        total_h = art_h + bar_h
        canvas = Image.new("RGB", (target_width, total_h), STEAM_BLACK)
        canvas.paste(art, (0, 0))

        draw = ImageDraw.Draw(canvas)

        # 4. Paste official OS icons at bottom left
        curr_x = 24
        os_icons = get_os_icons(deal, max_height=20)
        for icon in os_icons:
            icon_y = art_h + (bar_h - icon.height) // 2
            canvas.paste(icon, (curr_x, icon_y), icon)
            curr_x += icon.width + 12

        # 5. Load fonts
        try:
            f_discount = ImageFont.truetype(FONT_BOLD, 28)
            f_orig = ImageFont.truetype(FONT_REGULAR, 14)
            f_final = ImageFont.truetype(FONT_BOLD, 18)
        except Exception:
            f_discount = ImageFont.load_default()
            f_orig = ImageFont.load_default()
            f_final = ImageFont.load_default()

        # 6. Format texts
        discount_text = f"-{deal.discount_percent}%"
        curr_symbol = "$" if deal.currency.upper() == "USD" else deal.currency

        if deal.discount_percent >= 100 or deal.final_price == 0:
            orig_text = f"{curr_symbol}{deal.original_price:.2f}"
            final_text = "FREE"
        else:
            orig_text = f"{curr_symbol}{deal.original_price:.2f}"
            final_text = f"{curr_symbol}{deal.final_price:.2f}"

        # 7. Compute box sizes dynamically based on text width
        bbox_d = draw.textbbox((0, 0), discount_text, font=f_discount)
        dt_w = bbox_d[2] - bbox_d[0]
        dt_h = bbox_d[3] - bbox_d[1]
        discount_box_w = max(96, dt_w + 28)

        bbox_o = draw.textbbox((0, 0), orig_text, font=f_orig)
        ot_w = bbox_o[2] - bbox_o[0]
        ot_h = bbox_o[3] - bbox_o[1]

        bbox_f = draw.textbbox((0, 0), final_text, font=f_final)
        ft_w = bbox_f[2] - bbox_f[0]
        ft_h = bbox_f[3] - bbox_f[1]

        price_content_w = max(ot_w, ft_w)
        price_box_w = max(112, price_content_w + 30)

        discount_box_x = target_width - discount_box_w - price_box_w
        price_box_x = target_width - price_box_w

        # 8. Draw Green Discount Box
        draw.rectangle(
            [discount_box_x, art_h, discount_box_x + discount_box_w, total_h],
            fill=STEAM_GREEN_BG,
        )
        # Center discount text inside discount box
        dt_x = discount_box_x + (discount_box_w - dt_w) // 2
        dt_y = art_h + (bar_h - dt_h) // 2 - 2
        draw.text((dt_x, dt_y), discount_text, fill=STEAM_LIME_TEXT, font=f_discount)

        # 9. Draw Dark Price Box
        draw.rectangle(
            [price_box_x, art_h, target_width, total_h],
            fill=STEAM_PRICE_BG,
        )

        # Original Price with Strikethrough (top line)
        ot_x = price_box_x + (price_box_w - ot_w) // 2
        ot_y = art_h + 8
        draw.text((ot_x, ot_y), orig_text, fill=STEAM_GREY_TEXT, font=f_orig)

        # Strikethrough line over original price
        strike_y = ot_y + ot_h // 2 + 1
        draw.line([ot_x - 3, strike_y + 1, ot_x + ot_w + 3, strike_y - 1], fill=STEAM_GREY_TEXT, width=1)

        # Final Price (bottom line)
        ft_x = price_box_x + (price_box_w - ft_w) // 2
        ft_y = art_h + bar_h - ft_h - 10
        draw.text((ft_x, ft_y), final_text, fill=STEAM_LIME_TEXT, font=f_final)

        # 10. Save to bytes buffer
        out_buf = io.BytesIO()
        canvas.save(out_buf, format="JPEG", quality=95)
        out_buf.seek(0)
        return out_buf.getvalue()

    except Exception as e:
        logger.error("Failed to generate custom Steam banner: %s", e, exc_info=True)
        return b""


async def _download_artwork_image(deal: SteamDeal, client: httpx.AsyncClient) -> Image.Image:
    """Helper to download artwork image with CDN hash and fallback mechanisms."""
    try:
        resp = await client.get(deal.image_url)
        if resp.status_code != 200:
            app_res = await client.get(
                f"https://store.steampowered.com/api/appdetails?appids={deal.id}&cc=us&l=english"
            )
            if app_res.status_code == 200:
                real_img = app_res.json().get(str(deal.id), {}).get("data", {}).get("header_image")
                if real_img:
                    resp = await client.get(real_img)
            if resp.status_code != 200:
                fallback_url = f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{deal.id}/header.jpg"
                resp = await client.get(fallback_url)
        if resp.status_code == 200:
            return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        logger.warning("Could not download artwork for deal %s: %s", deal.id, e)

    # Placeholder black image if failed
    placeholder = Image.new("RGB", (460, 215), (20, 24, 30))
    p_draw = ImageDraw.Draw(placeholder)
    p_draw.text((20, 90), deal.name[:30], fill=WHITE)
    return placeholder


async def _render_deal_card(
    deal: SteamDeal, client: httpx.AsyncClient, card_w: int, card_h: int, bar_h: int
) -> Image.Image:
    """Renders an individual game card with image and Steam bottom bar."""
    art = await _download_artwork_image(deal, client)
    art_h = card_h - bar_h

    # Resize artwork maintaining aspect ratio and crop centered
    art_scale = max(card_w / float(art.width), art_h / float(art.height))
    nw = int(art.width * art_scale)
    nh = int(art.height * art_scale)
    art_resized = art.resize((nw, nh), Image.Resampling.LANCZOS)

    x0 = (nw - card_w) // 2
    y0 = (nh - art_h) // 2
    art_cropped = art_resized.crop((x0, y0, x0 + card_w, y0 + art_h))

    card = Image.new("RGB", (card_w, card_h), STEAM_BLACK)
    card.paste(art_cropped, (0, 0))

    draw = ImageDraw.Draw(card)

    # OS icons
    icons = get_os_icons(deal, max_height=int(bar_h * 0.42))
    curr_x = 10
    for ic in icons:
        ic_y = art_h + (bar_h - ic.height) // 2
        card.paste(ic, (curr_x, ic_y), ic)
        curr_x += ic.width + 6

    # Fonts
    disc_font_size = max(16, int(bar_h * 0.48))
    final_font_size = max(12, int(bar_h * 0.36))
    orig_font_size = max(10, int(bar_h * 0.26))

    try:
        f_discount = ImageFont.truetype(FONT_BOLD, disc_font_size)
        f_orig = ImageFont.truetype(FONT_REGULAR, orig_font_size)
        f_final = ImageFont.truetype(FONT_BOLD, final_font_size)
    except Exception:
        f_discount = ImageFont.load_default()
        f_orig = ImageFont.load_default()
        f_final = ImageFont.load_default()

    discount_text = f"-{deal.discount_percent}%"
    curr_symbol = "$" if deal.currency.upper() == "USD" else deal.currency

    if deal.discount_percent >= 100 or deal.final_price == 0:
        orig_text = f"{curr_symbol}{deal.original_price:.2f}"
        final_text = "FREE"
    else:
        orig_text = f"{curr_symbol}{deal.original_price:.2f}"
        final_text = f"{curr_symbol}{deal.final_price:.2f}"

    # Measure texts
    bbox_d = draw.textbbox((0, 0), discount_text, font=f_discount)
    dt_w = bbox_d[2] - bbox_d[0]
    dt_h = bbox_d[3] - bbox_d[1]
    discount_box_w = max(int(card_w * 0.18), dt_w + 14)

    bbox_o = draw.textbbox((0, 0), orig_text, font=f_orig)
    ot_w = bbox_o[2] - bbox_o[0]
    ot_h = bbox_o[3] - bbox_o[1]

    bbox_f = draw.textbbox((0, 0), final_text, font=f_final)
    ft_w = bbox_f[2] - bbox_f[0]
    ft_h = bbox_f[3] - bbox_f[1]

    price_box_w = max(int(card_w * 0.22), max(ot_w, ft_w) + 16)
    discount_box_x = card_w - discount_box_w - price_box_w
    price_box_x = card_w - price_box_w

    # Draw Green Discount Box
    draw.rectangle([discount_box_x, art_h, discount_box_x + discount_box_w, card_h], fill=STEAM_GREEN_BG)
    dt_x = discount_box_x + (discount_box_w - dt_w) // 2
    dt_y = art_h + (bar_h - dt_h) // 2 - 1
    draw.text((dt_x, dt_y), discount_text, fill=STEAM_LIME_TEXT, font=f_discount)

    # Draw Dark Price Box
    draw.rectangle([price_box_x, art_h, card_w, card_h], fill=STEAM_PRICE_BG)

    # Strikethrough orig price
    ot_x = price_box_x + (price_box_w - ot_w) // 2
    ot_y = art_h + int(bar_h * 0.12)
    draw.text((ot_x, ot_y), orig_text, fill=STEAM_GREY_TEXT, font=f_orig)
    strike_y = ot_y + ot_h // 2
    draw.line([ot_x - 2, strike_y, ot_x + ot_w + 2, strike_y], fill=STEAM_GREY_TEXT, width=1)

    # Final price
    ft_x = price_box_x + (price_box_w - ft_w) // 2
    ft_y = art_h + bar_h - ft_h - int(bar_h * 0.16)
    draw.text((ft_x, ft_y), final_text, fill=STEAM_LIME_TEXT, font=f_final)

    return card


async def generate_digest_collage(deals: list[SteamDeal], target_width: int = 1200) -> bytes:
    """
    Generates a unified Steam-styled collage of multiple deals (e.g. 5 deals in a 2+3 layout).
    Returns JPEG bytes.
    """
    if not deals:
        return b""

    # If only 1 deal, use standard banner
    if len(deals) == 1:
        return await generate_deal_banner(deals[0], target_width=target_width)

    try:
        pad = 16
        gap = 12
        STEAM_DARK_BG = (14, 20, 27)  # #0e141b

        async with httpx.AsyncClient(timeout=25.0) as client:
            if len(deals) >= 5:
                # 5-deal layout: Row 1 has 2 large cards, Row 2 has 3 cards
                avail_w1 = target_width - 2 * pad - gap
                w1 = avail_w1 // 2
                h1 = 310
                bar_h1 = 50

                avail_w2 = target_width - 2 * pad - 2 * gap
                w2 = avail_w2 // 3
                h2 = 220
                bar_h2 = 42

                total_h = pad + h1 + gap + h2 + pad
                canvas = Image.new("RGB", (target_width, total_h), STEAM_DARK_BG)

                # Render Row 1 (2 cards)
                c0 = await _render_deal_card(deals[0], client, w1, h1, bar_h1)
                c1 = await _render_deal_card(deals[1], client, w1, h1, bar_h1)
                canvas.paste(c0, (pad, pad))
                canvas.paste(c1, (pad + w1 + gap, pad))

                # Render Row 2 (3 cards)
                y2 = pad + h1 + gap
                for i in range(3):
                    ci = await _render_deal_card(deals[2 + i], client, w2, h2, bar_h2)
                    xi = pad + i * (w2 + gap)
                    canvas.paste(ci, (xi, y2))

            elif len(deals) == 4:
                # 4-deal layout: 2x2 grid
                avail_w = target_width - 2 * pad - gap
                w = avail_w // 2
                h = 280
                bar_h = 46
                total_h = pad + h + gap + h + pad
                canvas = Image.new("RGB", (target_width, total_h), STEAM_DARK_BG)

                for i in range(4):
                    row = i // 2
                    col = i % 2
                    ci = await _render_deal_card(deals[i], client, w, h, bar_h)
                    xi = pad + col * (w + gap)
                    yi = pad + row * (h + gap)
                    canvas.paste(ci, (xi, yi))

            elif len(deals) == 3:
                # 3-deal layout: 1 row of 3
                avail_w = target_width - 2 * pad - 2 * gap
                w = avail_w // 3
                h = 260
                bar_h = 44
                total_h = pad + h + pad
                canvas = Image.new("RGB", (target_width, total_h), STEAM_DARK_BG)

                for i in range(3):
                    ci = await _render_deal_card(deals[i], client, w, h, bar_h)
                    xi = pad + i * (w + gap)
                    canvas.paste(ci, (xi, pad))

            else:  # len(deals) == 2
                # 2-deal layout: 1 row of 2
                avail_w = target_width - 2 * pad - gap
                w = avail_w // 2
                h = 320
                bar_h = 50
                total_h = pad + h + pad
                canvas = Image.new("RGB", (target_width, total_h), STEAM_DARK_BG)

                c0 = await _render_deal_card(deals[0], client, w, h, bar_h)
                c1 = await _render_deal_card(deals[1], client, w, h, bar_h)
                canvas.paste(c0, (pad, pad))
                canvas.paste(c1, (pad + w + gap, pad))

        out_buf = io.BytesIO()
        canvas.save(out_buf, format="JPEG", quality=95)
        out_buf.seek(0)
        return out_buf.getvalue()

    except Exception as e:
        logger.error("Failed to generate digest collage: %s", e, exc_info=True)
        return b""

