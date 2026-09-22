"""Private admin gift panel. No automatic retries of paid requests."""
import asyncio
import secrets
import re
import logging
import time
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError, TelegramBadRequest, TelegramRetryAfter

PRICES = (15, 25, 50)

def error_text(exc):
    detail = re.sub(r"\d{6,}:[A-Za-z0-9_-]{20,}", "[TOKEN]", str(getattr(exc, 'message', type(exc).__name__)))[:350]
    if isinstance(exc, TelegramRetryAfter):
        return f"Telegram limiti: {exc.retry_after} soniya kutib /gift ni oching."
    return f"{type(exc).__name__}: {detail}"


def available(gift):
    return (gift.star_count in PRICES
            and getattr(gift, 'remaining_count', None) != 0
            and getattr(gift, 'personal_remaining_count', None) != 0)

def keyboard(rows):
    return Markup(inline_keyboard=[[Button(text=t, callback_data=d) for t, d in row] for row in rows])

def build_gift_router(admin_id, load_users):
    router = Router(name='admin_gifts')
    pending = {}
    lock = asyncio.Lock()

    def authorized(user, chat):
        return user and user.id == admin_id and chat and chat.type == 'private' and chat.id == admin_id

    async def users_page(message, bot, page=0):
        users = sorted(int(u) for u in load_users() if int(u) > 0)
        page = max(0, min(page, max(0, (len(users)-1)//10)))
        balance = await bot.get_my_star_balance()
        rows = [[(f'👤 {uid}', f'ag:user:{uid}')] for uid in users[page*10:page*10+10]]
        nav = []
        if page: nav.append(('⬅️', f'ag:page:{page-1}'))
        if (page+1)*10 < len(users): nav.append(('➡️', f'ag:page:{page+1}'))
        if nav: rows.append(nav)
        rows.append([('🔄 Yangilash', f'ag:page:{page}')])
        await message.answer(
            f'🎁 Gift yuborish\nBotning Stars balansi: {balance.amount} ⭐️\n'
            f'/start bosganlar: {len(users)}\nOluvchini ID bo‘yicha tanlang.\n'
            'Bevosita tanlash: /gift FOYDALANUVCHI_ID', reply_markup=keyboard(rows))

    async def prices(message, bot, uid):
        if uid not in {int(u) for u in load_users()}:
            await message.answer('Bu foydalanuvchi ro‘yxatda yo‘q. Avval botda /start bossin.')
            return
        chat = await bot.get_chat(uid)
        if chat.type != 'private':
            await message.answer('Faqat foydalanuvchiga yuborish mumkin.')
            return
        label = chat.full_name or str(uid)
        if chat.username: label += f' (@{chat.username})'
        await message.answer(f'Oluvchi: {label}\nID: {uid}\nGift narxini tanlang:',
            reply_markup=keyboard([[(f'{p} ⭐️', f'ag:price:{uid}:{p}') for p in PRICES], [('⬅️ Ro‘yxat', 'ag:page:0')]]))

    @router.message(Command('gift'))
    async def command(message, state):
        if not authorized(message.from_user, message.chat): return
        await state.clear()
        try:
            parts = (message.text or '').split()
            if len(parts) == 2 and parts[1].isdigit():
                await prices(message, message.bot, int(parts[1]))
            else:
                await users_page(message, message.bot)
        except TelegramAPIError as exc:
            await message.answer('Gift menyusini ochishda xato.\n' + error_text(exc))

    @router.callback_query(F.data.startswith('ag:'))
    async def callback(c, state):
        if not authorized(c.from_user, getattr(c.message, 'chat', None)):
            await c.answer('Faqat admin uchun.', show_alert=True)
            return
        await c.answer()
        # One lock covers confirmation consumption and the paid API request.
        async with lock:
            try:
                stage = 'Tugmani ochish'
                parts = c.data.split(':')
                action = parts[1]
                if action == 'page':
                    await state.clear()
                    await users_page(c.message, c.bot, int(parts[2]))
                elif action == 'user':
                    await prices(c.message, c.bot, int(parts[2]))
                elif action == 'price':
                    uid, price = int(parts[2]), int(parts[3])
                    if uid not in {int(u) for u in load_users()} or price not in PRICES: return
                    stage = 'Giftlar ro‘yxatini olish'
                    gifts = [g for g in (await c.bot.get_available_gifts()).gifts if available(g) and g.star_count == price]
                    if not gifts:
                        await c.message.answer(f'Hozir {price} ⭐️ narxda mavjud gift yo‘q.')
                    else:
                        # Send one compact list, avoiding a burst of sticker messages.
                        stage = 'Gift tanlash tugmalarini ko‘rsatish'
                        for offset in range(0, len(gifts), 40):
                            batch = gifts[offset:offset+40]
                            rows = [[(f"{getattr(g.sticker, 'emoji', None) or '🎁'} {offset+i}-gift · {price} ⭐️", f'ag:pick:{uid}:{g.id}')] for i, g in enumerate(batch, 1)]
                            await c.message.answer(f'{price} ⭐️ giftlar — oluvchi ID: {uid}\nGiftni tanlang:', reply_markup=keyboard(rows))
                elif action == 'pick':
                    uid, gid = int(parts[2]), parts[3]
                    if uid not in {int(u) for u in load_users()}: return
                    gift = next((g for g in (await c.bot.get_available_gifts()).gifts if g.id == gid and available(g)), None)
                    if not gift:
                        await c.message.answer('Gift tugagan. /gift orqali qayta tanlang.')
                        return
                    chat = await c.bot.get_chat(uid)
                    if chat.type != 'private': return
                    # A gift sticker may be rejected by sendSticker. Preview failure
                    # must not prevent selection/confirmation of the actual gift.
                    stage = 'Gift ko‘rinishini ko‘rsatish'
                    try:
                        await c.message.answer_sticker(gift.sticker.file_id)
                    except TelegramBadRequest as exc:
                        logging.warning('Gift preview unavailable: %s', error_text(exc))
                    stage = 'Yuborishni tasdiqlash'
                    pending.clear()  # Only the latest confirmation is valid.
                    nonce = secrets.token_hex(8)
                    pending[nonce] = (uid, gid, gift.star_count, time.monotonic()+300)
                    await c.message.answer(
                        f'🎁 Tasdiqlaysizmi?\nOluvchi: {chat.full_name or uid}\nID: {uid}\n'
                        f'Bot balansidan {gift.star_count} ⭐️ sarflanadi.',
                        reply_markup=keyboard([[('✅ Yuborish', f'ag:send:{nonce}')], [('❌ Bekor qilish', f'ag:cancel:{nonce}')]]))
                elif action == 'cancel':
                    pending.pop(parts[2], None)
                    await c.message.edit_text('Gift yuborish bekor qilindi.')
                elif action == 'send':
                    order = pending.pop(parts[2], None)
                    if not order or order[3] < time.monotonic():
                        await c.message.answer('Tasdiq eskirgan yoki ishlatilgan. /gift orqali qayta oching.')
                        return
                    uid, gid, price, _ = order
                    if uid not in {int(u) for u in load_users()}: return
                    gift = next((g for g in (await c.bot.get_available_gifts()).gifts if g.id == gid and available(g)), None)
                    if not gift or gift.star_count != price:
                        await c.message.answer('Gift narxi yoki mavjudligi o‘zgardi. /gift orqali qayta tanlang.')
                        return
                    balance = await c.bot.get_my_star_balance()
                    if balance.amount + (getattr(balance, 'nanostar_amount', 0) or 0)/1e9 < price:
                        await c.message.answer(f'Balans yetarli emas: {balance.amount} ⭐️. Kerak: {price} ⭐️.')
                        return
                    await c.message.edit_text(f'⏳ {uid} ga gift yuborilmoqda…')
                    # Do not retry send_gift: a timeout may occur after Telegram charged Stars.
                    try:
                        result = await c.bot.send_gift(user_id=uid, gift_id=gid, pay_for_upgrade=False)
                    except (TelegramNetworkError, asyncio.TimeoutError):
                        await c.message.answer('⚠️ Yuborish natijasi noma’lum. Qayta yuborishdan oldin oluvchining giftlarini va bot balansini tekshiring.')
                        return
                    except TelegramAPIError as exc:
                        detail = str(getattr(exc, 'message', 'Telegram rad etdi.'))[:250]
                        await c.message.answer(f'Gift yuborilmadi: {detail}')
                        return
                    if result:
                        await c.message.answer(f'✅ Gift yuborildi!\nOluvchi ID: {uid}\nSarflandi: {price} ⭐️')
                    else:
                        await c.message.answer('Gift yuborish tasdiqlanmadi. Balans va oluvchini tekshiring.')
            except (ValueError, IndexError):
                await c.message.answer('Tugma eskirgan. /gift orqali qayta oching.')
            except TelegramAPIError as exc:
                await c.message.answer(f'{stage}:\n{error_text(exc)}\n/gift orqali qayta oching.')
    return router
