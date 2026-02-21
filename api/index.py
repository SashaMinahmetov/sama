import os
import logging
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from redis.asyncio import Redis

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REDIS_URL = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")
ADMIN_ID = "-1003731208847" 
INSTAGRAM_LINK = "https://instagram.com/твой_аккаунт" # Замени на свою ссылку

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
def get_main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧾 Завантажити чек"), KeyboardButton(text="👤 Мій кабінет")],
            [KeyboardButton(text="📸 Наш Instagram"), KeyboardButton(text="🎁 Умови розіграшу")]
        ],
        resize_keyboard=True
    )

def get_cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Скасувати")]],
        resize_keyboard=True
    )

# --- ЛОГИКА БОТА ---

# 1. Главное меню и приветствие
@dp.message(Command("start"))
@dp.message(F.text == "❌ Скасувати")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(None) # Сбрасываем любые начатые действия
    welcome_text = (
        "👋 <b>Вітаємо у нашому святковому розіграші!</b> 🎉\n\n"
        "Тут ви можете реєструвати чеки за покупку нашої продукції та вигравати неймовірні призи! 🎁\n\n"
        "Оберіть потрібний розділ меню нижче 👇"
    )
    await message.answer(welcome_text, reply_markup=get_main_kb(), parse_mode="HTML")

# 2. Инстаграм и Условия
@dp.message(F.text == "📸 Наш Instagram")
async def show_instagram(message: types.Message):
    await message.answer(f"Слідкуйте за нами та результатами розіграшу в Instagram!\n👉 {INSTAGRAM_LINK}")

@dp.message(F.text == "🎁 Умови розіграшу")
async def show_rules(message: types.Message):
    rules = (
        "📜 <b>Умови дуже прості:</b>\n\n"
        "1️⃣ Купуйте нашу продукцію у мережі магазинів.\n"
        "2️⃣ Натискайте «Завантажити чек» у цьому боті.\n"
        "3️⃣ Надсилайте фото чека та беріть участь у розіграші!\n\n"
        "Більше чеків — більше шансів на перемогу! 🍀"
    )
    await message.answer(rules, parse_mode="HTML")

# 3. Личный кабинет (Чтение из Redis)
@dp.message(F.text == "👤 Мій кабінет")
async def show_cabinet(message: types.Message):
    user_id = message.from_user.id
    # Получаем профиль из базы
    user_data = await redis.hgetall(f"user:{user_id}")
    
    if not user_data:
        await message.answer(
            "🤷‍♂️ Ви ще не зареєстровані.\nНатисніть «🧾 Завантажити чек», щоб створити профіль та додати перший чек!", 
            reply_markup=get_main_kb()
        )
        return

    # Декодируем данные из Redis
    fio = user_data.get(b'fio', b'').decode('utf-8')
    phone = user_data.get(b'phone', b'').decode('utf-8')
    receipts_count = user_data.get(b'receipts', b'0').decode('utf-8')

    cabinet_text = (
        "👤 <b>Ваш особистий кабінет:</b>\n\n"
        f"🔸 <b>ПІБ:</b> {fio}\n"
        f"🔸 <b>Телефон:</b> {phone}\n"
        f"🎫 <b>Зареєстровано чеків:</b> {receipts_count}\n\n"
        "Так тримати! Чим більше чеків, тим ближче перемога 🏆"
    )
    await message.answer(cabinet_text, parse_mode="HTML")

# 4. Процесс загрузки чека (с проверкой регистрации)
@dp.message(F.text == "🧾 Завантажити чек")
async def start_receipt_upload(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await redis.hgetall(f"user:{user_id}")
    
    # Если пользователь еще не вводил данные
    if not user_data or b'phone' not in user_data:
        await message.answer(
            "📝 Для початку реєстрації, будь ласка, <b>напишіть ваше ПІБ</b> (Прізвище, Ім'я, По батькові):", 
            reply_markup=get_cancel_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Registration.waiting_for_fio)
    else:
        # Если уже зарегистрирован — сразу просим чек
        await message.answer(
            "📸 Будь ласка, відправте чітке фото вашого чека.", 
            reply_markup=get_cancel_kb()
        )
        await state.set_state(Registration.waiting_for_receipt)

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
    
    # Получаем ФИО из временного состояния FSM
    fsm_data = await state.get_data()
    fio = fsm_data.get("fio", "Не вказано")
    
    # СОХРАНЯЕМ ПРОФИЛЬ В REDIS НАВСЕГДА
    user_id = message.from_user.id
    await redis.hset(f"user:{user_id}", mapping={
        "fio": fio, 
        "phone": phone, 
        "receipts": 0 # Стартовое количество чеков
    })
    
    await message.answer(
        "✅ <b>Реєстрація успішна!</b>\n\nТепер відправте фото вашого чека 📸", 
        reply_markup=get_cancel_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Registration.waiting_for_receipt)

@dp.message(Registration.waiting_for_receipt, F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    # Берем данные прямо из профиля Redis
    user_data = await redis.hgetall(f"user:{user_id}")
    fio = user_data.get(b'fio', b'').decode('utf-8')
    phone = user_data.get(b'phone', b'').decode('utf-8')
    
    # УВЕЛИЧИВАЕМ СЧЕТЧИК ЧЕКОВ НА +1
    await redis.hincrby(f"user:{user_id}", "receipts", 1)
    new_count = await redis.hget(f"user:{user_id}", "receipts")
    new_count = new_count.decode('utf-8')

    photo_id = message.photo[-1].file_id

    # Отправляем в группу админам
    admin_caption = (
        f"🆕 <b>Новий чек! (Всього у клієнта: {new_count})</b>\n\n"
        f"👤 <b>ПІБ:</b> {fio}\n"
        f"📱 <b>Телефон:</b> {phone}\n"
        f"💬 <b>Юзернейм:</b> @{message.from_user.username if message.from_user.username else 'Немає'}"
    )
    
    try:
        await bot.send_photo(chat_id=ADMIN_ID, photo=photo_id, caption=admin_caption, parse_mode="HTML")
    except Exception as e:
        logging.error(f"Помилка відправки в групу: {e}")

    await message.answer(
        f"✅ <b>Чек успішно прийнято!</b>\n\nЦе ваш чек №{new_count}. Дякуємо за участь!", 
        reply_markup=get_main_kb(),
        parse_mode="HTML"
    )
    await state.set_state(None) # Возвращаем в главное меню

# На случай, если на шаге чека прислали текст, а не фото
@dp.message(Registration.waiting_for_receipt, F.text)
async def error_receipt_format(message: types.Message):
    await message.answer("Будь ласка, відправте саме <b>ФОТО</b> чека 📸", parse_mode="HTML")

# --- WEBHOOK ---
@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Бот з особистим кабінетом працює!"}

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
