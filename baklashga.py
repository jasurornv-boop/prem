"""
baklashga.py — Birlashtirilgan bot: "Name Emojis" (newbot_fixed) + "Logo/Text Emojis"
(tgs_make_bot) bitta botda.

/start bosilganda 2 ta bo'lim ko'rsatiladi:
  🔤 Name Emojis      — so'zdan tayyor shablon ustiga yozilgan animatsiyali emoji
  🖼 Logo/Text Emojis — 103 ta tayyor shablondan birini tanlab, ustiga
                        o'zingizning matningizni joylash

FAYL TUZILISHI:
    baklashga.py        <- shu fayl (Telegram handlerlari)
    logo_engine.py         <- SVG/Lottie generatsiya "dvigateli" (tgs_make_bot'dan)
    logo_emoji_ids.py      <- Logo/Text shablonlari uchun preview custom_emoji_id lar
    template_engine.py     <- Name emoji render dvigateli (o'zgarishsiz)
    font_render.py         <- Name emoji shrift render (o'zgarishsiz)
    templates_config.py    <- Name emoji shablonlari sozlamalari (o'zgarishsiz)
    templates/*.json       <- Name emoji shablonlari
    templates_tgs/*.json   <- Logo/Text emoji shablonlari (yangilangan JSON'lar)
    fonts/*.ttf             <- Har ikkala bo'lim uchun shriftlar
"""

import asyncio
import html
import json
import logging
import os
import random
import re
import string
import zipfile

from aiogram import Bot, Dispatcher, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    Message,
    MessageEntity,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
)

import logo_engine
from logo_emoji_ids import LOGO_TEMPLATE_EMOJI_IDS
from template_engine import render_template, save_as_tgs
from templates_config import (EMOJI_IDS, TEMPLATE_ORDER, TEMPLATES,
                              CS2_EMOJI_SET, CS2_FILE_UNIQUE_ID)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8960203334:AAG_rn-yMwsF_3cMUwfcAuWqnCI75Mh_4KA")
MAX_LEN = 12
PLACEHOLDER = "\U0001F538"


def _random_nick(length: int = 12) -> str:
    """Telegram-style random lowercase nick, e.g. 'wiwheowuwhsj'."""
    return "".join(random.choices(string.ascii_lowercase, k=length))


ADMIN_ID = 5974947091  # <-- shu yerga o'zingizning Telegram user_id'ingizni yozing
LOG_CHAT_ID = "@prememojbot"
ALLOWED_FILE = os.path.join(os.path.dirname(__file__), "allowed_users.json")
USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")
EMOJI_PACK_FILE = os.path.join(os.path.dirname(__file__), "emoji_pack.json")
PRICE_FILES = {
    "name": os.path.join(os.path.dirname(__file__), "price_name.json"),
    "logo": os.path.join(os.path.dirname(__file__), "price_logo.json"),
    "code": os.path.join(os.path.dirname(__file__), "price_code.json"),
}
CREDITS_FILE = os.path.join(os.path.dirname(__file__), "credits.json")
BALANCE_FILE = os.path.join(os.path.dirname(__file__), "balance.json")
MONEY_BALANCE_FILE = os.path.join(os.path.dirname(__file__), "money_balance.json")
CARD_SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "card_settings.json")
MONEY_TOPUPS_FILE = os.path.join(os.path.dirname(__file__), "money_topups.json")
PROMOS_FILE = os.path.join(os.path.dirname(__file__), "promos.json")
STATS_FILE = os.path.join(os.path.dirname(__file__), "stats.json")
REFUND_REQUESTS_FILE = os.path.join(os.path.dirname(__file__), "refund_requests.json")
REFERRALS_FILE = os.path.join(os.path.dirname(__file__), "referrals.json")
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")
DEFAULT_PRICE_STARS = 1
DEFAULT_CODE_PRICE_STARS = 60
DEFAULT_MONEY_PRICE_UZS = 1000
# Placeholder shown to anyone running a copy of this code who hasn't set
# their own support contact yet (settings.json isn't included in the sold
# .zip, so buyers never see the seller's real contact here).
DEFAULT_SUPPORT_CONTACT = "@cyberabu"
LOGO_PAGE_SIZE = 10
TOTAL_LOGO_TEMPLATES = 103

logging.basicConfig(level=logging.INFO)
router = Router()


# ============================================================================
# Umumiy: pack saqlash, ruxsatlar, foydalanuvchilar, narx, kreditlar, referal,
# majburiy kanallar — ikkala bo'lim (Name / Logo) uchun ham baravar ishlatiladi.
# ============================================================================

