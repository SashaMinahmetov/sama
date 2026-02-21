import os
import logging
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

# Токен будем брать из переменных окружения Vercel
BOT_TOKEN = os.environ.get("BOT_TOKEN")

bot = Bot(token=BOT_TOKEN)
# ВНИМАНИЕ: MemoryStorage сбрасывается на Vercel между запросами. 
# Для продакшена мы заменим это на Redis.
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

class Registration(StatesGroup):
    waiting_for_fio = State()
    waiting_for_phone = State()
    waiting_for_receipt = State()

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
    await message.answer("Отлично! Теперь введите ваш номер или нажмите кнопку:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_phone)

@dp.message(Registration.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    await state.update_data(phone=phone)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🧾 Загрузить чек")]], resize_keyboard=True)
    await message.answer("Успешно!\nТеперь нажмите «Загрузить чек» внизу.", reply_markup=kb)
    await state.set_state(Registration.waiting_for_receipt)

@dp.message(Registration.waiting_for_receipt, F.text == "🧾 Загрузить чек")
async def ask_for_photo(message: types.Message):
    await message.answer("Прикрепите фото чека.", reply_markup=ReplyKeyboardRemove())

@dp.message(Registration.waiting_for_receipt, F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    photo_file_id = message.photo[-1].file_id
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="🧾 Загрузить чек")]], resize_keyboard=True)
    await message.answer("✅ Чек загружен!\nМожете загрузить еще.", reply_markup=kb)

# Эндпоинт, на который Telegram будет присылать сообщения пользователей
@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = types.Update(**data)
        await dp.feed_update(bot, update)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
    return {"status": "ok"}
