import os
import logging
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
# Добавляем импорт Inline кнопок
from aiogram.types import (
    ReplyKeyboardMarkup, 
    KeyboardButton, 
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from redis.asyncio import Redis

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REDIS_URL = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")
ADMIN_ID = "-1003731208847" 
INSTAGRAM_LINK = "https://instagram.com/твой_аккаунт" 

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=BOT_TOKEN)
redis = Redis.from_url(REDIS_URL)
storage = RedisStorage(redis=redis)
dp = Dispatcher(storage=storage)
app = FastAPI()

# --- СОСТОЯНИЯ ---
class Registration(StatesGroup):
    waiting_for_fio = State()
    waiting_for_phone = State()
    waiting_for_receipt = State()

# --- КЛАВИАТУРЫ ---

# 1. Нижняя панель (Главное меню) - всегда на экране
def get_main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧾 Завантажити чек"), KeyboardButton(text="👤 Мій кабінет")],
            [KeyboardButton(text="📸 Наш Instagram"), KeyboardButton(text="🎁 Умови розіграшу")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Оберіть пункт меню..."
    )

# 2. Кнопка для отправки телефона (только нижняя панель умеет это)
def get_contact_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поділитися номером", request_contact=True)],
            [KeyboardButton(text="❌ Скасувати")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# 3. Инлайн-кнопка (под сообщением) для Instagram
def get_instagram_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📸 Перейти в Instagram", url=INSTAGRAM_LINK)]
        ]
    )

# 4. Инлайн-кнопка (под сообщением) для Отмены
def get_cancel_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Скасувати реєстрацію", callback_data="cancel_action")]
        ]
    )

# --- ЛОГИКА БОТА ---

# Обработчик кнопки "Отмена" (Inline)
@dp.callback_query(F.data == "cancel_action")
async def callback_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete() # Удаляем сообщение с кнопкой
    await callback.message.answer("❌ Дія скасована.", reply_markup=get_main_kb())

# Обработчик текстовой кнопки "Отмена"
@dp.message(F.text == "❌ Скасувати")
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "👋 <b>Вітаємо у святковому розіграші!</b> 🎉\n\n"
        "Реєструйте чеки, накопичуйте шанси та вигравайте призи!\n"
        "Скористайтеся меню знизу 👇"
    )
    await message.answer(welcome_text, reply_markup=get_main_kb(), parse_mode="HTML")

# Instagram с красивой кнопкой-ссылкой
@dp.message(F.text == "📸 Наш Instagram")
async def show_instagram(message: types.Message):
    await message.answer(
        "Підписуйтесь на нас, щоб не пропустити результати! 👇",
        reply_markup=get_instagram_inline_kb() # <-- Красивая кнопка под текстом
    )

@dp.message(F.text == "🎁 Умови розіграшу")
async def show_rules(message: types.Message):
    rules = (
        "📜 <b>Як взяти участь:</b>\n\n"
        "1️⃣ Купіть акційну продукцію.\n"
        "2️⃣ Натисніть <b>«Завантажити чек»</b>.\n"
        "3️⃣ Зробіть фото чека.\n\n"
        "Переможців обираємо рандомно в Instagram! 🍀"
    )
    await message.answer(rules, parse_mode="HTML")

# Личный кабинет
@dp.message(F.text == "👤 Мій кабінет")
async def show_cabinet(message: types.Message):
    user_id = message.from_user.id
    user_data = await redis.hgetall(f"user:{user_id}")
    
    if not user_data:
        await message.answer("Ви ще не зареєстровані. Завантажте перший чек!", reply_markup=get_main_kb())
        return

    fio = user_data.get(b'fio', b'').decode('utf-8')
    phone = user_data.get(b'phone', b'').decode('utf-8')
    receipts_count = user_data.get(b'receipts', b'0').decode('utf-8')

    cabinet_text = (
        "👤 <b>Особистий кабінет</b>\n"
        "➖➖➖➖➖➖➖\n"
        f"📛 <b>Ім'я:</b> {fio}\n"
        f"📞 <b>Телефон:</b> {phone}\n"
        f"🎟 <b>Ваші чеки:</b> {receipts_count}\n"
        "➖➖➖➖➖➖➖"
    )
    await message.answer(cabinet_text, parse_mode="HTML")