def load_packs() -> dict:
    if not os.path.exists(EMOJI_PACK_FILE):
        return {}
    try:
        with open(EMOJI_PACK_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_packs(packs: dict):
    with open(EMOJI_PACK_FILE, "w", encoding="utf-8") as f:
        json.dump(packs, f)


def _safe_nick(nick: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]", "", nick)
    return cleaned or "pack"


async def add_stickers_to_pack(
    bot: Bot, sticker_paths: list[str], nick: str, pack_kind: str, progress_message: Message | None = None,
    owner_id: int | None = None, title: str | None = None,
):
    """Create or reuse a sticker set for this nick+kind and add all the
    given stickers to it. pack_kind is 'emoji' (premium custom emoji pack)
    or 'sticker' (regular stickers pack). Returns the pack name, or None
    if it failed.

    owner_id is the Telegram user who ordered the pack - the set is
    created under their account (so it shows up in their own sticker/emoji
    catalog in Telegram), not the bot admin's. Falls back to ADMIN_ID if
    no user is available (e.g. an internal/admin-triggered call).

    Telegram enforces its own rate limit on sticker-set edits: if we hit
    it, the API raises TelegramRetryAfter rather than adding the sticker.
    We catch it per-sticker, sleep for the time Telegram asks for, and
    retry that same sticker - so the pack always finishes once the wait
    is over, instead of stopping partway.

    Progress is shown by editing a single message in place (not by
    sending a new message per sticker), so the chat doesn't get flooded
    with one line per item."""
    from aiogram.types import InputSticker

    sticker_type = "custom_emoji" if pack_kind == "emoji" else "regular"
    owner_id = owner_id or ADMIN_ID
    packs = load_packs()
    storage_key = f"{pack_kind}:{nick}:{owner_id}"
    name = packs.get(storage_key)
    total = len(sticker_paths)
    last_text = None

    async def update(text: str):
        nonlocal last_text
        if progress_message is None or text == last_text:
            return
        last_text = text
        try:
            await progress_message.edit_text(text)
        except Exception:
            pass

    try:
        me = await bot.get_me()
        if not name:
            name = f"{_safe_nick(nick)}_{owner_id}_by_{me.username}"

        for i, sticker_path in enumerate(sticker_paths):
            item = InputSticker(sticker=FSInputFile(sticker_path), format="animated", emoji_list=["🙂"])
            while True:
                try:
                    if i == 0 and storage_key not in packs:
                        try:
                            await bot.create_new_sticker_set(
                                user_id=owner_id,
                                name=name,
                                title=title or nick,
                                stickers=[item],
                                sticker_type=sticker_type,
                            )
                        except TelegramBadRequest as e:
                            if "already occupied" not in str(e).lower():
                                raise
                            await bot.add_sticker_to_set(user_id=owner_id, name=name, sticker=item)
                        packs[storage_key] = name
                        save_packs(packs)
                    else:
                        await bot.add_sticker_to_set(user_id=owner_id, name=name, sticker=item)
                    break
                except TelegramRetryAfter as e:
                    await update(
                        f"⏳ Telegram cheklovi sababli {e.retry_after}s kutyapmiz "
                        f"({i}/{total} qo'shildi), keyin davom etamiz..."
                    )
                    await asyncio.sleep(e.retry_after + 1)
                    continue

            await update(f"⏳ Tayyorlanmoqda: {i + 1}/{total} qo'shildi")
        return name
    except Exception as e:
        logging.warning(f"pack update failed: {e}")
        return None


def load_allowed() -> set[int]:
    if not os.path.exists(ALLOWED_FILE):
        return set()
    try:
        with open(ALLOWED_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def save_allowed(ids: set[int]):
    with open(ALLOWED_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f)


def is_free_user(user_id: int) -> bool:
    return user_id == ADMIN_ID or user_id in load_allowed()


def load_users() -> set[int]:
    if not os.path.exists(USERS_FILE):
        return set()
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def save_users(ids: set[int]):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f)


def record_user(user_id: int):
    """Remember that this user has started the bot, so broadcasts can reach them."""
    users = load_users()
    if user_id not in users:
        users.add(user_id)
        save_users(users)


def load_price(kind: str = "name") -> int:
    path = PRICE_FILES.get(kind, PRICE_FILES["name"])
    default = DEFAULT_CODE_PRICE_STARS if kind == "code" else DEFAULT_PRICE_STARS
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if "price" in data:
            return int(data.get("price", default))
        return int(data.get("stars", default))
    except (json.JSONDecodeError, OSError, ValueError, TypeError):
        return default


def save_price(kind: str, stars: int):
    path = PRICE_FILES.get(kind, PRICE_FILES["name"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"stars": stars}, f)


# ---------- Bot manba kodini sotish uchun toza (sanitized) .zip paket ----------

_CODE_PACKAGE_DIR = os.path.join(os.path.dirname(__file__), "output")
_CODE_PACKAGE_PATH = os.path.join(_CODE_PACKAGE_DIR, "bot_source_code.zip")

# Ishga tushirish paytidagi bu botning o'ziga tegishli maxfiy/runtime
# ma'lumotlari — xaridorga sotilgan nusxada bular BO'LMASLIGI kerak.
_CODE_PACKAGE_EXCLUDE_DIRS = {"__pycache__", "output", "data"}
_CODE_PACKAGE_EXCLUDE_FILES = {
    "users.json", "credits.json", "balance.json", "allowed_users.json", "emoji_pack.json",
    "referrals.json", "settings.json", "stats.json", "refund_requests.json",
    "price_name.json", "price_logo.json", "price_code.json", "money_balance.json", "card_settings.json", "money_topups.json",
    "sonnet.lock", "bot.log",
}


def _sanitize_bot_py(content: str) -> str:
    """Sotuvchining haqiqiy BOT_TOKEN/ADMIN_ID/LOG_CHAT_ID qiymatlarini
    baklashga.py nusxasidan olib tashlab, xaridor o'zi to'ldiradigan bo'sh
    joy (placeholder) bilan almashtiradi."""
    content = re.sub(
        r'BOT_TOKEN = os\.environ\.get\("BOT_TOKEN", "[^"]*"\)',
        'BOT_TOKEN = os.environ.get("BOT_TOKEN", "BU_YERGA_BOT_TOKEN")',
        content,
    )
    content = re.sub(
        r"ADMIN_ID = \d+",
        "ADMIN_ID = 6745248562  # <-- shu yerga o'zingizning Telegram user_id'ingizni yozing  # <-- shu yerga o'zingizning Telegram user_id'ingizni yozing",
        content,
    )
    content = re.sub(
        r'LOG_CHAT_ID = (?:-?\d+|"[^"]*")',
        'LOG_CHAT_ID = "@emojiabu"',
        content,
    )
    return content


def build_code_package() -> str:
    """Botning o'z manba kodidan tozalangan (token/admin/kanal/yordam
    kontakti olib tashlangan) .zip paket yasaydi. Har bir xariddan keyin
    QAYTA yasaladi (fayllar o'zgargan bo'lishi mumkin), lekin bevosita
    umumiy _CODE_PACKAGE_PATH'ga yozmaydi: avval alohida vaqtinchalik
    faylga yozadi, so'ng atomik ravishda almashtiradi. Bu ikkita xarid
    bir vaqtda bo'lganda (yoki eski, hali ochilmagan invoys keyinroq
    to'langanda) bittasi hali yozilayotgan/yarim tugallangan zip fayl
    o'qib yuborilib, xaridorga buzilgan/bo'sh fayl ketishining oldini
    oladi."""
    os.makedirs(_CODE_PACKAGE_DIR, exist_ok=True)
    src_root = os.path.dirname(__file__)

    tmp_path = f"{_CODE_PACKAGE_PATH}.{os.getpid()}.{random.randint(0, 999999)}.tmp"
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(src_root):
            dirnames[:] = [d for d in dirnames if d not in _CODE_PACKAGE_EXCLUDE_DIRS]
            for fname in filenames:
                if fname in _CODE_PACKAGE_EXCLUDE_FILES:
                    continue
                full_path = os.path.join(dirpath, fname)
                arcname = os.path.join("baklashga", os.path.relpath(full_path, src_root))
                if fname == "baklashga.py":
                    with open(full_path, encoding="utf-8") as f:
                        content = f.read()
                    zf.writestr(arcname, _sanitize_bot_py(content))
                else:
                    zf.write(full_path, arcname)

    # Atomic on the same filesystem - readers either see the old complete
    # file or the new complete file, never a half-written one.
    os.replace(tmp_path, _CODE_PACKAGE_PATH)
    return _CODE_PACKAGE_PATH


def load_credits() -> dict:
    if not os.path.exists(CREDITS_FILE):
        return {}
    try:
        with open(CREDITS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_credits(credits: dict):
    with open(CREDITS_FILE, "w", encoding="utf-8") as f:
        json.dump(credits, f)


def get_credits(user_id: int) -> int:
    return load_credits().get(str(user_id), 0)


def add_credit(user_id: int, n: int = 1):
    credits = load_credits()
    key = str(user_id)
    credits[key] = credits.get(key, 0) + n
    save_credits(credits)


def use_credit(user_id: int) -> bool:
    credits = load_credits()
    key = str(user_id)
    if credits.get(key, 0) <= 0:
        return False
    credits[key] -= 1
    save_credits(credits)
    return True

def load_balance() -> dict:
    if not os.path.exists(BALANCE_FILE):
        return {}
    try:
        with open(BALANCE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_balance(balance: dict):
    with open(BALANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(balance, f)


def load_money_balance() -> dict:
    if not os.path.exists(MONEY_BALANCE_FILE):
        return {}
    try:
        with open(MONEY_BALANCE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_money_balance(balance: dict):
    with open(MONEY_BALANCE_FILE, "w", encoding="utf-8") as f:
        json.dump(balance, f)


def get_money_balance(user_id: int) -> int:
    return int(load_money_balance().get(str(user_id), 0))


def add_money_balance(user_id: int, amount: int):
    balance = load_money_balance()
    key = str(user_id)
    balance[key] = int(balance.get(key, 0)) + amount
    save_money_balance(balance)


def use_money_balance(user_id: int, amount: int) -> bool:
    if amount <= 0:
        return False
    balance = load_money_balance()
    key = str(user_id)
    current = int(balance.get(key, 0))
    if current < amount:
        return False
    balance[key] = current - amount
    save_money_balance(balance)
    return True


def load_card_settings() -> dict:
    if not os.path.exists(CARD_SETTINGS_FILE):
        return {"card": "", "name": ""}
    try:
        with open(CARD_SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return {"card": str(data.get("card", "")), "name": str(data.get("name", ""))}
    except (json.JSONDecodeError, OSError):
        return {"card": "", "name": ""}


def save_card_settings(card: str, name: str = ""):
    with open(CARD_SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump({"card": card, "name": name}, f, ensure_ascii=False)


def load_money_topups() -> dict:
    if not os.path.exists(MONEY_TOPUPS_FILE):
        return {}
    try:
        with open(MONEY_TOPUPS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_money_topups(data: dict):
    with open(MONEY_TOPUPS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_price_mode(kind: str = "name") -> str:
    path = PRICE_FILES.get(kind, PRICE_FILES["name"])
    default = "stars"
    if not os.path.exists(path):
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return str(json.load(f).get("mode", default))
    except (json.JSONDecodeError, OSError, TypeError):
        return default


def save_price_config(kind: str, amount: int, mode: str):
    path = PRICE_FILES.get(kind, PRICE_FILES["name"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"price": int(amount), "stars": int(amount) if mode == "stars" else DEFAULT_PRICE_STARS, "mode": mode}, f)


def get_balance(user_id: int) -> int:
    return int(load_balance().get(str(user_id), 0))


def add_balance(user_id: int, amount: int):
    if amount <= 0:
        return
    balance = load_balance()
    key = str(user_id)
    balance[key] = int(balance.get(key, 0)) + amount
    save_balance(balance)


def use_balance(user_id: int, amount: int) -> bool:
    if amount <= 0:
        return False
    balance = load_balance()
    key = str(user_id)
    current = int(balance.get(key, 0))
    if current < amount:
        return False
    balance[key] = current - amount
    save_balance(balance)
    return True

def load_promos() -> dict:
    if not os.path.exists(PROMOS_FILE):
        return {}
    try:
        with open(PROMOS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_promos(promos: dict):
    with open(PROMOS_FILE, "w", encoding="utf-8") as f:
        json.dump(promos, f)


def create_promo(code: str, credits: int, max_uses: int):
    promos = load_promos()
    promos[code.upper()] = {"credits": credits, "uses": 0, "max_uses": max_uses}
    save_promos(promos)


def redeem_promo(user_id: int, code: str):
    promos = load_promos()
    key = code.upper()
    item = promos.get(key)
    if not item or item.get("uses", 0) >= item.get("max_uses", 1):
        return False, 0
    item["uses"] = item.get("uses", 0) + 1
    promos[key] = item
    save_promos(promos)
    amount = int(item.get("credits", 0))
    add_credit(user_id, amount)
    return True, amount


def load_stats() -> dict:
    if not os.path.exists(STATS_FILE):
        return {}
    try:
        with open(STATS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_stats(stats: dict):
    with open(STATS_FILE, "w", encoding="utf-8") as f:
        json.dump(stats, f)


def record_pack_created(user_id: int, username: str | None):
    """Track how many packs (emoji/sticker sets) each user has generated,
    for the admin 'who made the most' leaderboard."""
    stats = load_stats()
    key = str(user_id)
    entry = stats.get(key, {"packs": 0, "stars": 0, "username": None})
    entry["packs"] = entry.get("packs", 0) + 1
    if username:
        entry["username"] = username
    stats[key] = entry
    save_stats(stats)


def record_stars_spent(user_id: int, username: str | None, amount: int):
    """Track how many Stars each user has paid the bot in total, for the
    admin 'who spent the most' leaderboard."""
    if amount <= 0:
        return
    stats = load_stats()
    key = str(user_id)
    entry = stats.get(key, {"packs": 0, "stars": 0, "username": None})
    entry["stars"] = entry.get("stars", 0) + amount
    if username:
        entry["username"] = username
    stats[key] = entry
    save_stats(stats)


def load_refund_requests() -> dict:
    if not os.path.exists(REFUND_REQUESTS_FILE):
        return {}
    try:
        with open(REFUND_REQUESTS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_refund_requests(requests: dict):
    with open(REFUND_REQUESTS_FILE, "w", encoding="utf-8") as f:
        json.dump(requests, f)


def create_refund_request(user_id: int, charge_id: str, amount: int) -> str:
    """Stash a pending stale-price refund so the admin can trigger it with
    one tap from the log channel, without the charge_id (which can be
    long) needing to round-trip through callback_data."""
    requests = load_refund_requests()
    ref_id = f"{user_id}_{len(requests)}_{random.randint(0, 999999)}"
    requests[ref_id] = {
        "user_id": user_id, "charge_id": charge_id, "amount": amount, "done": False,
    }
    save_refund_requests(requests)
    return ref_id


def load_referrals() -> dict:
    if not os.path.exists(REFERRALS_FILE):
        return {}
    try:
        with open(REFERRALS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_referrals(referrals: dict):
    with open(REFERRALS_FILE, "w", encoding="utf-8") as f:
        json.dump(referrals, f)


def record_referral(referred_id: int, referrer_id: int):
    """Remember who invited whom, so we can reward the referrer once the
    referred user finishes their first pack. Only the first referrer for
    a given user counts, and self-referrals are ignored."""
    if referred_id == referrer_id:
        return
    referrals = load_referrals()
    key = str(referred_id)
    if key in referrals:
        return
    referrals[key] = {"referrer": referrer_id, "rewarded": False}
    save_referrals(referrals)


async def reward_referral_if_pending(bot: Bot, referred_id: int):
    referrals = load_referrals()
    key = str(referred_id)
    entry = referrals.get(key)
    if not entry or entry.get("rewarded"):
        return
    referrer_id = entry["referrer"]
    entry["rewarded"] = True
    save_referrals(referrals)
    add_credit(referrer_id, 1)
    try:
        await bot.send_message(
            referrer_id,
            "🎉 Siz taklif qilgan do'stingiz birinchi emojisini yasadi!\n"
            "Sizga 1 ta bepul kredit berildi. Keyingi emojingizni yasaganda ishlatishingiz mumkin.",
        )
    except Exception as e:
        logging.warning(f"referral notify failed: {e}")


def load_settings() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(settings: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f)


def get_channels() -> list[str]:
    channels = load_settings().get("channels")
    if channels:
        return channels
    legacy = load_settings().get("channel")
    return [legacy] if legacy else []


def set_channels(channels: list[str]):
    settings = load_settings()
    settings["channels"] = channels
    settings.pop("channel", None)
    save_settings(settings)


def get_support_contact() -> str:
    """Support/help contact shown in user-facing messages. Stored in
    settings.json (per-deployment, not shipped in the sold code package)
    so each buyer of the bot code sets their own without ever seeing the
    seller's."""
    return load_settings().get("support_contact") or DEFAULT_SUPPORT_CONTACT


def set_support_contact(contact: str):
    settings = load_settings()
    settings["support_contact"] = contact
    save_settings(settings)


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    channels = get_channels()
    if not channels:
        return True
    for channel in channels:
        try:
            member = await bot.get_chat_member(channel, user_id)
            if member.status in ("left", "kicked"):
                return False
        except Exception as e:
            logging.warning(f"channel check failed for {channel}: {e}")
            continue
    return True


def subscribe_keyboard(channels: list[str]):
    rows = []
    for i, channel in enumerate(channels, start=1):
        uname = channel.lstrip("@")
        label = f"➕ Obuna bo'lish #{i}" if len(channels) > 1 else "📢 Kanalga o'tish"
        rows.append([InlineKeyboardButton(text=label, url=f"https://t.me/{uname}", style="primary")])
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="checksub", style="success")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _normalize_hex(text: str):
    m = re.match(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$", (text or "").strip())
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h.upper()


def _utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


# ============================================================================
# FSM holatlar
# ============================================================================

class Flow(StatesGroup):
    word = State()
    pack_title = State()
    pack_type = State()
    pack_nick = State()


class LogoFlow(StatesGroup):
    waiting_outer = State()
    waiting_outer_hex = State()
    waiting_inner = State()
    waiting_inner_hex = State()
    waiting_logo_color = State()
    waiting_logo_color_hex = State()
    waiting_svg = State()


class GiftFlow(StatesGroup):
    waiting_amount = State()


class BalanceFlow(StatesGroup):
    waiting_amount = State()


class AdminFlow(StatesGroup):
    add_id = State()
    remove_id = State()
    set_price = State()
    set_channel = State()
    set_support = State()
    broadcast = State()
    add_balance = State()
    sub_balance = State()
    add_promo = State()
    set_price_mode = State()
    set_card = State()
    topup_money_amount = State()
    topup_money_receipt = State()


# ============================================================================
# Bosh menyu (/start) — 2 bo'lim: Name Emojis / Logo Text Emojis
# ============================================================================

def main_section_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔤 Name Emojis", callback_data="section:name", style="primary"),
        InlineKeyboardButton(text="🖼 Logo/Text Emojis", callback_data="section:logo", style="primary"),
    ], [
        InlineKeyboardButton(text="💳 Hisobni to'ldirish", callback_data="section:balance", style="primary"),
        InlineKeyboardButton(text="🎁 Yulduz hadya qilish", callback_data="section:gift", style="primary"),
    ], [
        InlineKeyboardButton(text="ℹ️ Yordam", callback_data="help"),
    ]])


BUY_CODE_BUTTON_TEXT = "💻 Bot kodini olish"


def persistent_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BUY_CODE_BUTTON_TEXT)]],
        resize_keyboard=True,
    )


async def _send_section_menu(message: Message):
    await message.answer("Nima yasaymiz? 👇", reply_markup=main_section_keyboard())


@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    record_user(message.from_user.id)

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
            referrer_id = int(parts[1][len("ref_"):])
            record_referral(message.from_user.id, referrer_id)
        except ValueError:
            pass

    channels = get_channels()
    if channels and not await is_subscribed(message.bot, message.from_user.id):
        await message.answer(
            "Botdan foydalanish uchun avval kanal(lar)ga a'zo bo'ling, so'ng \"Tekshirish\" tugmasini bosing:",
            reply_markup=subscribe_keyboard(channels),
        )
        return

    await message.answer("👋 Xush kelibsiz!", reply_markup=persistent_keyboard())
    await _send_section_menu(message)


@router.callback_query(F.data == "checksub")
async def check_subscription(callback: CallbackQuery):
    channels = get_channels()
    if channels and not await is_subscribed(callback.bot, callback.from_user.id):
        await callback.answer("Hali barcha kanallarga a'zo bo'lmadingiz.", show_alert=True)
        return
    await callback.answer("✅ Tasdiqlandi!")
    try:
        await callback.message.delete()
    except Exception:
        pass
    await _send_section_menu(callback.message)


@router.callback_query(F.data == "backmain")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await _send_section_menu(callback.message)


@router.callback_query(F.data == "help")
async def help_handler(callback: CallbackQuery):
    me = await callback.bot.get_me()
    ref_link = f"https://t.me/{me.username}?start=ref_{callback.from_user.id}"
    credits = get_credits(callback.from_user.id)
    await callback.message.answer(
        f"🆘 Savol yoki muammo bo'lsa {get_support_contact()} ga yozing.\n\n"
        "🎁 Do'stingizni taklif qiling! U birinchi emoji/stikerini yasab bo'lgach, "
        "sizga 1 ta bepul kredit beriladi (keyingi emojingiz uchun to'lovsiz foydalanasiz).\n\n"
        f"Sizning taklif havolangiz:\n{ref_link}\n\n"
        f"💳 Hozir sizda {credits} ta bepul kredit bor."
    )
    await callback.answer()


# ============================================================================
# BO'LIM 0: HISOBNI TO'LDIRISH (Telegram Stars -> bot ichidagi balans)
# ============================================================================

BALANCE_MIN_AMOUNT = 1
BALANCE_MAX_AMOUNT = 100000


@router.callback_query(F.data == "section:balance")
async def section_balance(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        f"💳 Balansingiz: {get_balance(callback.from_user.id)} ⭐\n"
        f"💵 Pul balansi: {get_money_balance(callback.from_user.id):,} so'm\n\n"
        "Hisobni qaysi usulda to'ldirasiz?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ Stars orqali", callback_data="topup:stars", style="primary")],
            [InlineKeyboardButton(text="💵 Karta orqali (chek bilan)", callback_data="topup:money", style="success")],
            [InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="backmain")],
        ])
    )


@router.callback_query(F.data == "topup:stars")
async def topup_stars(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(BalanceFlow.waiting_amount)
    await callback.answer()
    await callback.message.answer("Nechta ⭐ qo'shmoqchisiz? Sonini yuboring (masalan: 100).")


@router.callback_query(F.data == "topup:money")
async def topup_money(callback: CallbackQuery, state: FSMContext):
    card = load_card_settings()
    if not card.get("card"):
        await callback.answer("Admin hali karta ma'lumotlarini sozlamagan.", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminFlow.topup_money_amount)
    await callback.answer()
    await callback.message.answer(
        f"💳 Karta: <code>{html.escape(card['card'])}</code>\n"
        f"👤 Qabul qiluvchi: {html.escape(card.get('name') or '-') }\n\n"
        "Qancha so'm to'ldirmoqchisiz? Sonini yuboring.", parse_mode="HTML"
    )


@router.message(AdminFlow.topup_money_amount, F.text)
async def money_topup_amount(message: Message, state: FSMContext):
    raw=(message.text or "").replace(" ", "").replace(",", "")
    if not raw.isdigit() or int(raw) < 1000:
        await message.answer("❌ Kamida 1 000 so'm bo'lishi kerak. Faqat son yuboring.")
        return
    amount=int(raw)
    await state.update_data(money_amount=amount)
    await state.set_state(AdminFlow.topup_money_receipt)
    await message.answer(f"💵 {amount:,} so'm. Endi to'lov chekini <b>rasm</b> qilib yuboring.", parse_mode="HTML")


@router.message(AdminFlow.topup_money_receipt, F.photo)
async def money_topup_receipt(message: Message, state: FSMContext):
    data=await state.get_data()
    amount=int(data.get("money_amount",0))
    if amount <= 0:
        await state.clear(); await message.answer("❌ So'rov eskirgan. Qaytadan boshlang."); return
    req_id=f"{message.from_user.id}_{message.message_id}"
    topups=load_money_topups()
    topups[req_id]={"user_id":message.from_user.id,"amount":amount,"status":"pending","photo_id":message.photo[-1].file_id}
    save_money_topups(topups)
    await state.clear()
    await message.answer("✅ Chek adminga yuborildi. Admin tasdiqlagach pul balansi hisobingizga tushadi.")
    who=f"@{message.from_user.username}" if message.from_user.username else f"id {message.from_user.id}"
    try:
        await message.bot.send_photo(
            ADMIN_ID, message.photo[-1].file_id,
            caption=f"💵 <b>Yangi karta to'lovi</b>\nFoydalanuvchi: {html.escape(who)}\nID: <code>{message.from_user.id}</code>\nMiqdor: <b>{amount:,} so'm</b>\nSo'rov: <code>{req_id}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"moneyok:{req_id}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"moneyno:{req_id}"),
            ]])
        )
    except Exception as e:
        logging.warning(f"money topup admin notify failed: {e}")


