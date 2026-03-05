import os
import logging
import aiohttp
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
INSTAGRAM_LINK_1 = "https://instagram.com/vasia_pupkin" # Замени на 1 страницу
INSTAGRAM_LINK_2 = "https://instagram.com/vasia_pupkin2" # Замени на 2 страницу

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
    waiting_for_ig = State() # НОВОЕ: Ждем ник в инсте
    waiting_for_receipt_number = State() # НОВОЕ: Ждем номер чека
    waiting_for_receipt_photo = State() # Ждем фото чека

# --- КЛАВІАТУРИ ---
def get_main_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧾 Завантажити чек"), KeyboardButton(text="👤 Мій кабінет")],
            [KeyboardButton(text="🎁 Умови розіграшу")]
        ],
        resize_keyboard=True
    )

def get_inline_start_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧾 Завантажити чек", callback_data="upload_receipt")],
            [InlineKeyboardButton(text="👤 Мій кабінет", callback_data="my_cabinet")],
            [InlineKeyboardButton(text="📸 Наш Instagram 1", url=INSTAGRAM_LINK_1)],
            [InlineKeyboardButton(text="📸 Наш Instagram 2", url=INSTAGRAM_LINK_2)]
        ]
    )

def get_cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Скасувати")]],
        resize_keyboard=True
    )

# --- СПІЛЬНА ЛОГІКА ДЛЯ КНОПОК ---
async def process_show_cabinet(target_message, user_id: int):
    user_data = await redis.hgetall(f"user:{user_id}")
    
    if not user_data:
        await target_message.answer(
            "🤷‍♂️ Ви ще не зареєстровані.\nНатисніть «🧾 Завантажити чек», щоб створити профіль та додати перший чек!", 
            reply_markup=get_main_reply_kb()
        )
        return

    fio = user_data.get(b'fio', b'').decode('utf-8')
    phone = user_data.get(b'phone', b'').decode('utf-8')
    ig = user_data.get(b'ig', b'').decode('utf-8')
    receipts_count = user_data.get(b'receipts', b'0').decode('utf-8')

    cabinet_text = (
        "👤 <b>Ваш особистий кабінет:</b>\n\n"
        f"🔸 <b>ПІБ:</b> {fio}\n"
        f"🔸 <b>Телефон:</b> {phone}\n"
        f"🔸 <b>Instagram:</b> {ig}\n"
        f"🎫 <b>Зареєстровано чеків:</b> {receipts_count}\n\n"
        "Так тримати! Чим більше чеків, тим ближче перемога 🏆"
    )
    await target_message.answer(cabinet_text, parse_mode="HTML")

async def process_start_upload(target_message, user_id: int, state: FSMContext):
    user_data = await redis.hgetall(f"user:{user_id}")
    
    # Если нет инсты в базе (значит регистрация не пройдена)
    if not user_data or b'ig' not in user_data:
        await target_message.answer(
            "📝 Для початку реєстрації, будь ласка, <b>напишіть ваше ПІБ</b> (Прізвище, Ім'я, По батькові):", 
            reply_markup=get_cancel_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Registration.waiting_for_fio)
    else:
        # Если юзер уже есть в базе, сразу просим номер нового чека
        await target_message.answer(
            "🧾 <b>Введіть НОМЕР вашого чека</b> (тільки цифри/літери):", 
            reply_markup=get_cancel_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Registration.waiting_for_receipt_number)


# --- ОБРОБНИКИ КОМАНД ТА ПОВІДОМЛЕНЬ ---
@dp.message(Command("start"))
@dp.message(F.text == "❌ Скасувати")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(None) 
    await message.answer("Головне меню відкрито 👇", reply_markup=get_main_reply_kb())
    welcome_text = (
        "👋 <b>Вітаємо у нашому святковому розіграші!</b> 🎉\n\n"
        "Тут ви можете реєструвати чеки за покупку нашої продукції та вигравати неймовірні призи! 🎁\n\n"
        "⚠️ <b>Обов'язкова умова:</b> підписка на наші дві Instagram сторінки!\n\n"
        "Оберіть потрібний розділ нижче 👇"
    )
    await message.answer(welcome_text, reply_markup=get_inline_start_kb(), parse_mode="HTML")


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
        except Exception as e:
            error_count += 1
    await message.answer(f"✅ <b>Розсилку завершено!</b>\n\n🟢 Доставлено: {success_count}\n🔴 Помилок: {error_count}", parse_mode="HTML")


