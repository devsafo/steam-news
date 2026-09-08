"""
Main Telegram Bot module for Steam Game Deals Channel.
Automates fetching Steam discounts and posting them to a Telegram channel.
"""

import sys
import asyncio
import logging
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from telegram import Update, Bot
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import io
import config
import database
from steam_api import SteamAPI, SteamDeal, is_deal_safe
from formatter import (
    format_deal_caption,
    get_deal_keyboard,
    format_digest_caption,
)
from image_generator import generate_deal_banner, generate_digest_collage

# Configure logging
logging.basicConfig(
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("SteamBot")


POST_LOCK = asyncio.Lock()


async def post_deal_to_channel(bot: Bot, deal: SteamDeal, channel_id: str) -> bool:
    """
    Sends a single deal post to the target Telegram channel.
    Guarantees posts ALWAYS have images. Never sends text-only fallbacks to prevent duplicates.
    Returns True if successful, False otherwise.
    """
    caption = format_deal_caption(deal, channel_id)

    # 1. First attempt with custom Steam banner overlay
    try:
        banner_bytes = await generate_deal_banner(deal)
        photo_payload = io.BytesIO(banner_bytes) if banner_bytes else deal.image_url

        await bot.send_photo(
            chat_id=channel_id,
            photo=photo_payload,
            caption=caption,
            parse_mode=ParseMode.HTML,
            read_timeout=45,
            write_timeout=45,
        )
        return True
    except Exception as e:
        logger.warning("Rasm yuklashda 1-urinishda xatolik (%s): %s. 3 soniyadan so'ng qayta urinilmoqda...", deal.name, e)
        await asyncio.sleep(3.0)

    # 2. Second retry attempt directly with Steam CDN image URL
    try:
        await bot.send_photo(
            chat_id=channel_id,
            photo=deal.image_url,
            caption=caption,
            parse_mode=ParseMode.HTML,
            read_timeout=45,
            write_timeout=45,
        )
        return True
    except Exception as err:
        logger.error("Rasm yuborish mutlaqo amalga oshmadi (%s): %s. Dublikat bo'lmasligi uchun post bekor qilindi.", deal.name, err)
        return False


async def post_digest_to_channel(bot: Bot, deals: list[SteamDeal], channel_id: str) -> bool:
    """
    Builds and posts a unified digest post containing multiple deals with a custom collage image.
    """
    if not deals:
        return False

    caption = format_digest_caption(deals, channel_id)

    try:
        collage_bytes = await generate_digest_collage(deals)
        if collage_bytes:
            photo_payload = io.BytesIO(collage_bytes)
            await bot.send_photo(
                chat_id=channel_id,
                photo=photo_payload,
                caption=caption,
                parse_mode=ParseMode.HTML,
                read_timeout=60,
                write_timeout=60,
            )
            logger.info(f"Jamlanma (digest) posti {len(deals)} ta o'yin bilan kanalga muvaffaqiyatli yuborildi!")
            return True
        else:
            logger.warning("Kollaj tasviri yaratilmadi.")
            return False
    except Exception as e:
        logger.error(f"Jamlanma postini yuborishda xatolik: {e}", exc_info=True)
        return False


async def check_and_post_deals(bot: Bot) -> int:
    """
    Checks Steam for current deals, compares against database,
    and posts newly discovered deals to the channel.
    After completing the batch, immediately posts a unified digest post.
    Guarantees no duplicate posts via POST_LOCK mutex.
    """
    if POST_LOCK.locked():
        logger.info("Tekshiruv boshqa vazifa tomonidan bajarilmoqda. Kutib turiladi...")

    async with POST_LOCK:
        logger.info("Steam API dan chegirmalar qidirilmoqda...")
        api = SteamAPI()
        deals = await api.get_all_current_deals()

        if not deals:
            logger.info("Hech qanday chegirmali o'yin topilmadi.")
            return 0

        posted_count = 0
        newly_posted_deals: list[SteamDeal] = []
        logger.info(f"Steam API dan jami {len(deals)} ta chegirma olindi. Yangilari filtrlanmoqda...")

        for deal in deals:
            if database.is_game_posted(deal.id):
                continue

            # Check content filter (18+ / Adult-Only / Blocked keywords)
            is_safe, reason = await is_deal_safe(deal)
            if not is_safe:
                logger.info(f"O'yin filtrdan o'tmadi: {deal.name} ({reason}). E'lon qilinmaydi.")
                # Record in DB so it won't be queried repeatedly
                database.mark_game_posted(
                    app_id=deal.id,
                    name=deal.name,
                    discount_percent=deal.discount_percent,
                    original_price=deal.original_price,
                    final_price=deal.final_price,
                    currency=deal.currency,
                    expiration_timestamp=deal.discount_expiration,
                )
                continue

            if posted_count >= config.MAX_POSTS_PER_RUN:
                logger.info(
                    f"Bir martalik limitga ({config.MAX_POSTS_PER_RUN} ta) yetildi. Qolganlari keyingi siklda tekshiriladi."
                )
                break

            logger.info(f"Yangi chegirma topildi: {deal.name} (-{deal.discount_percent}%). Kanalga yuborilmoqda...")
            success = await post_deal_to_channel(bot, deal, config.CHANNEL_ID)

            if success:
                database.mark_game_posted(
                    app_id=deal.id,
                    name=deal.name,
                    discount_percent=deal.discount_percent,
                    original_price=deal.original_price,
                    final_price=deal.final_price,
                    currency=deal.currency,
                    expiration_timestamp=deal.discount_expiration,
                )
                posted_count += 1
                newly_posted_deals.append(deal)
                # Rate limit protection between Telegram channel posts (3 seconds)
                await asyncio.sleep(3.0)

        # 5 talik (yoki kamida 2 talik) o'yinlar muvaffaqiyatli post qilingach, ularni birlashtirgan yaxlit jamlanma chiqariladi
        if len(newly_posted_deals) >= 2:
            logger.info(f"{len(newly_posted_deals)} ta o'yin bo'yicha yaxlit jamlanma (digest) posti tayyorlanmoqda...")
            await asyncio.sleep(3.0)
            await post_digest_to_channel(bot, newly_posted_deals, config.CHANNEL_ID)

        return posted_count


async def scheduler_loop(app: Application):
    """
    Background asynchronous loop that periodically triggers deal checks.
    """
    logger.info(
        f"Avtomatik tekshiruv xizmati (Scheduler) faollashdi. Interval: {config.CHECK_INTERVAL_MINUTES} daqiqa."
    )
    # Wait 5 seconds after startup before first check
    await asyncio.sleep(5)

    while True:
        try:
            posted = await check_and_post_deals(app.bot)
            if posted > 0:
                logger.info(f"Muvaffaqiyatli: {posted} ta yangi chegirma kanalga joylandi.")
            else:
                logger.info("Hozircha yangi e'lon qilinmagan chegirma yo'q.")
        except Exception as e:
            logger.error(f"Scheduler siklida xatolik yuz berdi: {e}", exc_info=True)

        await asyncio.sleep(config.CHECK_INTERVAL_MINUTES * 60)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command."""
    posted_count = database.get_posted_count()
    text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Men <b>Steam Chegirmalari Boti</b>man 🎮\n"
        "Steam rasmiy do'konidagi eng yaxshi o'yin chegirmalarini avtomatik ravishda kuzatib, "
        "Telegram kanalga joylab boraman.\n\n"
        f"📢 <b>Ulangan kanal:</b> <code>{config.CHANNEL_ID}</code>\n"
        f"⏱ <b>Tekshiruv oralig'i:</b> har {config.CHECK_INTERVAL_MINUTES} daqiqada\n"
        f"📊 <b>Bazadagi postlar:</b> {posted_count} ta o'yin\n\n"
        "<b>Mavjud buyruqlar:</b>\n"
        "🔹 /deals - Hozirgi eng yaxshi chegirmalarni ko'rish\n"
        "🔹 /check - Kanalga yangi chegirmalarni hoziroq tekshirib post qilish\n"
        "🔹 /status - Bot va ma'lumotlar bazasi holati\n"
        "🔹 /help - Bot haqida yordam"
    )
    await update.message.reply_html(text)


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to manually trigger check and post deals immediately."""
    user_id = update.effective_user.id
    if config.ADMIN_ID and user_id != config.ADMIN_ID:
        await update.message.reply_text("⛔️ Ushbu buyruq faqat bot administratori uchun!")
        return

    status_msg = await update.message.reply_text("⏳ Steam API tekshirilmoqda va yangi postlar kanalga yuborilmoqda...")
    try:
        count = await check_and_post_deals(context.bot)
        if count > 0:
            await status_msg.edit_text(f"✅ Tekshiruv yakunlandi! <b>{count}</b> ta yangi chegirma kanalga joylandi.", parse_mode=ParseMode.HTML)
        else:
            await status_msg.edit_text("ℹ️ Yangi e'lon qilinmagan chegirma topilmadi. Barcha mavjud chegirmalar allaqachon kanalga joylangan.")
    except Exception as e:
        logger.error(f"/check buyrug'ida xatolik: {e}")
        await status_msg.edit_text(f"❌ Xatolik yuz berdi: {e}")


async def cmd_deals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows top 5 current deals directly to the user in chat."""
    status_msg = await update.message.reply_text("⏳ Eng qaynoq chegirmalar yuklanmoqda...")
    try:
        api = SteamAPI()
        deals = await api.get_all_current_deals()
        if not deals:
            await status_msg.edit_text("Hozircha chegirmalar topilmadi.")
            return

        await status_msg.delete()
        # Collect top 3 safe deals
        safe_deals = []
        for deal in deals:
            is_safe, _ = await is_deal_safe(deal)
            if is_safe:
                safe_deals.append(deal)
            if len(safe_deals) >= 3:
                break

        for deal in safe_deals:
            caption = format_deal_caption(deal, config.CHANNEL_ID)
            keyboard = get_deal_keyboard(deal, config.CHANNEL_ID)
            try:
                banner_bytes = await generate_deal_banner(deal)
                photo_payload = io.BytesIO(banner_bytes) if banner_bytes else deal.image_url

                await update.message.reply_photo(
                    photo=photo_payload,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard
                )
                await asyncio.sleep(0.5)
            except Exception:
                await update.message.reply_html(caption, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"/deals buyrug'ida xatolik: {e}")
        await update.message.reply_text(f"❌ Xatolik yuz berdi: {e}")


async def cmd_digest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to manually test/generate a 5-deal digest collage post to the channel."""
    user_id = update.effective_user.id if update.effective_user else 0
    if config.ADMIN_ID and user_id != config.ADMIN_ID:
        await update.message.reply_text("⛔️ Kechirasiz, bu buyruq faqat bot admini uchun.")
        return

    status_msg = await update.message.reply_text("🔄 Eng sara 5 ta chegirmali o'yindan iborat yaxlit jamlanma (digest) tayyorlanmoqda...")
    try:
        api = SteamAPI()
        deals = await api.get_all_current_deals()
        valid_deals = []
        for d in deals:
            safe, _ = await is_deal_safe(d)
            if safe:
                valid_deals.append(d)
            if len(valid_deals) == 5:
                break

        if not valid_deals:
            await status_msg.edit_text("❌ Chegirmalar topilmadi.")
            return

        success = await post_digest_to_channel(context.bot, valid_deals, config.CHANNEL_ID)
        if success:
            await status_msg.edit_text("✅ 5 talik yaxlit jamlanma (digest) posti kanalga muvaffaqiyatli yuborildi!")
        else:
            await status_msg.edit_text("❌ Jamlanma postini yuborishda xatolik yuz berdi.")
    except Exception as e:
        logger.error(f"/digest buyrug'ida xatolik: {e}")
        await status_msg.edit_text(f"❌ Xatolik yuz berdi: {e}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays bot and database status."""
    posted_count = database.get_posted_count()
    recent = database.get_recent_posted(limit=5)
    
    recent_text = ""
    if recent:
        recent_text = "\n<b>Oxirgi e'lon qilingan o'yinlar:</b>\n"
        for r in recent:
            recent_text += f"• <b>{r['name']}</b> (-{r['discount_percent']}%) - ${r['final_price']}\n"

    text = (
        "🟢 <b>Bot Holati: Faol (Online)</b>\n\n"
        f"📢 <b>Kanal:</b> <code>{config.CHANNEL_ID}</code>\n"
        f"⏱ <b>Tekshiruv oralig'i:</b> {config.CHECK_INTERVAL_MINUTES} daqiqa\n"
        f"🏷 <b>Minimal chegirma:</b> {config.MIN_DISCOUNT_PERCENT}%\n"
        f"📦 <b>Bazadagi jami e'lonlar:</b> {posted_count} ta\n"
        f"{recent_text}"
    )
    await update.message.reply_html(text)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays help information."""
    text = (
        "ℹ️ <b>Yordam va Yo'riqnoma:</b>\n\n"
        "1. <b>Kanalga ulash:</b> Botni Telegram kanalingizga Administrator qilib qo'shing va unga 'Post Messages' (Xabar yozish) huquqini bering.\n"
        "2. <b>.env fayli:</b> <code>.env</code> faylida <code>BOT_TOKEN</code> va <code>CHANNEL_ID</code> to'g'ri kiritilganiga ishonch hosil qiling.\n"
        "3. <b>Avtomatlashtirish:</b> Bot ishga tushishi bilan avtomatik rejimda ishlaydi va har belgilangan vaqtda yangi chegirmalarni kanalga joylaydi.\n"
        "4. <b>Takrorlanmaslik:</b> Bir marta e'lon qilingan o'yin SQLite bazasiga saqlanadi va qayta e'lon qilinmaydi.\n"
        "5. <b>Yaxlit Jamlanma (Digest):</b> 5 ta post chiqqach, bot ularni birlashtirgan holda 5 talik umumiy kollaj va xulosa postini ham kanalga yuboradi."
    )
    await update.message.reply_html(text)


async def post_init(application: Application):
    """Initializes background tasks after bot application starts."""
    asyncio.create_task(scheduler_loop(application))


def main():
    """Main entrypoint for running the bot."""
    is_valid, msg = config.validate_config()
    if not is_valid:
        logger.error("=" * 60)
        logger.error("DIQQAT! SOZLAMALAR TO'G'RI O'RNATILMAGAN:")
        logger.error(msg)
        logger.error("Iltimos, d:\\game news\\.env faylini ochib, kerakli qiymatlarni kiriting.")
        logger.error("=" * 60)
        print(f"\n[XATOLIK] {msg}\n")
        return

    logger.info("Telegram Bot ishga tushirilmoqda...")
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    # Register command handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("check", cmd_check))
    application.add_handler(CommandHandler("digest", cmd_digest))
    application.add_handler(CommandHandler("deals", cmd_deals))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("help", cmd_help))

    logger.info("Bot tayyor. Polling boshlanmoqda...")
    
    # Render.com uchun web serverni fonida ishga tushirish
    try:
        from keep_alive import keep_alive
        keep_alive()
        logger.info("Keep-alive server ishga tushirildi.")
    except Exception as e:
        logger.error(f"Keep-alive server ishga tushmadi: {e}")

    application.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