@router.message(AdminFlow.topup_money_receipt)
async def money_topup_wrong_receipt(message: Message):
    await message.answer("Iltimos, to'lov chekini rasm ko'rinishida yuboring.")


@router.message(BalanceFlow.waiting_amount)
async def balance_got_wrong_type(message: Message):
    await message.answer("Iltimos, balans uchun ⭐ miqdorini faqat son ko'rinishida yuboring.")


# ============================================================================
# BO'LIM 1: YULDUZ HADYA QILISH (Telegram Stars orqali oddiy hadya)
# ============================================================================

GIFT_MIN_AMOUNT = 1
GIFT_MAX_AMOUNT = 100000


@router.callback_query(F.data == "section:gift")
async def section_gift(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(GiftFlow.waiting_amount)
    await callback.answer()
    await callback.message.answer(
        "🎁 Nechta ⭐ Stars hadya qilmoqchisiz? Sonini yozing (masalan: 100):"
    )


@router.message(GiftFlow.waiting_amount, F.text)
async def gift_got_amount(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Iltimos, faqat son yuboring (masalan: 100).")
        return
    amount = int(raw)
    if not (GIFT_MIN_AMOUNT <= amount <= GIFT_MAX_AMOUNT):
        await message.answer(
            f"Son {GIFT_MIN_AMOUNT} dan {GIFT_MAX_AMOUNT} tagacha bo'lishi kerak. Qaytadan yozing:"
        )
        return

    await state.update_data(gift_amount=amount)
    await message.bot.send_invoice(
        chat_id=message.chat.id,
        title="⭐ Yulduz hadya",
        description=f"{amount} ⭐ Stars hadya qilish",
        payload=f"gift:{message.from_user.id}:{amount}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Stars hadya", amount=amount)],
    )


@router.message(GiftFlow.waiting_amount)
async def gift_got_wrong_type(message: Message):
    await message.answer("Iltimos, faqat son yuboring (masalan: 100).")


# ============================================================================
# BOT KODINI SOTIB OLISH (pastki, doimiy tugma orqali)
# ============================================================================

@router.message(F.text == BUY_CODE_BUTTON_TEXT)
async def buy_code_pressed(message: Message, state: FSMContext):
    price = load_price("code")
    await message.bot.send_invoice(
        chat_id=message.chat.id,
        title="💻 Bot manba kodi",
        description=f"Botning to'liq manba kodi (barcha fayllar bilan), {price} ⭐",
        payload=f"code:{message.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Bot kodi", amount=price)],
    )