@dp.message(F.text == "🎁 Умови розіграшу")
async def show_rules(message: types.Message):
    rules = (
        "📜 <b>Умови дуже прості:</b>\n\n"
        "1️⃣ Бути підписаним на наші 2 сторінки в Instagram.\n"
        "2️⃣ Купувати нашу продукцію.\n"
        "3️⃣ Натискати «Завантажити чек» у цьому боті.\n"
        "4️⃣ Вводити номер чека та надсилати його фото.\n\n"
        "Більше чеків — більше шансів на перемогу! 🍀"
    )
    await message.answer(rules, parse_mode="HTML")

@dp.message(F.text == "👤 Мій кабінет")
async def show_cabinet_msg(message: types.Message):
    await process_show_cabinet(message, message.from_user.id)

@dp.callback_query(F.data == "my_cabinet")
async def show_cabinet_call(call: CallbackQuery):
    await call.answer() 
    await process_show_cabinet(call.message, call.from_user.id)

@dp.message(F.text == "🧾 Завантажити чек")
async def start_upload_msg(message: types.Message, state: FSMContext):
    await process_start_upload(message, message.from_user.id, state)

@dp.callback_query(F.data == "upload_receipt")
async def start_upload_call(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await process_start_upload(call.message, call.from_user.id, state)

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
        "📸 <b>Введіть ваш нікнейм в Instagram</b> (наприклад: @vash_nik):\n\n"
        "<i>Ми перевіримо підписку на наші сторінки під час розіграшу!</i>", 
        reply_markup=get_cancel_kb(),
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
    
    # ЗБЕРІГАЄМО ПРОФІЛЬ В БАЗУ НАЗАВЖДИ
    await redis.hset(f"user:{user_id}", mapping={"fio": fio, "phone": phone, "ig": ig, "receipts": 0})
    
    await message.answer(
        "✅ <b>Реєстрація успішна!</b>\n\n🧾 Тепер <b>введіть НОМЕР вашого чека</b>:", 
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Registration.waiting_for_receipt_number)

@dp.message(Registration.waiting_for_receipt_number)
async def process_receipt_number(message: types.Message, state: FSMContext):
    # Зберігаємо номер чека у тимчасову пам'ять
    await state.update_data(receipt_number=message.text)
    
    await message.answer(
        "📸 Тепер відправте <b>ФОТО цього чека</b> для підтвердження:", 
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Registration.waiting_for_receipt_photo)

@dp.message(Registration.waiting_for_receipt_photo, F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    user_data = await redis.hgetall(f"user:{user_id}")
    fio = user_data.get(b'fio', b'').decode('utf-8')
    phone = user_data.get(b'phone', b'').decode('utf-8')
    ig = user_data.get(b'ig', b'').decode('utf-8')
    
    fsm_data = await state.get_data()
    receipt_number_text = fsm_data.get("receipt_number", "Не вказано")
    
    await redis.hincrby(f"user:{user_id}", "receipts", 1)
    new_count = await redis.hget(f"user:{user_id}", "receipts")
    new_count = new_count.decode('utf-8')

    photo_id = message.photo[-1].file_id
    username = f"@{message.from_user.username}" if message.from_user.username else "Немає"

    # 1. Відправка адмінам в Telegram
    admin_caption = (
        f"🆕 <b>Новий чек! (У клієнта чеків: {new_count})</b>\n\n"
        f"🧾 <b>Номер чека (введений):</b> {receipt_number_text}\n\n"
        f"👤 <b>ПІБ:</b> {fio}\n"
        f"📱 <b>Телефон:</b> {phone}\n"
        f"📸 <b>Instagram:</b> {ig}\n"
        f"💬 <b>TG Юзернейм:</b> {username}"
    )
    
    try:
        await bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=admin_caption, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Помилка відправки в групу: {e}")

    # 2. Відправка в Google Таблицю
    if GOOGLE_WEBHOOK_URL:
        google_data = {
            "fio": fio,
            "phone": phone,
            "tg_username": username,
            "ig_username": ig,
            "receipt_count": new_count,
            "receipt_number": receipt_number_text
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(GOOGLE_WEBHOOK_URL, json=google_data) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        await bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ Помилка Google Таблиці! Статус: {response.status}\nТекст: {error_text}")
        except Exception as e:
            await bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ Технічна помилка підключення до Google: {e}")

    await message.answer(
        f"✅ <b>Чек успішно прийнято!</b>\n\nЦе ваш чек №{new_count}. Дякуємо за участь!", 
        reply_markup=get_main_reply_kb(),
        parse_mode="HTML"
    )
    await state.set_state(None)

@dp.message(Registration.waiting_for_receipt_photo, F.text)
async def error_receipt_format(message: types.Message):
    await message.answer("Будь ласка, відправте саме <b>ФОТО</b> чека 📸", parse_mode="HTML")

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