# --- ПРОЦЕСС ЗАГРУЗКИ ---

@dp.message(F.text == "🧾 Завантажити чек")
async def start_receipt_upload(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await redis.hgetall(f"user:{user_id}")
    
    # Скрываем нижнюю панель, чтобы не мешала, или оставляем кнопку Отмена
    if not user_data or b'phone' not in user_data:
        await message.answer(
            "📝 Введіть ваше <b>Прізвище та Ім'я</b> для реєстрації:", 
            reply_markup=ReplyKeyboardRemove(), # Убираем меню на время ввода
            parse_mode="HTML"
        )
        # Добавляем кнопку отмены под текстом
        await message.answer("Або натисніть кнопку для скасування:", reply_markup=get_cancel_inline_kb())
        await state.set_state(Registration.waiting_for_fio)
    else:
        await message.answer(
            "📸 <b>Відправте фото чека</b>", 
            reply_markup=get_cancel_inline_kb(), # Кнопка отмены прямо под сообщением
            parse_mode="HTML"
        )
        await state.set_state(Registration.waiting_for_receipt)

@dp.message(Registration.waiting_for_fio)
async def process_fio(message: types.Message, state: FSMContext):
    await state.update_data(fio=message.text)
    # Тут используем Нижнюю клавиатуру, так как Request Contact работает ТОЛЬКО снизу
    await message.answer(
        "📱 Тепер натисніть кнопку <b>«Поділитися номером»</b> знизу:", 
        reply_markup=get_contact_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Registration.waiting_for_phone)

@dp.message(Registration.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    fsm_data = await state.get_data()
    fio = fsm_data.get("fio", "Не вказано")
    
    user_id = message.from_user.id
    await redis.hset(f"user:{user_id}", mapping={"fio": fio, "phone": phone, "receipts": 0})
    
    await message.answer(
        "✅ Реєстрація успішна! Тепер відправте фото чека.", 
        reply_markup=get_cancel_inline_kb() # Снова красивая инлайн кнопка
    )
    await state.set_state(Registration.waiting_for_receipt)

@dp.message(Registration.waiting_for_receipt, F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await redis.hincrby(f"user:{user_id}", "receipts", 1)
    new_count = (await redis.hget(f"user:{user_id}", "receipts")).decode('utf-8')
    
    # Получаем данные для админа
    user_data = await redis.hgetall(f"user:{user_id}")
    fio = user_data.get(b'fio', b'Unknown').decode('utf-8')
    phone = user_data.get(b'phone', b'Unknown').decode('utf-8')

    # Отправка админу
    try:
        await bot.send_photo(
            chat_id=ADMIN_ID, 
            photo=message.photo[-1].file_id, 
            caption=f"🧾 <b>Новий чек! (Всього: {new_count})</b>\n👤 {fio}\n📱 {phone}\n🔗 @{message.from_user.username}", 
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Error sending to admin: {e}")

    await message.answer(
        f"🎉 <b>Чек №{new_count} прийнято!</b>\nДякуємо за участь.", 
        reply_markup=get_main_kb(), # Возвращаем главное меню
        parse_mode="HTML"
    )
    await state.set_state(None)

@dp.message(Registration.waiting_for_receipt, F.text)
async def error_receipt(message: types.Message):
    await message.answer("📸 Будь ласка, надішліть <b>фото</b>.", reply_markup=get_cancel_inline_kb(), parse_mode="HTML")

# --- WEBHOOK ---
@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Bot is running"}

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