# ============================================================================
# BO'LIM 1: NAME EMOJIS (so'zdan tayyor shablon ustiga yozadi)
# ============================================================================

def build_preview():
    text = "Name Emojis — 16 ta | CS 2 qo‘shilgan\n\n"
    entities = []
    for key in TEMPLATE_ORDER:
        label = TEMPLATES[key]["label"]
        emoji_id = EMOJI_IDS.get(key)
        start = _utf16_len(text)
        text += PLACEHOLDER
        if emoji_id:
            entities.append(MessageEntity(
                type="custom_emoji", offset=start, length=_utf16_len(PLACEHOLDER),
                custom_emoji_id=emoji_id,
            ))
        text += f" {label}\n"
    return text, entities


def choice_keyboard():
    buttons = [InlineKeyboardButton(text=TEMPLATES[k]["label"], callback_data=f"tpl:{k}") for k in TEMPLATE_ORDER]
    per_row = 4
    rows = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    rows.append([InlineKeyboardButton(text="Hammasi", callback_data="tpl:all", style="success")])
    rows.append([InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="backmain")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_name_menu(message: Message):
    # Resolve the preview from the supplied pack; never guess a custom emoji ID.
    if not EMOJI_IDS.get("cs2"):
        try:
            pack = await message.bot.get_sticker_set(CS2_EMOJI_SET, request_timeout=5)
            sticker = next((s for s in pack.stickers
                            if s.file_unique_id == CS2_FILE_UNIQUE_ID), None)
            if sticker is None and len(pack.stickers) == 1:
                sticker = pack.stickers[0]
            if sticker is not None and sticker.custom_emoji_id:
                EMOJI_IDS["cs2"] = sticker.custom_emoji_id
        except Exception:
            pass  # The template and the pack link remain usable without a preview.
    text, entities = build_preview()
    await message.answer(text, entities=entities)
    await message.answer("Qaysi birini yasaymiz?", reply_markup=choice_keyboard())


@router.callback_query(F.data == "section:name")
async def section_name(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(kind="name")
    await callback.answer()
    await _send_name_menu(callback.message)


@router.callback_query(F.data.startswith("tpl:"))
async def choose_template(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    if key != "all" and key not in TEMPLATE_ORDER:
        await callback.answer("Shablon topilmadi. Menyudan qayta tanlang.", show_alert=True)
        return
    await state.clear()
    await state.update_data(template=key, kind="name")
    await state.set_state(Flow.word)
    await callback.message.answer(f"So'zni yozing (maksimum {MAX_LEN} ta harf):")
    await callback.answer()


async def _render_sticker(message: Message, template_key: str, word: str) -> str:
    cfg = TEMPLATES[template_key]
    lottie = render_template(cfg, word)

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{message.from_user.id}_{template_key}.tgs")
    save_as_tgs(lottie, out_path)

    return out_path


def pack_type_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💎 Premium custom emoji pack", callback_data="packtype:emoji", style="primary"),
        InlineKeyboardButton(text="🖼 Stickers pack", callback_data="packtype:sticker", style="primary"),
    ]])


@router.message(Flow.word)
async def got_word(message: Message, state: FSMContext):
    word = (message.text or "").strip()
    if not word or len(word) > MAX_LEN:
        await message.answer(f"So'z 1 dan {MAX_LEN} tagacha harf bo'lishi kerak. Qaytadan yozing:")
        return

    data = await state.get_data()
    template_key = data.get("template")
    if template_key != "all" and template_key not in TEMPLATE_ORDER:
        await state.clear()
        await message.answer("Avval Name Emojis menyusidan shablon tanlang.")
        await _send_name_menu(message)
        return

    paths = []
    if template_key == "all":
        for key in TEMPLATE_ORDER:
            paths.append(await _render_sticker(message, key, word))
    else:
        paths.append(await _render_sticker(message, template_key, word))

    nick = _random_nick()
    await state.update_data(paths=paths, nick=nick)
    await state.set_state(Flow.pack_title)
    await message.answer("To'plam nomini yozing (bu Telegram'da ko'rinadigan sarlavha bo'ladi):")


PACK_TITLE_MAX_LEN = 64


@router.message(Flow.pack_title, F.text)
async def got_pack_title(message: Message, state: FSMContext):
    title = (message.text or "").strip()
    if not title or len(title) > PACK_TITLE_MAX_LEN:
        await message.answer(f"Nom 1 dan {PACK_TITLE_MAX_LEN} tagacha belgidan iborat bo'lishi kerak. Qaytadan yozing:")
        return
    await state.update_data(title=title)

    data = await state.get_data()
    kind = data.get("kind", "name")

    if kind == "logo":
        await _render_and_stage_logo_pack(message, state)
        await _offer_payment(message, state, message.from_user)
        return

    await state.set_state(Flow.pack_type)
    await message.answer("Qayerga qo'shamiz?", reply_markup=pack_type_keyboard())


@router.message(Flow.pack_nick, F.text)
async def got_pack_nick(message: Message, state: FSMContext):
    # No longer reachable in the normal flow (nick is auto-generated), kept
    # only as a safety net in case old FSM state from a previous version
    # is still stored for a user.
    nick = (message.text or "").strip()
    if not nick:
        await message.answer("Nik bo'sh bo'lmasin. Qaytadan yozing:")
        return
    await state.update_data(nick=nick)
    await state.set_state(Flow.pack_type)
    await message.answer("Qayerga qo'shamiz?", reply_markup=pack_type_keyboard())


async def _finalize_pack(
    bot: Bot, chat_id: int, paths: list[str], nick: str, pack_kind: str, user=None, title: str | None = None,
):
    total = len(paths)
    status = await bot.send_message(chat_id, f"⏳ Tayyorlanmoqda: 0/{total}")

    owner_id = user.id if user is not None else ADMIN_ID
    pack_name = await add_stickers_to_pack(
        bot, paths, nick, pack_kind, progress_message=status, owner_id=owner_id, title=title,
    )
    if pack_name:
        link = "addemoji" if pack_kind == "emoji" else "addstickers"
        url = f"https://t.me/{link}/{pack_name}"
        try:
            await status.edit_text(f"✅ Tayyor! Mana emojingiz, to'lov uchun rahmat 🙏\n{url}")
        except Exception:
            await bot.send_message(chat_id, f"✅ Tayyor! Mana emojingiz, to'lov uchun rahmat 🙏\n{url}")
        try:
            who = f"@{user.username}" if user and user.username else f"id {user.id}" if user else "noma'lum"
            channel_text = (
                f"🆕 <b>Yangi emoji:</b> {html.escape(who)}\n"
                f"<b>Nik:</b> {html.escape(nick)}\n"
                f"{url}\n\n"
                f"💳 <b>To'lovingiz uchun rahmat!</b> 🙏❤️\n"
                f"✨ Emojiingizdan zavq bilan foydalaning!"
            )
            await bot.send_message(LOG_CHAT_ID, channel_text, parse_mode="HTML", disable_web_page_preview=True)
            for p in paths:
                try:
                    await bot.send_sticker(LOG_CHAT_ID, FSInputFile(p))
                except Exception:
                    await bot.send_document(LOG_CHAT_ID, FSInputFile(p))
        except Exception as e:
            logging.warning(f"log channel post failed: {e}")
        if user is not None:
            await reward_referral_if_pending(bot, user.id)
            record_pack_created(user.id, user.username)
    else:
        try:
            await status.edit_text(f"❌ To'plamga qo'shib bo'lmadi. Xatolik bo'lsa {get_support_contact()} ga yozing.")
        except Exception:
            await bot.send_message(chat_id, f"❌ To'plamga qo'shib bo'lmadi. Xatolik bo'lsa {get_support_contact()} ga yozing.")
    await bot.send_message(chat_id, "Yangisini yasash uchun /start bosing.")


