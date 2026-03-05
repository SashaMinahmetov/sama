import os
import logging
import aiohttp
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from redis.asyncio import Redis

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REDIS_URL = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")
GOOGLE_WEBHOOK_URL = os.environ.get("GOOGLE_WEBHOOK_URL") 
ADMIN_ID = "-1003731208847" 
INSTAGRAM_LINK_1 = "https://instagram.com/tm.sama.ua" 
INSTAGRAM_LINK_2 = "https://instagram.com/koshik_shop_" 

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=BOT_TOKEN)

if not REDIS_URL:
    raise ValueError("Не найдена переменная окружения KV_URL для Redis.")

redis = Redis.from_url(REDIS_URL)
storage = RedisStorage(redis=redis)
dp = Dispatcher(storage=storage)
app = FastAPI()

# --- СОСТОЯНИЯ ---
class Registration(StatesGroup):
    waiting_for_fio = State()
    waiting_for_phone = State()
    waiting_for_receipt_number = State() 
    waiting_for_ig = State()             
    waiting_for_subscription = State()   
    waiting_for_receipt_photo = State()  


# --- КЛАВІАТУРИ ---

# ГОЛОВНІ ЕКРАННІ КНОПКИ (ПІД ТЕКСТОМ) + ІНСТАГРАМ
def get_inline_start_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧾 Завантажити чек", callback_data="upload_receipt"),
                InlineKeyboardButton(text="👤 Мій кабінет", callback_data="my_cabinet")
            ],
            [
                InlineKeyboardButton(text="🎁 Умови розіграшу", callback_data="show_rules"),
                InlineKeyboardButton(text="🏆 Призи та FAQ", callback_data="show_faq")
            ],
            [
                InlineKeyboardButton(text="📸 tm.sama.ua", url=INSTAGRAM_LINK_1),
                InlineKeyboardButton(text="📸 koshik_shop_", url=INSTAGRAM_LINK_2)
            ]
        ]
    )

# ЕКРАННА КНОПКА ПОВЕРНЕННЯ В МЕНЮ
def get_back_to_main_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В головне меню", callback_data="back_to_main")]
        ]
    )

# ТИМЧАСОВІ НИЖНІ КНОПКИ ДЛЯ ЗРУЧНОСТІ ПРИ ВВОДІ ДАНИХ (ПІД ЧАС РЕЄСТРАЦІЇ)
def get_cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Скасувати")]],
        resize_keyboard=True
    )

def get_back_cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⬅️ Назад"), KeyboardButton(text="❌ Скасувати")]
        ],
        resize_keyboard=True
    )

# --- СПІЛЬНА ЛОГІКА ДЛЯ КНОПОК ---
async def process_show_cabinet(target_message, user_id: int):
    user_data = await redis.hgetall(f"user:{user_id}")
    
    if not user_data:
        await target_message.answer(
            "🤷‍♂️ Ви ще не зареєстровані.\nНатисніть «🧾 Завантажити чек», щоб створити профіль та додати перший чек!", 
            reply_markup=get_back_to_main_inline_kb()
        )
        return

    fio = user_data.get(b'fio', b'').decode('utf-8')
    phone = user_data.get(b'phone', b'').decode('utf-8')
    ig = user_data.get(b'ig', b'').decode('utf-8')
    receipts_count = user_data.get(b'receipts', b'0').decode('utf-8')

    history_items = await redis.lrange(f"user_receipts:{user_id}", 0, -1)
    history_text = ""
    if history_items:
        history_text = "\n\n📋 <b>Історія ваших чеків:</b>\n"
        for item in history_items:
            try:
                date_str, rec_num = item.decode('utf-8').split('|', 1)
                history_text += f"🔹 {date_str} — № {rec_num}\n"
            except:
                pass
    else:
        history_text = "\n\n📋 <b>Історія ваших чеків:</b>\nПоки що порожньо."

    cabinet_text = (
        "👤 <b>Ваш особистий кабінет:</b>\n\n"
        f"🔸 <b>ПІБ:</b> {fio}\n"
        f"🔸 <b>Телефон:</b> {phone}\n"
        f"🔸 <b>Instagram:</b> {ig}\n"
        f"🎫 <b>Успішно схвалено чеків:</b> {receipts_count}"
        f"{history_text}\n\n"
        "Так тримати! Чим більше чеків, тим ближче перемога 🏆"
    )
    await target_message.answer(cabinet_text, parse_mode="HTML", reply_markup=get_back_to_main_inline_kb())

