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

# Вставляем ID группы ОБЯЗАТЕЛЬНО С МИНУСОМ (и в кавычках)
ADMIN_ID = "-1003731208847"

# Пытаемся найти адрес базы данных (Vercel создает KV_URL или KV_REST_API_URL)
REDIS_URL = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")

# --- ИНИЦИАЛИЗАЦИЯ ---
bot = Bot(token=BOT_TOKEN)

# Если Redis подключен — используем его. Если нет — упадем с ошибкой (чтобы сразу понять).
if not REDIS_URL:
    raise ValueError("Не найдена переменная окружения KV_URL. Проверьте подключение базы в Vercel Storage.")

# Создаем подключение к Redis и передаем его в диспетчер
redis = Redis.from_url(REDIS_URL)
storage = RedisStorage(redis=redis)
dp = Dispatcher(storage=storage)

app = FastAPI()

# --- СОСТОЯНИЯ ---
class Registration(StatesGroup):
    waiting_for_fio = State()
    waiting_for_phone = State()
    waiting_for_receipt = State()

# --- ЛОГИКА БОТА ---

@dp.message(F.text == "/start")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Добро пожаловать в розыгрыш! 🎉\n\nДля участия напишите ваше ФИО:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Registration.waiting_for_fio)

@dp.message(Registration.waiting_for_fio)
async def process_fio(message: types.Message, state: FSMContext):
    await state.update_data(fio=message.text)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    
    await message.answer(
        "Отлично! Теперь введите ваш номер телефона или нажмите кнопку ниже:",
        reply_markup=kb
    )
    await state.set_state(Registration.waiting_for_phone)

@dp.message(Registration.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    # Получаем телефон (или текстом, или контактом)
    phone = message.contact.phone_number if message.contact else message.text
    await state.update_data(phone=phone)
    
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🧾 Загрузить чек")]],
        resize_keyboard=True
    )
    
    await message.answer(
        "Данные приняты! Остался последний шаг.\nНажмите кнопку «Загрузить чек» и прикрепите фото.",
        reply_markup=kb
    )
    await state.set_state(Registration.waiting_for_receipt)

@dp.message(Registration.waiting_for_receipt, F.text == "🧾 Загрузить чек")
async def ask_for_photo(message: types.Message):
    await message.answer(
        "Пожалуйста, отправьте фото чека.",
        reply_markup=ReplyKeyboardRemove()
    )

@dp.message(Registration.waiting_for_receipt, F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    # Получаем все данные пользователя из Redis
    user_data = await state.get_data()
    fio = user_data.get("fio")
    phone = user_data.get("phone")
    photo_id = message.photo[-1].file_id

    # Тут потом добавим отправку в Гугл Таблицы
    logging.info(f"ЗАЯВКА: {fio} | {phone} | ФОТО: {photo_id}")

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🧾 Загрузить чек")]],
        resize_keyboard=True
    )
    await message.answer(
        "✅ Чек принят! Вы участвуете в розыгрыше.\nЕсли есть еще чеки — загружайте.",
        reply_markup=kb
    )

# --- WEBHOOK ---

@app.get("/")
async def health_check():
    return {"status": "ok", "message": "Бот работает на Redis!"}

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