def payment_choice_keyboard(price: int, credits: int, balance: int, money_price: int | None = None, money_balance: int = 0):
    rows=[]
    if credits>0:
        rows.append([InlineKeyboardButton(text=f"🎁 Bepul kredit ishlatish ({credits} ta bor)", callback_data="pay:credit", style="success")])
    if money_price is not None:
        if money_balance >= money_price:
            rows.append([InlineKeyboardButton(text=f"💵 Pul balansidan to'lash ({money_balance:,} so'm)", callback_data="pay:money", style="primary")])
    else:
        if balance >= price:
            rows.append([InlineKeyboardButton(text=f"💳 Stars balansidan to'lash ({balance} ⭐)", callback_data="pay:balance", style="primary")])
        rows.append([InlineKeyboardButton(text=f"⭐ {price} Stars bilan to'lash", callback_data="pay:stars", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_invoice_msg(send_target: Message, user, nick: str, pack_kind: str, kind: str, count: int = 1):
    unit_price=load_price(kind); count=count or 1; total_price=unit_price*count
    kind_label="Custom emoji pack" if pack_kind=="emoji" else "Stickers pack"
    section_label="Logo/Text emoji" if kind=="logo" else "Name emoji"
    description=f"{section_label} — {kind_label}, {count} ta animatsiyali emoji/stiker ({unit_price} ⭐ x {count})"
    await send_target.bot.send_invoice(chat_id=send_target.chat.id,title=f"Emoji Pack ({nick})",description=description,payload=f"pack:{user.id}",provider_token="",currency="XTR",prices=[LabeledPrice(label="Emoji Pack",amount=total_price)])


async def _offer_payment(send_target: Message, state: FSMContext, user):
    data=await state.get_data(); paths=data.get("paths") or []; nick=data.get("nick","pack"); pack_kind=data.get("pack_kind","emoji"); title=data.get("title"); kind=data.get("kind","name")
    if is_free_user(user.id):
        await _finalize_pack(send_target.bot,send_target.chat.id,paths,nick,pack_kind,user=user,title=title); await state.clear(); return
    credits=get_credits(user.id); mode=load_price_mode(kind); unit_price=load_price(kind); count=len(paths) or 1; total_price=unit_price*count
    if mode=="uzs":
        money_balance=get_money_balance(user.id)
        if credits>0 or money_balance>=total_price:
            await send_target.answer(f"Qanday to'laymiz?\n\n💵 Pul balansi: {money_balance:,} so'm\n💰 Narx: {total_price:,} so'm", reply_markup=payment_choice_keyboard(0,credits,0,money_price=total_price,money_balance=money_balance))
            return
        await send_target.answer(f"💰 Bu emoji faqat pulga sotiladi.\nNarx: {total_price:,} so'm\n\nHisobni to'ldirish uchun 💳 Hisobni to'ldirish bo'limidan karta orqali chek yuboring.")
        return
    balance=get_balance(user.id)
    if credits>0 or balance>=total_price:
        await send_target.answer(f"Qanday to'laymiz?\n\n💳 Stars balans: {balance} ⭐",reply_markup=payment_choice_keyboard(total_price,credits,balance))
        return
    await _send_invoice_msg(send_target,user,nick,pack_kind,kind,count=count)


@router.callback_query(F.data == "pay:money")
async def pay_with_money(callback: CallbackQuery, state: FSMContext):
    data=await state.get_data(); paths=data.get("paths") or []; nick=data.get("nick","pack"); pack_kind=data.get("pack_kind","emoji"); title=data.get("title"); kind=data.get("kind","name")
    total_price=load_price(kind)*(len(paths) or 1)
    if load_price_mode(kind)!="uzs" or not use_money_balance(callback.from_user.id,total_price):
        await callback.answer("Pul balansi yetarli emas.",show_alert=True); return
    await _finalize_pack(callback.bot,callback.message.chat.id,paths,nick,pack_kind,user=callback.from_user,title=title)
    await state.clear(); await callback.answer("✅ Pul balansidan to'landi!")


@router.callback_query(F.data.startswith("packtype:"))
async def choose_pack_type(callback: CallbackQuery, state: FSMContext):
    pack_kind = callback.data.split(":", 1)[1]
    data = await state.get_data()
    if (pack_kind not in ("emoji", "sticker")
            or await state.get_state() != Flow.pack_type.state
            or not data.get("paths") or not data.get("title")):
        await callback.answer("Avval shablon, so‘z va to‘plam nomini kiriting.", show_alert=True)
        return
    await state.update_data(pack_kind=pack_kind)
    await _offer_payment(callback.message, state, callback.from_user)
    await callback.answer()


@router.callback_query(F.data == "pay:credit")
async def pay_with_credit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    paths = data.get("paths") or []
    nick = data.get("nick", "pack")
    pack_kind = data.get("pack_kind", "emoji")
    title = data.get("title")

    if not use_credit(callback.from_user.id):
        await callback.answer("Kredit topilmadi.", show_alert=True)
        return

    await _finalize_pack(
        callback.bot, callback.message.chat.id, paths, nick, pack_kind, user=callback.from_user, title=title,
    )
    await state.clear()
    await callback.answer()


@router.callback_query(F.data == "pay:balance")
async def pay_with_balance(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    paths = data.get("paths") or []
    nick = data.get("nick", "pack")
    pack_kind = data.get("pack_kind", "emoji")
    title = data.get("title")
    kind = data.get("kind", "name")
    total_price = load_price(kind) * (len(paths) or 1)

    if not use_balance(callback.from_user.id, total_price):
        await callback.answer("Balans yetarli emas. Hisobni to'ldiring.", show_alert=True)
        return

    await _finalize_pack(
        callback.bot, callback.message.chat.id, paths, nick, pack_kind,
        user=callback.from_user, title=title,
    )
    await state.clear()
    await callback.answer("✅ Balansdan to'landi!")


@router.callback_query(F.data == "pay:stars")
async def pay_with_stars(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    paths = data.get("paths") or []
    nick = data.get("nick", "pack")
    pack_kind = data.get("pack_kind", "emoji")
    kind = data.get("kind", "name")
    await _send_invoice_msg(callback.message, callback.from_user, nick, pack_kind, kind, count=len(paths))
    await callback.answer()


@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    payload = pre_checkout_query.invoice_payload or ""
    if payload.startswith("balance:"):
        parts = payload.split(":")
        try:
            owner_id = int(parts[1])
            requested = int(parts[2])
        except (IndexError, ValueError):
            await pre_checkout_query.answer(ok=False, error_message="Noto'g'ri balans invoysi.")
            return
        if owner_id != pre_checkout_query.from_user.id or requested <= 0:
            await pre_checkout_query.answer(ok=False, error_message="Bu invoys sizga tegishli emas yoki summa noto'g'ri.")
            return
        if pre_checkout_query.currency != "XTR" or pre_checkout_query.total_amount != requested:
            await pre_checkout_query.answer(ok=False, error_message="To'lov summasi mos kelmadi.")
            return
    await pre_checkout_query.answer(ok=True)


@router.message(F.successful_payment)
async def process_successful_payment(message: Message, state: FSMContext):
    payload = message.successful_payment.invoice_payload or ""
    paid_amount = message.successful_payment.total_amount or 0
    record_stars_spent(message.from_user.id, message.from_user.username, paid_amount)

    if payload.startswith("balance:"):
        parts = payload.split(":")
        requested = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        if requested <= 0 or paid_amount != requested:
            await message.answer("❌ Balans to'lovi tasdiqlanmadi: summa mos kelmadi. Yordam uchun admin bilan bog'laning.")
            await state.clear()
            return
        add_balance(message.from_user.id, paid_amount)
        await message.answer(
            f"✅ To'lov tasdiqlandi!\n💳 Balansingizga +{paid_amount} ⭐ qo'shildi.\n"
            f"💰 Joriy balans: {get_balance(message.from_user.id)} ⭐"
        )
        try:
            who = f"@{message.from_user.username}" if message.from_user.username else f"id {message.from_user.id}"
            await message.bot.send_message(
                LOG_CHAT_ID,
                f"💳 Balans to'ldirildi: {who}\nMiqdor: {paid_amount} ⭐\n"
                f"Telegramdagi bot Stars balansi orqali qabul qilindi."
            )
        except Exception as e:
            logging.warning(f"log channel post failed: {e}")
        await state.clear()
        return

    if payload.startswith("gift:"):
        parts = payload.split(":")
        amount = parts[2] if len(parts) > 2 else "?"
        await message.answer(f"✅ Rahmat! {amount} ⭐ Stars hadyangiz uchun tashakkur 🙏")
        try:
            who = f"@{message.from_user.username}" if message.from_user.username else f"id {message.from_user.id}"
            await message.bot.send_message(LOG_CHAT_ID, f"🎁 Yangi hadya: {who}\nMiqdor: {amount} ⭐")
        except Exception as e:
            logging.warning(f"log channel post failed: {e}")
        await state.clear()
        return

    if payload.startswith("code:"):
        current_price = load_price("code")
        if paid_amount != current_price:
            # Bu eski invoys - narx o'zgargandan keyin ham hali to'lash
            # mumkin bo'lib qolgandi (Telegram eski xabarlarni ham
            # to'lashga ruxsat beradi). Eski narxda kod berib
            # yubormaymiz. Pulni AVTOMATIK qaytarmaymiz - faqat sizga
            # (adminga) log kanalida tugma chiqadi, xohlasangiz o'zingiz
            # bir bosishda qaytarasiz.
            charge_id = message.successful_payment.telegram_payment_charge_id
            ref_id = create_refund_request(message.from_user.id, charge_id, paid_amount)

            await message.answer(
                f"❌ Bu eski taklif edi, narx shu orada {current_price} ⭐ ga o'zgargan — "
                f"shuning uchun fayl berilmadi.\n\n"
                f"Iltimos {get_support_contact()} ga yozing, yoki pastdagi "
                f"\"{BUY_CODE_BUTTON_TEXT}\" tugmasini hozirgi narxda qaytadan bosing."
            )
            try:
                who = f"@{message.from_user.username}" if message.from_user.username else f"id {message.from_user.id}"
                await message.bot.send_message(
                    LOG_CHAT_ID,
                    f"⚠️ {who} kodni sotib olishga urindi, lekin eski narxda to'lagani "
                    f"uchun fayl berilmadi.\n"
                    f"To'langan: {paid_amount} ⭐, hozirgi narx: {current_price} ⭐",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(
                            text=f"💸 {paid_amount} ⭐ ni qaytarish",
                            callback_data=f"refundcode:{ref_id}",
                        ),
                    ]]),
                )
            except Exception as e:
                logging.warning(f"log channel post failed: {e}")
            await state.clear()
            return

        await message.answer("✅ To'lov qabul qilindi! Bot kodi tayyorlanmoqda...")
        sent = False
        last_error = None
        for attempt in range(2):  # 1 marta qayta urinish - eskirgan/buzilgan zip bo'lsa
            try:
                zip_path = build_code_package()
                if not zipfile.is_zipfile(zip_path):
                    raise RuntimeError("zip fayl buzilgan chiqdi, qayta yasalmoqda")
                await message.bot.send_document(
                    message.chat.id, FSInputFile(zip_path, filename="bot_source_code.zip"),
                    caption="💻 Mana botning to'liq manba kodi. O'z BOT_TOKEN, ADMIN_ID va LOG_CHAT_ID qiymatlaringizni baklashga.py ichida to'ldiring.",
                )
                sent = True
                break
            except Exception as e:
                last_error = e
                logging.exception(f"code package send failed (attempt {attempt + 1})")
        if not sent:
            await message.answer(
                f"❌ Kodni yuborishda xatolik: {last_error}\n\nIltimos {get_support_contact()} ga yozing."
            )
            try:
                await message.bot.send_message(
                    LOG_CHAT_ID,
                    f"⚠️ Bot kodi to'lovi qabul qilindi, lekin fayl yuborilmadi!\n"
                    f"Xaridor: id {message.from_user.id}\nXatolik: {last_error}",
                )
            except Exception as e:
                logging.warning(f"log channel post failed: {e}")
        try:
            who = f"@{message.from_user.username}" if message.from_user.username else f"id {message.from_user.id}"
            await message.bot.send_message(LOG_CHAT_ID, f"💻 Bot kodi sotildi: {who}")
        except Exception as e:
            logging.warning(f"log channel post failed: {e}")
        await state.clear()
        return

    data = await state.get_data()
    paths = data.get("paths") or []
    nick = data.get("nick", "pack")
    pack_kind = data.get("pack_kind", "emoji")
    title = data.get("title")
    kind = data.get("kind", "name")

    count = len(paths) or 1
    if load_price_mode(kind) != "stars":
        await message.answer("❌ Bu emoji hozir pul orqali sotiladi, Stars to'lovi qabul qilinmaydi. Pul balansini karta orqali to'ldiring.")
        await state.clear()
        return
    expected_price = load_price(kind) * count
    if paid_amount != expected_price:
        # Xuddi bot kodida bo'lgani kabi: bu eski invoys, narx o'shandan
        # beri o'zgargan. Emoji/stikerni bermaymiz, avtomatik ham
        # qaytarmaymiz - faqat log kanalida sizga (adminga) bittagina
        # tugma bilan qaytarish imkonini beramiz.
        charge_id = message.successful_payment.telegram_payment_charge_id
        ref_id = create_refund_request(message.from_user.id, charge_id, paid_amount)

        section_label = "Logo/Text emoji" if kind == "logo" else "Name emoji"
        await message.answer(
            f"❌ Bu eski taklif edi, narx shu orada o'zgargan — shuning uchun "
            f"emoji/stiker tayyorlanmadi.\n\n"
            f"Iltimos {get_support_contact()} ga yozing, yoki /start bosib hozirgi "
            f"narxda qaytadan buyurtma bering."
        )
        try:
            who = f"@{message.from_user.username}" if message.from_user.username else f"id {message.from_user.id}"
            await message.bot.send_message(
                LOG_CHAT_ID,
                f"⚠️ {who} {section_label} sotib olishga urindi, lekin eski narxda "
                f"to'lagani uchun berilmadi.\n"
                f"To'langan: {paid_amount} ⭐, hozirgi narx: {expected_price} ⭐ "
                f"({count} ta x {load_price(kind)} ⭐)",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text=f"💸 {paid_amount} ⭐ ni qaytarish",
                        callback_data=f"refundcode:{ref_id}",
                    ),
                ]]),
            )
        except Exception as e:
            logging.warning(f"log channel post failed: {e}")
        await state.clear()
        return

    await _finalize_pack(
        message.bot, message.chat.id, paths, nick, pack_kind, user=message.from_user, title=title,
    )
    await state.clear()