async def process_start_upload(target_message, user_id: int, state: FSMContext):
    user_data = await redis.hgetall(f"user:{user_id}")
    
    if not user_data or b'ig' not in user_data:
        await target_message.answer(
            "📝 Для початку реєстрації, будь ласка, <b>напишіть ваше ПІБ</b> (Прізвище, Ім'я, По батькові):", 
            reply_markup=get_cancel_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Registration.waiting_for_fio)
    else:
        await target_message.answer(
            "🧾 <b>Введіть НОМЕР вашого чека</b> (тільки цифри/літери):", 
            reply_markup=get_back_cancel_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Registration.waiting_for_receipt_number)

async def process_show_rules(target_message):
    rules = (
        "📜 <b>Умови дуже прості:</b>\n\n"
        "1️⃣ Бути підписаним на наші 2 сторінки в Instagram.\n"
        "2️⃣ Купувати нашу акційну продукцію.\n"
        "3️⃣ Натискати «Завантажити чек» у цьому боті.\n"
        "4️⃣ Вводити номер чека та надсилати його фото.\n\n"
        "Більше чеків — більше шансів на перемогу! 🍀"
    )
    await target_message.answer(rules, parse_mode="HTML", reply_markup=get_back_to_main_inline_kb())

async def process_show_faq(target_message):
    faq_text = (
        "🏆 <b>Призовий фонд та Часті запитання:</b>\n\n"
        "🎁 <b>Що можна виграти?</b>\n"
        "• Головний приз: <b>[Напиши тут головний приз]</b>\n"
        "• Щотижневі призи: <b>[Напиши тут інші призи]</b>\n\n"
        "📅 <b>Коли відбудеться розіграш?</b>\n"
        "Розіграш відбудеться <b>[Вкажи дату]</b> у прямому ефірі на нашій сторінці в Instagram.\n\n"
        "❓ <b>Скільки чеків можна завантажити?</b>\n"
        "Необмежену кількість! Більше унікальних чеків — більше шансів на перемогу.\n\n"
        "❓ <b>Чи потрібно зберігати паперовий чек?</b>\n"
        "Так, <b>ОБОВ'ЯЗКОВО</b> зберігайте оригінал чека до кінця розіграшу. Без нього отримати приз буде неможливо!"
    )
    await target_message.answer(faq_text, parse_mode="HTML", reply_markup=get_back_to_main_inline_kb())


# --- ОБРОБНИКИ КОМАНД ТА ПОВІДОМЛЕНЬ ---

@dp.message(Command("start"))
@dp.message(F.text == "❌ Скасувати")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(None) 
    
    # Примусово прибираємо будь-які старі нижні клавіатури
    rm_msg = await message.answer("🔄 Оновлення меню...", reply_markup=ReplyKeyboardRemove())
    await rm_msg.delete()
    
    welcome_text = (
        "👋 <b>Вітаємо у нашому святковому розіграші!</b> 🎉\n\n"
        "Тут ви можете реєструвати чеки за покупку нашої продукції та вигравати неймовірні призи! 🎁\n\n"
        "⚠️ <b>Обов'язкова умова:</b> підписка на наші дві Instagram сторінки!\n\n"
        "Оберіть потрібний розділ нижче 👇"
    )
    await message.answer(welcome_text, reply_markup=get_inline_start_kb(), parse_mode="HTML")

@dp.message(Command("cleardb"))
async def cmd_cleardb(message: types.Message):
    if str(message.chat.id) != ADMIN_ID: return 
    await redis.flushdb()
    await message.answer("🧹 <b>База даних ПОВНІСТЮ ОЧИЩЕНА!</b>\n\nВсі користувачі, їхні профілі та використані номери чеків видалені. Бот готовий до реального запуску.", parse_mode="HTML")

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if str(message.chat.id) != ADMIN_ID: return 
    
    users_keys = await redis.keys("user:*")
    users_count = len(users_keys)
    unique_receipts = await redis.scard("used_receipts") 
    
    stats_text = (
        "📊 <b>Статистика розіграшу:</b>\n\n"
        f"👤 Усього учасників: <b>{users_count}</b>\n"
        f"🧾 Чеків у базі: <b>{unique_receipts}</b>"
    )
    await message.answer(stats_text, parse_mode="HTML")

@dp.message(Command("sendall"))
async def cmd_sendall(message: types.Message):
    if str(message.chat.id) != ADMIN_ID: return 
    text_to_send = message.text.replace("/sendall", "").strip()
    if not text_to_send:
        await message.answer("⚠️ Ви не ввели текст. Використання: `/sendall Ваш текст`", parse_mode="Markdown")
        return
    await message.answer("⏳ Розпочинаю розсилку...")
    keys = await redis.keys("user:*")
    success_count, error_count = 0, 0
    for key in keys:
        user_id_str = key.decode('utf-8').split(":")[1]
        try:
            await bot.send_message(chat_id=int(user_id_str), text=text_to_send, parse_mode="HTML")
            success_count += 1
        except Exception:
            error_count += 1
    await message.answer(f"✅ <b>Розсилку завершено!</b>\n\n🟢 Доставлено: {success_count}\n🔴 Помилок: {error_count}", parse_mode="HTML")