# ============================================================================
# BO'LIM 2: LOGO/TEXT EMOJIS (103 ta shablondan birini tanlab, matn/SVG qo'yish)
# ============================================================================

PRESET_COLORS = [
    ("🔴 Qizil", "#E53935"),
    ("🟠 To'q sariq", "#FB8C00"),
    ("🟢 Yashil", "#43A047"),
    ("🔵 Ko'k", "#1E88E5"),
    ("⚪ Oq", "#FFFFFF"),
    ("⚫ Qora", "#000000"),
]


def color_keyboard(prefix: str, allow_skip: bool = False):
    rows = []
    row = []
    for label, hexcode in PRESET_COLORS:
        row.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{hexcode}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="🎨 O'zim kiritaman (HEX kod)", callback_data=f"{prefix}:custom")])
    if allow_skip:
        rows.append([InlineKeyboardButton(
            text="⏭ Skip — logo asl rangida qoladi", callback_data=f"{prefix}:skip",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_logo_preview(page: int):
    start = page * LOGO_PAGE_SIZE + 1
    end = min(start + LOGO_PAGE_SIZE - 1, TOTAL_LOGO_TEMPLATES)
    text = f"🖼 Qaysi shablonni yasaymiz? ({start}-{end} / {TOTAL_LOGO_TEMPLATES})\n\n"
    entities = []
    for n in range(start, end + 1):
        emoji_id = LOGO_TEMPLATE_EMOJI_IDS.get(n)
        offset = _utf16_len(text)
        text += PLACEHOLDER
        if emoji_id:
            entities.append(MessageEntity(
                type="custom_emoji", offset=offset, length=_utf16_len(PLACEHOLDER),
                custom_emoji_id=emoji_id,
            ))
        text += f" {n}-shablon\n"
    return text, entities


def logo_page_keyboard(page: int):
    start = page * LOGO_PAGE_SIZE + 1
    end = min(start + LOGO_PAGE_SIZE - 1, TOTAL_LOGO_TEMPLATES)
    rows = []
    row = []
    for n in range(start, end + 1):
        emoji_id = LOGO_TEMPLATE_EMOJI_IDS.get(n)
        kwargs = {"text": str(n), "callback_data": f"logotpl:{n}"}
        if emoji_id:
            kwargs["icon_custom_emoji_id"] = emoji_id
        row.append(InlineKeyboardButton(**kwargs))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"logopage:{page - 1}"))
    if end < TOTAL_LOGO_TEMPLATES:
        nav.append(InlineKeyboardButton(text="Keyingi qatorga o'tish ➡️", callback_data=f"logopage:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Bosh menyu", callback_data="backmain")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_logo_template_page(message: Message, page: int, edit_callback: CallbackQuery | None = None):
    text, entities = build_logo_preview(page)
    kb = logo_page_keyboard(page)
    if edit_callback is not None:
        try:
            await edit_callback.message.edit_text(text, entities=entities, reply_markup=kb)
            return
        except Exception:
            pass
    await message.answer(text, entities=entities, reply_markup=kb)


@router.callback_query(F.data == "section:logo")
async def section_logo(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.update_data(kind="logo")
    await callback.answer()
    await _send_logo_template_page(callback.message, 0)


@router.callback_query(F.data.startswith("logopage:"))
async def logo_page_nav(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[1])
    await callback.answer()
    await _send_logo_template_page(callback.message, page, edit_callback=callback)


@router.callback_query(F.data.startswith("logotpl:"))
async def logo_template_chosen(callback: CallbackQuery, state: FSMContext):
    n = int(callback.data.split(":")[1])
    await state.update_data(template_number=n, kind="logo")
    await state.set_state(LogoFlow.waiting_outer)
    await callback.answer(f"{n}-shablon tanlandi")
    await callback.message.answer(
        f"✅ {n}-shablon tanlandi.\n\n1️⃣ TASHQI (chegara) rangini tanlang:",
        reply_markup=color_keyboard("outer"),
    )


@router.callback_query(LogoFlow.waiting_outer, F.data.startswith("outer:"))
async def logo_outer_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await state.set_state(LogoFlow.waiting_outer_hex)
        await callback.answer()
        await callback.message.answer("Tashqi (chegara) rangini #RRGGBB ko'rinishida yuboring. Masalan: #FF0000")
        return
    await state.update_data(outer_hex=value)
    await state.set_state(LogoFlow.waiting_inner)
    await callback.answer(f"Tashqi rang: {value}")
    await callback.message.answer("2️⃣ ICHKI fon rangini tanlang:", reply_markup=color_keyboard("inner"))


@router.message(LogoFlow.waiting_outer_hex, F.text)
async def logo_outer_hex(message: Message, state: FSMContext):
    hexcode = _normalize_hex(message.text or "")
    if not hexcode:
        await message.answer("Noto'g'ri format. Masalan: #FF0000 ko'rinishida yuboring.")
        return
    await state.update_data(outer_hex=hexcode)
    await state.set_state(LogoFlow.waiting_inner)
    await message.answer(f"✅ Tashqi rang: {hexcode}\n\n2️⃣ ICHKI fon rangini tanlang:", reply_markup=color_keyboard("inner"))


@router.callback_query(LogoFlow.waiting_inner, F.data.startswith("inner:"))
async def logo_inner_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await state.set_state(LogoFlow.waiting_inner_hex)
        await callback.answer()
        await callback.message.answer("Ichki fon rangini #RRGGBB ko'rinishida yuboring. Masalan: #000000")
        return
    await state.update_data(inner_hex=value)
    await state.set_state(LogoFlow.waiting_logo_color)
    await callback.answer(f"Ichki rang: {value}")
    await callback.message.answer(
        "3️⃣ LOGO rangini tanlang (logoda 2-3 ta o'z rangi bo'lsa — Skip bosing, asl rangida qoladi):",
        reply_markup=color_keyboard("logocolor", allow_skip=True),
    )


@router.message(LogoFlow.waiting_inner_hex, F.text)
async def logo_inner_hex(message: Message, state: FSMContext):
    hexcode = _normalize_hex(message.text or "")
    if not hexcode:
        await message.answer("Noto'g'ri format. Masalan: #000000 ko'rinishida yuboring.")
        return
    await state.update_data(inner_hex=hexcode)
    await state.set_state(LogoFlow.waiting_logo_color)
    await message.answer(
        f"✅ Ichki rang: {hexcode}\n\n3️⃣ LOGO rangini tanlang (yoki Skip — logo asl rangida qoladi):",
        reply_markup=color_keyboard("logocolor", allow_skip=True),
    )


@router.callback_query(LogoFlow.waiting_logo_color, F.data.startswith("logocolor:"))
async def logo_color_chosen(callback: CallbackQuery, state: FSMContext):
    value = callback.data.split(":", 1)[1]
    if value == "custom":
        await state.set_state(LogoFlow.waiting_logo_color_hex)
        await callback.answer()
        await callback.message.answer("Logo rangini #RRGGBB ko'rinishida yuboring. Masalan: #FFFFFF")
        return
    if value == "skip":
        await state.update_data(logo_hex=None)
        await callback.answer("Logo o'z rangida qoladi")
    else:
        await state.update_data(logo_hex=value)
        await callback.answer(f"Logo rangi: {value}")
    _, font_path = logo_engine.FONT_OPTIONS["classic"]
    await state.update_data(font_path=font_path)
    await state.set_state(LogoFlow.waiting_svg)
    await callback.message.answer("✍️ Endi matn yozing (masalan: Salom):")


@router.message(LogoFlow.waiting_logo_color_hex, F.text)
async def logo_color_hex(message: Message, state: FSMContext):
    hexcode = _normalize_hex(message.text or "")
    if not hexcode:
        await message.answer("Noto'g'ri format. Masalan: #FFFFFF ko'rinishida yuboring.")
        return
    await state.update_data(logo_hex=hexcode)
    _, font_path = logo_engine.FONT_OPTIONS["classic"]
    await state.update_data(font_path=font_path)
    await state.set_state(LogoFlow.waiting_svg)
    await message.answer(
        f"✅ Logo rangi: {hexcode}\n\n"
        "✍️ Endi matn yozing (masalan: Salom):"
    )


async def _logo_continue_with_svg(message: Message, state: FSMContext, svg_text: str):
    await state.update_data(svg_text=svg_text)
    data = await state.get_data()

    template_filename = f"{data['template_number']:03d}.json"
    try:
        logo_engine.build_tgs_sticker(
            template_filename, svg_text,
            outer_hex=data["outer_hex"], inner_hex=data["inner_hex"], logo_hex=data.get("logo_hex"),
            size_percent=logo_engine.DEFAULT_SIZE_PERCENT,
        )
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}\n\nBoshqa matn yuborib ko'ring.")
        return

    await state.set_state(Flow.pack_title)
    await message.answer("To'plam nomini yozing (bu Telegram'da ko'rinadigan sarlavha bo'ladi):")


@router.message(LogoFlow.waiting_svg, F.text)
async def logo_got_svg_text(message: Message, state: FSMContext):
    if (message.text or "").startswith("/"):
        return
    data = await state.get_data()
    font_path = data.get("font_path")
    try:
        svg_text = logo_engine.text_to_svg(message.text, font_path=font_path)
    except Exception as e:
        await message.answer(f"❌ Matndan logo yasab bo'lmadi: {e}")
        return
    await _logo_continue_with_svg(message, state, svg_text)


@router.message(LogoFlow.waiting_svg)
async def logo_got_svg_wrong_type(message: Message):
    await message.answer("Iltimos, shunchaki matn yozing (masalan: Salom).")


async def _render_and_stage_logo_pack(message: Message, state: FSMContext):
    """Renders the final .tgs for the chosen logo/text template + colors,
    saves it to disk, and stages paths/nick/pack_kind in FSM data exactly
    like the Name-emoji flow does, so the shared payment code can take
    over from here."""
    data = await state.get_data()
    template_number = data["template_number"]
    template_filename = f"{template_number:03d}.json"

    tgs_bytes, _ = logo_engine.build_tgs_sticker(
        template_filename, data["svg_text"],
        outer_hex=data["outer_hex"], inner_hex=data["inner_hex"], logo_hex=data.get("logo_hex"),
        size_percent=logo_engine.DEFAULT_SIZE_PERCENT,
    )

    out_dir = os.path.join(os.path.dirname(__file__), "output")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{message.from_user.id}_logo_{template_number}.tgs")
    with open(out_path, "wb") as f:
        f.write(tgs_bytes)

    nick = _random_nick()
    await state.update_data(paths=[out_path], nick=nick, pack_kind="emoji")


# ============================================================================
# ADMIN PANEL — ikkala bo'lim uchun ham (Name / Logo/Text alohida narxlar)
# ============================================================================

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎁 Gift yuborish · Bot balansi", callback_data="ag:page:0"),
    ], [
        InlineKeyboardButton(text="➕ Balans qo'shish", callback_data="adm:add_balance", style="primary"),
        InlineKeyboardButton(text="➖ Balans ayirish", callback_data="adm:sub_balance", style="danger"),
    ], [
        InlineKeyboardButton(text="🎟 Promokod qo'shish", callback_data="adm:add_promo", style="primary"),
    ], [
        InlineKeyboardButton(text="🆓 Bepul foydalanuvchilar", callback_data="adm:free", style="primary"),
    ], [
        InlineKeyboardButton(text="💰 Name emoji narxi", callback_data="adm:price_name", style="primary"),
        InlineKeyboardButton(text="💰 Logo/Text emoji narxi", callback_data="adm:price_logo", style="primary"),
    ], [
        InlineKeyboardButton(text="💳 Karta sozlamasi", callback_data="adm:card", style="primary"),
        InlineKeyboardButton(text="⭐ Bot Stars balansi", callback_data="adm:stars_balance", style="primary"),
    ], [
        InlineKeyboardButton(text="💰 Bot kodi narxi", callback_data="adm:price_code", style="primary"),
    ], [
        InlineKeyboardButton(text="🚫 Ruxsatni olib tashlash", callback_data="adm:revoke", style="danger"),
    ], [
        InlineKeyboardButton(text="📢 Majburiy kanallar", callback_data="adm:channel", style="primary"),
        InlineKeyboardButton(text="🆘 Yordam bo'limini sozlash", callback_data="adm:support", style="primary"),
    ], [
        InlineKeyboardButton(text="📊 Statistika", callback_data="adm:stats", style="primary"),
    ], [
        InlineKeyboardButton(text="⭐ Bot Stars balansi", callback_data="adm:stars_balance", style="primary"),
    ], [
        InlineKeyboardButton(text="📣 Xabar tarqatish", callback_data="adm:broadcast", style="primary"),
    ]])


@router.callback_query(F.data.startswith("admpmode:"))
async def admin_price_mode(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(); return
    _, kind, mode = callback.data.split(":", 2)
    if kind not in ("name", "logo") or mode not in ("stars", "uzs"):
        await callback.answer("Noto'g'ri tanlov.", show_alert=True); return
    await state.update_data(price_kind=kind, price_mode=mode)
    await state.set_state(AdminFlow.set_price_mode)
    unit="Stars" if mode=="stars" else "so'm"
    await callback.message.answer(f"Yangi narxni {unit}da yuboring. Masalan: {'10' if mode=='stars' else '5000'}")
    await callback.answer()


@router.callback_query(F.data.startswith("refundcode:"))
async def refund_code_payment(callback: CallbackQuery, state: FSMContext):
    """The refund button posted to the log channel. Anyone in that channel
    can see it, but only ADMIN_ID is allowed to actually trigger the
    refund - everyone else just gets a 'no permission' popup and nothing
    happens."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Sizda bu tugmadan foydalanish huquqi yo'q.", show_alert=True)
        return

    ref_id = callback.data.split(":", 1)[1]
    requests = load_refund_requests()
    entry = requests.get(ref_id)
    if not entry:
        await callback.answer("Bu so'rov topilmadi (eskirgan bo'lishi mumkin).", show_alert=True)
        return
    if entry.get("done"):
        await callback.answer("Bu allaqachon qaytarilgan.", show_alert=True)
        return

    try:
        await callback.bot.refund_star_payment(
            user_id=entry["user_id"], telegram_payment_charge_id=entry["charge_id"],
        )
    except Exception as e:
        logging.exception("manual refund failed")
        await callback.answer(f"Qaytarishda xatolik: {e}", show_alert=True)
        return

    entry["done"] = True
    requests[ref_id] = entry
    save_refund_requests(requests)

    await callback.answer("✅ Qaytarildi.", show_alert=True)
    try:
        await callback.message.edit_text(callback.message.text + "\n\n✅ Qaytarildi.")
    except Exception:
        pass


@router.callback_query(F.data.startswith("moneyok:"))
async def approve_money_topup(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: await callback.answer("Ruxsat yo'q",show_alert=True); return
    rid=callback.data.split(":",1)[1]; data=load_money_topups(); entry=data.get(rid)
    if not entry or entry.get("status")!="pending": await callback.answer("So'rov topilmadi yoki allaqachon ko'rib chiqilgan.",show_alert=True); return
    entry["status"]="approved"; data[rid]=entry; save_money_topups(data); add_money_balance(int(entry["user_id"]),int(entry["amount"]))
    try: await callback.bot.send_message(int(entry["user_id"]),f"✅ Karta to'lovi tasdiqlandi!\n💵 +{int(entry['amount']):,} so'm\n💰 Balans: {get_money_balance(int(entry['user_id'])):,} so'm")
    except Exception: pass
    await callback.answer("✅ Tasdiqlandi",show_alert=True)
    try: await callback.message.edit_caption((callback.message.caption or "")+"\n\n✅ TASDIQLANDI")
    except Exception: pass


@router.callback_query(F.data.startswith("moneyno:"))
async def reject_money_topup(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: await callback.answer("Ruxsat yo'q",show_alert=True); return
    rid=callback.data.split(":",1)[1]; data=load_money_topups(); entry=data.get(rid)
    if not entry or entry.get("status")!="pending": await callback.answer("So'rov topilmadi yoki allaqachon ko'rib chiqilgan.",show_alert=True); return
    entry["status"]="rejected"; data[rid]=entry; save_money_topups(data)
    try: await callback.bot.send_message(int(entry["user_id"]),"❌ Karta to'lovi rad etildi. Chek yoki summa bo'yicha admin bilan bog'laning.")
    except Exception: pass
    await callback.answer("❌ Rad etildi",show_alert=True)
    try: await callback.message.edit_caption((callback.message.caption or "")+"\n\n❌ RAD ETILDI")
    except Exception: pass


@router.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID or message.chat.type != "private":
        return
    await state.clear()
    await message.answer("Admin panel:", reply_markup=admin_keyboard())


@router.callback_query(F.data.startswith("adm:"))
async def admin_menu(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer()
        return

    action = callback.data.split(":")[1]
    if action == "add_balance":
        await state.set_state(AdminFlow.add_balance)
        await callback.message.answer("➕ Pullik balans qo'shish\nFormat: USER_ID MIQDOR\nMasalan: 123456789 50")
    elif action == "sub_balance":
        await state.set_state(AdminFlow.sub_balance)
        await callback.message.answer("➖ Pullik balans ayirish\nFormat: USER_ID MIQDOR\nMasalan: 123456789 20")
    elif action == "add_promo":
        await state.set_state(AdminFlow.add_promo)
        await callback.message.answer("🎟 Promokod yaratish\nFormat: KOD BALANS FOYDALANISH_LIMI\nMasalan: ABU10 10 5")
    elif action == "free":
        listing = "\n".join(str(i) for i in sorted(load_allowed())) or "(bo'sh)"
        await state.set_state(AdminFlow.add_id)
        await callback.message.answer(f"Bepul foydalanuvchilar:\n{listing}\n\nQo'shish uchun user_id yuboring:")
    elif action in ("price_name", "price_logo", "price_code"):
        kind = action.split("_", 1)[1]
        label = {"name": "Name emoji", "logo": "Logo/Text emoji", "code": "Bot kodi"}[kind]
        await state.update_data(price_kind=kind)
        if kind == "code":
            await state.set_state(AdminFlow.set_price)
            await callback.message.answer(f"Hozirgi {label} narxi: {load_price(kind)} ⭐\n\nYangi narxni Starsda yuboring:")
        else:
            mode = load_price_mode(kind)
            unit = "⭐" if mode == "stars" else "so'm"
            await callback.message.answer(
                f"{label}: hozir {load_price(kind):,} {unit}.\n\nNarx turini tanlang:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="⭐ Stars", callback_data=f"admpmode:{kind}:stars", style="primary"),
                    InlineKeyboardButton(text="💵 So'm", callback_data=f"admpmode:{kind}:uzs", style="success"),
                ]])
            )
    elif action == "card":
        card=load_card_settings()
        await state.set_state(AdminFlow.set_card)
        await callback.message.answer(f'Hozirgi karta: {card.get("card") or "(yo\'q)"}\nQabul qiluvchi: {card.get("name") or "(yo\'q)"}\n\nFormat: KARTA | ISM\nMasalan: 8600 1234 5678 9012 | ASAD')
    elif action == "stars_balance":
        try:
            bal = await callback.bot.get_my_star_balance()
            amount = getattr(bal, "amount", bal)
            await callback.message.answer(f"⭐ Bot Stars balansi: {amount} ⭐")
        except Exception as e:
            await callback.message.answer(f"❌ Stars balansini olishda xatolik: {e}")
    elif action == "revoke":
        listing = "\n".join(str(i) for i in sorted(load_allowed())) or "(bo'sh)"
        await state.set_state(AdminFlow.remove_id)
        await callback.message.answer(f"Bepul foydalanuvchilar:\n{listing}\n\nOlib tashlash uchun user_id yuboring:")
    elif action == "channel":
        current = "\n".join(get_channels()) or "(o'rnatilmagan)"
        await state.set_state(AdminFlow.set_channel)
        await callback.message.answer(
            f"Hozirgi majburiy kanallar:\n{current}\n\n"
            "Yangi kanallar ro'yxatini yuboring (har birini bo'sh joy yoki yangi qatorga yozing, "
            "masalan @kanal1 @kanal2). Bu ro'yxat eskisini to'liq almashtiradi.\n"
            "Barcha kanallarni o'chirish uchun 'off' deb yozing:"
        )
    elif action == "support":
        current = get_support_contact()
        await state.set_state(AdminFlow.set_support)
        await callback.message.answer(
            f"Hozirgi yordam kontakti: {current}\n\n"
            "Yangi kontaktni yuboring (masalan @sizning_username). Bu faqat shu botning "
            "o'zida ishlatiladi — kod sotilganda xaridorga yubormaysiz, u o'zining "
            "kontaktini shu yerdan alohida sozlaydi."
        )
    elif action == "stars_balance":
        try:
            star_balance = await callback.bot.get_my_star_balance()
            amount = getattr(star_balance, "amount", star_balance)
            nano = getattr(star_balance, "nanostar_amount", 0) or 0
            if nano:
                await callback.message.answer(
                    f"⭐ Bot Stars balansi: {amount:,} ⭐\n"
                    f"NanoStars qismi: {nano}".replace(",", " ")
                )
            else:
                await callback.message.answer(f"⭐ Bot Stars balansi: {amount:,} ⭐".replace(",", " "))
        except Exception as e:
            logging.exception("get bot stars balance failed")
            await callback.message.answer(
                "❌ Bot Stars balansini olishda xatolik yuz berdi.\n"
                f"{e}"
            )
    elif action == "stats":
        stats = load_stats()
        if not stats:
            await callback.message.answer("Hozircha statistika yo'q.")
        else:
            entries = list(stats.items())

            def _label(uid: str, entry: dict) -> str:
                return f"@{entry['username']}" if entry.get("username") else f"id {uid}"

            by_packs = sorted(entries, key=lambda kv: kv[1].get("packs", 0), reverse=True)[:10]
            by_stars = sorted(entries, key=lambda kv: kv[1].get("stars", 0), reverse=True)[:10]

            packs_text = "\n".join(
                f"{i}. {_label(uid, e)} — {e.get('packs', 0)} ta"
                for i, (uid, e) in enumerate(by_packs, start=1)
            ) or "(bo'sh)"
            stars_text = "\n".join(
                f"{i}. {_label(uid, e)} — {e.get('stars', 0)} ⭐"
                for i, (uid, e) in enumerate(by_stars, start=1)
            ) or "(bo'sh)"

            await callback.message.answer(
                f"📊 Statistika\n\n"
                f"🏆 Eng ko'p emoji/stiker yasaganlar:\n{packs_text}\n\n"
                f"⭐ Eng ko'p Stars to'laganlar:\n{stars_text}"
            )
    elif action == "broadcast":
        total = len(load_users())
        await state.set_state(AdminFlow.broadcast)
        await callback.message.answer(
            f"Reklama xabaringizni yozing (matn, custom emoji, rasm, video — hammasi bo'ladi).\n"
            f"Hozircha botga start bosgan {total} ta foydalanuvchi bor."
        )
    await callback.answer()


@router.message(AdminFlow.add_balance)
async def admin_add_balance(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Format: USER_ID MIQDOR")
        return
    try:
        uid, amount = int(parts[0]), int(parts[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Ikkalasi ham musbat son bo'lishi kerak.")
        return
    add_balance(uid, amount)
    await message.answer(f"✅ {uid} balansiga +{amount} qo'shildi.\n💳 Yangi balans: {get_balance(uid)} ⭐")
    await state.clear()


@router.message(AdminFlow.sub_balance)
async def admin_sub_balance(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Format: USER_ID MIQDOR")
        return
    try:
        uid, amount = int(parts[0]), int(parts[1])
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Ikkalasi ham musbat son bo'lishi kerak.")
        return
    balance = load_balance()
    key = str(uid)
    balance[key] = max(0, int(balance.get(key, 0)) - amount)
    save_balance(balance)
    await message.answer(f"✅ {uid} balansidan -{amount} ayirildi.\n💳 Yangi balans: {get_balance(uid)} ⭐")
    await state.clear()


@router.message(AdminFlow.add_promo)
async def admin_add_promo(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Format: KOD BALANS FOYDALANISH_LIMI")
        return
    code = parts[0].upper()
    try:
        amount, max_uses = int(parts[1]), int(parts[2])
        if not code or amount <= 0 or max_uses <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri ma'lumot.")
        return
    create_promo(code, amount, max_uses)
    await message.answer(f"✅ Promokod yaratildi: {code}\n💰 Balans: +{amount}\n🔢 Limit: {max_uses}")
    await state.clear()


@router.message(Command("promo"))
async def redeem_promo_command(message: Message):
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Format: /promo KOD")
        return
    ok, amount = redeem_promo(message.from_user.id, parts[1])
    if not ok:
        await message.answer("❌ Promokod noto'g'ri yoki limiti tugagan.")
        return
    await message.answer(f"✅ Promokod qabul qilindi!\n💰 +{amount} balans\n⭐ Balansingiz: {get_credits(message.from_user.id)}")


@router.message(AdminFlow.add_id)
async def admin_add_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        uid = int((message.text or "").strip())
    except ValueError:
        await message.answer("user_id butun son bo'lishi kerak. Qaytadan yuboring:")
        return
    allowed = load_allowed()
    allowed.add(uid)
    save_allowed(allowed)
    await message.answer(f"✅ {uid} ga bepul foydalanish ruxsati berildi.")
    await state.clear()


@router.message(AdminFlow.remove_id)
async def admin_remove_id(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        uid = int((message.text or "").strip())
    except ValueError:
        await message.answer("user_id butun son bo'lishi kerak. Qaytadan yuboring:")
        return
    allowed = load_allowed()
    allowed.discard(uid)
    save_allowed(allowed)
    await message.answer(f"❌ {uid} dan ruxsat olib tashlandi.")
    await state.clear()


@router.message(AdminFlow.set_price_mode)
async def admin_set_price_mode(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    raw=(message.text or "").strip().replace(" ","").replace(",","")
    try:
        amount=int(raw)
        if amount<1: raise ValueError
    except ValueError:
        await message.answer("❌ Musbat butun son yuboring."); return
    data=await state.get_data(); kind=data.get("price_kind"); mode=data.get("price_mode")
    if mode=="stars" and kind not in ("name","logo"):
        await message.answer("❌ Noto'g'ri sozlama."); await state.clear(); return
    save_price_config(kind, amount, mode)
    label={"name":"Name emoji","logo":"Logo/Text emoji"}[kind]
    unit="⭐" if mode=="stars" else "so'm"
    await message.answer(f"✅ {label} narxi {amount:,} {unit} qilib o'rnatildi. Bu rejimda emoji uchun {'Stars' if mode=='stars' else 'pul'} ishlatiladi.")
    await state.clear()


@router.message(AdminFlow.set_price)
async def admin_set_price(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    try:
        stars = int((message.text or "").strip())
        if stars < 1: raise ValueError
    except ValueError:
        await message.answer("Narx musbat butun son bo'lishi kerak. Qaytadan yuboring:"); return
    data=await state.get_data(); kind=data.get("price_kind", "name")
    label={"name":"Name emoji","logo":"Logo/Text emoji","code":"Bot kodi"}.get(kind,"Name emoji")
    save_price(kind, stars)
    await message.answer(f"✅ {label} narxi {stars} ⭐ qilib o'zgartirildi.")
    await state.clear()


@router.message(AdminFlow.set_card)
async def admin_set_card(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    parts=[x.strip() for x in (message.text or "").split("|",1)]
    if len(parts)!=2 or not parts[0] or not parts[1]:
        await message.answer("Format: KARTA | ISM\nMasalan: 8600 1234 5678 9012 | ASAD"); return
    save_card_settings(parts[0], parts[1])
    await message.answer("✅ Karta ma'lumotlari saqlandi.")
    await state.clear()




@router.message(AdminFlow.set_channel)
async def admin_set_channel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    text = (message.text or "").strip()
    if text.lower() == "off":
        set_channels([])
        await message.answer("✅ Barcha majburiy kanallar o'chirildi.")
    else:
        raw = [t for t in text.replace(",", "\n").split() if t]
        channels = []
        for t in raw:
            uname = t.replace("https://t.me/", "").replace("http://t.me/", "").strip()
            if not uname.startswith("@"):
                uname = "@" + uname
            channels.append(uname)
        set_channels(channels)
        listing = "\n".join(channels) or "(bo'sh)"
        await message.answer(f"✅ Majburiy kanallar o'rnatildi:\n{listing}")
    await state.clear()


@router.message(AdminFlow.set_support)
async def admin_set_support(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    contact = (message.text or "").strip()
    if not contact:
        await message.answer("Kontakt bo'sh bo'lmasin. Qaytadan yuboring:")
        return
    set_support_contact(contact)
    await message.answer(f"✅ Yordam kontakti {contact} qilib o'zgartirildi.")
    await state.clear()


@router.message(AdminFlow.broadcast)
async def admin_broadcast(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()

    user_ids = load_users()
    total = len(user_ids)
    status = await message.answer(f"⏳ Yuborilmoqda: 0/{total}")

    sent = 0
    failed = 0
    for i, uid in enumerate(user_ids, start=1):
        while True:
            try:
                await message.bot.copy_message(
                    chat_id=uid, from_chat_id=message.chat.id, message_id=message.message_id,
                )
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except TelegramBadRequest:
                failed += 1
            except Exception:
                failed += 1
            break

        if i % 20 == 0 or i == total:
            try:
                await status.edit_text(f"⏳ Yuborilmoqda: {i}/{total}")
            except Exception:
                pass
        await asyncio.sleep(0.05)

    await status.edit_text(
        f"✅ Tarqatish tugadi.\n\n"
        f"📤 Yuborildi: {sent} ta odamga\n"
        f"❌ Yuborilmadi: {failed} ta odamga"
    )


@router.errors()
async def errors_handler(event) -> bool:
    """Telegram raises TelegramForbiddenError whenever we try to message a
    user who has blocked the bot or deleted the chat - this is routine and
    not a bug, so we just note it quietly instead of dumping a traceback
    for every occurrence. Anything else is still logged with its
    traceback so real bugs stay visible."""
    from aiogram.exceptions import TelegramForbiddenError

    exception = event.exception
    if isinstance(exception, TelegramForbiddenError):
        logging.info(f"user blocked the bot / chat unavailable: {exception}")
        return True
    logging.exception("Unhandled error while processing update", exc_info=exception)
    return True


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "BU_YERGA_BOT_TOKEN":
        raise RuntimeError("BOT_TOKEN topilmadi. baklashga.py ichida BOT_TOKEN ni kiriting yoki environment variable o'rnating.")
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    from admin_gifts import build_gift_router
    dp.include_router(build_gift_router(ADMIN_ID, load_users))
    dp.include_router(router)
    await dp.start_polling(bot)


_LOCK_PATH = os.path.join(os.path.dirname(__file__), "sonnet.lock")
_lock_file_handle = None  # keep a reference so the OS lock isn't released early


def _acquire_single_instance_lock():
    """Windows/Linux uchun oddiy single-instance lock."""
    global _lock_file_handle
    try:
        import msvcrt
        _lock_file_handle = open(_LOCK_PATH, "w")
        try:
            msvcrt.locking(_lock_file_handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("❌ Bot allaqachon ishlab turibdi. Avval eski oynani yoping.", flush=True)
            raise SystemExit(1)
    except ImportError:
        try:
            import fcntl
            _lock_file_handle = open(_LOCK_PATH, "w")
            fcntl.flock(_lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("❌ Bot allaqachon ishlab turibdi. Avval eski jarayonni to'xtating.", flush=True)
            raise SystemExit(1)
    _lock_file_handle.write(str(os.getpid()))
    _lock_file_handle.flush()


if __name__ == "__main__":
    _acquire_single_instance_lock()
    asyncio.run(main())