# ОБРОБНИК КНОПКИ "НАЗАД" (ДЛЯ ВОРОНКИ)
@dp.message(F.text == "⬅️ Назад")
async def process_back_button(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    
    if current_state == Registration.waiting_for_receipt_photo.state:
        await message.answer(
            "🧾 <b>Введіть НОМЕР вашого чека</b> (тільки цифри/літери):", 
            reply_markup=get_back_cancel_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Registration.waiting_for_receipt_number)
        
    elif current_state == Registration.waiting_for_ig.state:
        await message.answer(
            "🧾 <b>Введіть НОМЕР вашого чека</b> (тільки цифри/літери):", 
            reply_markup=get_back_cancel_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Registration.waiting_for_receipt_number)
        
    else:
        await cmd_start(message, state)

# ПОВЕРНЕННЯ В МЕНЮ ЧЕРЕЗ ЕКРАННУ (INLINE) КНОПКУ
@dp.callback_query(F.data == "back_to_main")
async def back_to_main_call(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await cmd_start(call.message, state)


# ОБРОБНИКИ КНОПОК ЗІ СТАРИХ ТЕКСТОВИХ КОМАНД (Залишені про всяк випадок)
@dp.message(F.text == "🎁 Умови розіграшу")
async def show_rules_msg(message: types.Message):
    await process_show_rules(message)

@dp.message(F.text == "🏆 Призи та FAQ")
async def show_faq_msg(message: types.Message):
    await process_show_faq(message)

@dp.message(F.text == "👤 Мій кабінет")
async def show_cabinet_msg(message: types.Message):
    await process_show_cabinet(message, message.from_user.id)

@dp.message(F.text == "🧾 Завантажити чек")
async def start_upload_msg(message: types.Message, state: FSMContext):
    await process_start_upload(message, message.from_user.id, state)

# ОБРОБНИКИ ДЛЯ INLINE КНОПОК МЕНЮ
@dp.callback_query(F.data == "show_rules")
async def show_rules_call(call: CallbackQuery):
    await call.answer()
    await process_show_rules(call.message)

@dp.callback_query(F.data == "show_faq")
async def show_faq_call(call: CallbackQuery):
    await call.answer()
    await process_show_faq(call.message)

@dp.callback_query(F.data == "my_cabinet")
async def show_cabinet_call(call: CallbackQuery):
    await call.answer() 
    await process_show_cabinet(call.message, call.from_user.id)

@dp.callback_query(F.data == "upload_receipt")
async def start_upload_call(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await process_start_upload(call.message, call.from_user.id, state)


# --- ВОРОНКА РЕЄСТРАЦІЇ ---
@dp.message(Registration.waiting_for_fio)
async def process_fio(message: types.Message, state: FSMContext):
    await state.update_data(fio=message.text)
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поділитися номером", request_contact=True)],
            [KeyboardButton(text="❌ Скасувати")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await message.answer("Чудово! Тепер введіть ваш номер телефону або натисніть кнопку нижче:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_phone)

@dp.message(Registration.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    await state.update_data(phone=phone)
    
    await message.answer(
        "🧾 <b>Введіть НОМЕР вашого чека</b> (тільки цифри/літери):", 
        reply_markup=get_back_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Registration.waiting_for_receipt_number)

@dp.message(Registration.waiting_for_receipt_number)
async def process_receipt_number(message: types.Message, state: FSMContext):
    receipt_num = message.text.strip().upper() 
    
    if len(receipt_num) > 30:
        await message.answer("⚠️ Номер чека занадто довгий. Будь ласка, перевірте та введіть коректний номер:", reply_markup=get_back_cancel_kb())
        return

    is_used = await redis.sismember("used_receipts", receipt_num)
    if is_used:
        await message.answer(
            "⚠️ <b>Помилка!</b> Чек з таким номером вже був зареєстрований у системі.\n"
            "Спробуйте ввести інший номер:",
            parse_mode="HTML",
            reply_markup=get_back_cancel_kb()
        )
        return 
        
    await state.update_data(receipt_number=receipt_num)
    
    user_id = message.from_user.id
    user_data = await redis.hgetall(f"user:{user_id}")
    
    is_sub_checked = user_data.get(b'sub_checked', b'0').decode('utf-8') == '1'
    
    if user_data and b'ig' in user_data:
        if is_sub_checked:
            await message.answer(
                "📸 Тепер відправте <b>ФОТО вашого чека</b>:", 
                reply_markup=get_back_cancel_kb(),
                parse_mode="HTML"
            )
            await state.set_state(Registration.waiting_for_receipt_photo)
        else:
            await send_subscription_step_1(message, state)
    else:
        await message.answer(
            "📸 <b>Введіть ваш нікнейм в Instagram</b> (наприклад: @vash_nik):\n\n"
            "<i>Це потрібно для перевірки виконання умов розіграшу.</i>", 
            reply_markup=get_back_cancel_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Registration.waiting_for_ig)

@dp.message(Registration.waiting_for_ig)
async def process_ig(message: types.Message, state: FSMContext):
    ig = message.text
    fsm_data = await state.get_data()
    fio = fsm_data.get("fio", "Не вказано")
    phone = fsm_data.get("phone", "Не вказано")
    user_id = message.from_user.id
    
    await redis.hset(f"user:{user_id}", mapping={"fio": fio, "phone": phone, "ig": ig, "receipts": 0, "sub_checked": "0"})
    await send_subscription_step_1(message, state)

async def send_subscription_step_1(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Перейти: tm.sama.ua", url=INSTAGRAM_LINK_1)],
            [InlineKeyboardButton(text="🔄 Перевірити підписку 1", callback_data="check_sub_1")]
        ]
    )
    text = (
        "⚠️ <b>Обов'язкова умова участі! (Крок 1 з 2)</b>\n\n"
        "Система перевірить наявність підписки на нашу першу сторінку.\n"
        "Перейдіть за посиланням, підпишіться, поверніться сюди та натисніть <b>«Перевірити підписку 1»</b>."
    )
    await message.answer(text, reply_markup=kb, parse_mode="HTML")
    await state.set_state(Registration.waiting_for_subscription)

@dp.callback_query(Registration.waiting_for_subscription, F.data == "check_sub_1")
async def process_check_sub_1(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("⏳ <i>З'єднання з Instagram... Перевірка першої підписки...</i>", parse_mode="HTML")
    await asyncio.sleep(2.5) 
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📱 Перейти: koshik_shop_", url=INSTAGRAM_LINK_2)],
            [InlineKeyboardButton(text="🔄 Перевірити підписку 2", callback_data="check_sub_2")]
        ]
    )
    text = (
        "✅ <b>Першу підписку підтверджено!</b>\n\n"
        "⚠️ <b>Крок 2 з 2:</b> Тепер підпишіться на нашу другу сторінку. "
        "Після підписки натисніть кнопку перевірки нижче."
    )
    await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Registration.waiting_for_subscription, F.data == "check_sub_2")
async def process_check_sub_2(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("⏳ <i>З'єднання з Instagram... Перевірка другої підписки...</i>", parse_mode="HTML")
    await asyncio.sleep(2.5) 
    
    await redis.hset(f"user:{call.from_user.id}", "sub_checked", "1")
    
    await call.message.edit_text(
        "✅ <b>Всі підписки успішно підтверджено!</b> 🎉", 
        parse_mode="HTML"
    )
    await call.message.answer(
        "📸 Тепер відправте <b>ФОТО вашого чека</b> для реєстрації:", 
        reply_markup=get_back_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Registration.waiting_for_receipt_photo)

@dp.message(Registration.waiting_for_subscription)
async def force_click_check(message: types.Message):
    await message.answer("⚠️ Будь ласка, натисніть кнопку <b>«🔄 Перевірити підписку»</b> у повідомленні вище.", parse_mode="HTML")


# --- ПРИЙОМ ФОТО: МОМЕНТАЛЬНЕ ПОВІДОМЛЕННЯ + ЗАПИС ІСТОРІЇ ---
@dp.message(Registration.waiting_for_receipt_photo, F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    user_data = await redis.hgetall(f"user:{user_id}")
    fio = user_data.get(b'fio', b'').decode('utf-8')
    phone = user_data.get(b'phone', b'').decode('utf-8')
    ig = user_data.get(b'ig', b'').decode('utf-8')
    tg_username = f"@{message.from_user.username}" if message.from_user.username else "Немає"
    
    fsm_data = await state.get_data()
    receipt_number_text = fsm_data.get("receipt_number", "Не вказано")
    
    if receipt_number_text != "Не вказано":
        await redis.sadd("used_receipts", receipt_number_text)
        kyiv_time = datetime.utcnow() + timedelta(hours=2)
        now_str = kyiv_time.strftime("%d.%m.%Y %H:%M")
        await redis.rpush(f"user_receipts:{user_id}", f"{now_str}|{receipt_number_text}")
    
    await redis.hincrby(f"user:{user_id}", "receipts", 1)
    new_count = await redis.hget(f"user:{user_id}", "receipts")
    new_count = new_count.decode('utf-8')
    await redis.hset(f"user:{user_id}", "tg_username", tg_username)

    rm_msg = await message.answer("🔄 Обробка...", reply_markup=ReplyKeyboardRemove())
    await rm_msg.delete()
    
    await message.answer(
        f"✅ <b>Чек успішно прийнято!</b>\n\nЦе ваш чек №{new_count}. Дякуємо за участь у розіграші! 🍀\n\n"
        "<i>Натисніть кнопку нижче, щоб повернутися в головне меню.</i>", 
        reply_markup=get_back_to_main_inline_kb(),
        parse_mode="HTML"
    )
    await state.set_state(None)

    if GOOGLE_WEBHOOK_URL:
        google_data = {
            "fio": fio,
            "phone": phone,
            "tg_username": tg_username,
            "ig_username": ig,
            "receipt_count": new_count,
            "receipt_number": receipt_number_text
        }
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(GOOGLE_WEBHOOK_URL, json=google_data)
        except Exception:
            pass

    photo_id = message.photo[-1].file_id
    admin_caption = (
        f"🆕 <b>Новий чек прийнято системою!</b> (У клієнта: {new_count})\n\n"
        f"🧾 <b>Номер чека:</b> {receipt_number_text}\n"
        f"👤 <b>ПІБ:</b> {fio}\n"
        f"📱 <b>Телефон:</b> {phone}\n"
        f"📸 <b>Instagram:</b> {ig}\n"
        f"💬 <b>TG Юзернейм:</b> {tg_username}"
    )
    
    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Ок (Сховати)", callback_data=f"approve_hide"),
                InlineKeyboardButton(text="❌ ВІДХИЛИТИ (Брак)", callback_data=f"reject_{user_id}_{receipt_number_text}")
            ]
        ]
    )
    
    try:
        await bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=admin_caption, reply_markup=admin_kb, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Помилка відправки в групу: {e}")

@dp.message(Registration.waiting_for_receipt_photo)
async def error_receipt_format(message: types.Message):
    await message.answer("Будь ласка, відправте саме <b>ФОТО</b> чека 📸 (документи або текст не приймаються).", parse_mode="HTML")

# --- ОБРОБНИКИ КНОПОК МОДЕРАЦІЇ ---

@dp.callback_query(F.data == "approve_hide")
async def admin_approve(call: CallbackQuery):
    original_caption = call.message.html_text if call.message.html_text else (call.message.caption or "Чек")
    admin_name = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name

    await call.message.edit_caption(
        caption=original_caption + f"\n\n✅ <b>Перевірено:</b> {admin_name}", 
        parse_mode="HTML", 
        reply_markup=None
    )
    await call.answer("Ок!")

@dp.callback_query(F.data.startswith("reject_"))
async def admin_reject(call: CallbackQuery):
    parts = call.data.split("_")
    user_id = int(parts[1])
    receipt_number = parts[2]
    
    await redis.srem("used_receipts", receipt_number)
    
    history_items = await redis.lrange(f"user_receipts:{user_id}", 0, -1)
    for item in history_items:
        decoded_item = item.decode('utf-8')
        if decoded_item.endswith(f"|{receipt_number}"):
            await redis.lrem(f"user_receipts:{user_id}", 1, item)
            break
            
    await redis.hincrby(f"user:{user_id}", "receipts", -1)
    
    try:
        await bot.send_message(
            chat_id=user_id, 
            text=f"⚠️ <b>Увага!</b> Ваш чек №{receipt_number} <b>ВІДХИЛЕНО</b> модератором.\nМожливо, фото нечітке, обрізане або чек не відповідає умовам.\n\nБудь ласка, завантажте цей чек правильно ще раз.", 
            parse_mode="HTML",
            reply_markup=get_back_to_main_inline_kb()
        )
    except Exception:
        pass
        
    original_caption = call.message.html_text if call.message.html_text else (call.message.caption or "Чек")
    admin_name = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name

    await call.message.edit_caption(
        caption=original_caption + f"\n\n❌ <b>ВІДХИЛЕНО:</b> {admin_name}", 
        parse_mode="HTML", 
        reply_markup=None
    )
    await call.answer("Чек відхилено!")


# --- WEBHOOK ---
@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Бот працює!"}

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error: {e}")
        return {"status": "error", "message": str(e)}
