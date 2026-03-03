import os
import logging
import aiohttp
import asyncio
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
import google.generativeai as genai
from io import BytesIO

# --- НАЛАШТУВАННЯ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REDIS_URL = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")
GOOGLE_WEBHOOK_URL = os.environ.get("GOOGLE_WEBHOOK_URL") 
GOOGLE_AI_KEY = os.environ.get("GOOGLE_AI_KEY") 
ADMIN_ID = "-1003731208847" 
INSTAGRAM_LINK = "https://instagram.com/твой_аккаунт"

# --- СПИСОК АКЦІЙНИХ ТОВАРІВ ---
# Форматуємо в один рядок для кращого розуміння AI
PROMO_PRODUCTS_LIST = [
    "ЛЮБИСТОК", "ТОРЧИН", "RIO", "MOLENDAM", "МОЛЕНДАМ", 
    "КЕТЧУП", "АНАНАСИ", "ШАМПІНЬЙОНИ", "ПРИПРАВА"
]
PROMO_PRODUCTS_STR = ", ".join(PROMO_PRODUCTS_LIST)

# --- ІНІЦІАЛІЗАЦІЯ ---
bot = Bot(token=BOT_TOKEN)

if not REDIS_URL:
    raise ValueError("Не знайдено змінну оточення KV_URL")

redis = Redis.from_url(REDIS_URL)
storage = RedisStorage(redis=redis)
dp = Dispatcher(storage=storage)
app = FastAPI()

# Налаштування AI Gemini
if GOOGLE_AI_KEY:
    genai.configure(api_key=GOOGLE_AI_KEY)
    # ВАЖЛИВО: Змінюємо 'flash' на 'pro' для кращого зору
    # Якщо pro буде падати з помилкою квоти, зміни назад на 'gemini-1.5-flash'
    model = genai.GenerativeModel('gemini-1.5-pro')

# --- СТАНИ FSM ---
class Registration(StatesGroup):
    waiting_for_fio = State()
    waiting_for_phone = State()
    waiting_for_receipt = State()

# --- КЛАВІАТУРИ ---
def get_main_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🧾 Завантажити чек"), KeyboardButton(text="👤 Мій кабінет")],
            [KeyboardButton(text="🎁 Умови розіграшу")]
        ],
        resize_keyboard=True
    )

def get_cancel_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Скасувати")]],
        resize_keyboard=True
    )

def get_inline_start_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧾 Завантажити чек", callback_data="upload_receipt")],
            [InlineKeyboardButton(text="👤 Мій кабінет", callback_data="my_cabinet")],
            [InlineKeyboardButton(text="📸 Наш Instagram", url=INSTAGRAM_LINK)]
        ]
    )

def get_manual_review_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👨‍💻 Відправити на перевірку", callback_data="force_manual_review")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_upload")]
        ]
    )

# --- ФУНКЦІЯ ПЕРЕВІРКИ ЧЕКА (AI GEMINI PRO) ---
async def check_receipt_with_ai(photo_bytes):
    if not GOOGLE_AI_KEY:
        return False, "❌ Помилка: Немає API ключа"
    
    try:
        image_part = {"mime_type": "image/jpeg", "data": photo_bytes}
        
        # Більш детальний промпт
        prompt = f"""
        Analyze this image carefully. It is a store receipt.
        
        Target Keywords: {PROMO_PRODUCTS_STR}
        
        Step 1: Read ALL text from the receipt.
        Step 2: Check if ANY of the Target Keywords appear in the text.
        Step 3: Ignore case and small typos (e.g. "30Г" vs "З0Г").
        
        OUTPUT FORMAT:
        If FOUND: Start response with "YES". Then list what you found.
        If NOT FOUND: Start response with "NO". Then list 5-10 main products you actually saw on the receipt (for debugging).
        """
        
        # Виконуємо запит (це може зайняти 3-5 секунд)
        response = await asyncio.to_thread(model.generate_content, [prompt, image_part])
        answer = response.text.strip()
        
        # Логіка визначення
        if answer.upper().startswith("YES"):
            return True, answer # Повертаємо повну відповідь для логів
        else:
            return False, answer # Повертаємо пояснення, що він там побачив
            
    except Exception as e:
        logging.error(f"AI Check Error: {e}")
        return False, f"Технічна помилка AI: {str(e)}"

# --- ОБРОБНИКИ (HANDLERS) ---

@dp.message(Command("start"))
@dp.message(F.text == "❌ Скасувати")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(None) 
    await message.answer("Головне меню 👇", reply_markup=get_main_reply_kb())
    await message.answer("👋 <b>Вітаємо у розіграші!</b>", reply_markup=get_inline_start_kb(), parse_mode="HTML")

@dp.callback_query(F.data == "cancel_upload")
async def callback_cancel(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await cmd_start(call.message, state)

@dp.message(Command("sendall"))
async def cmd_sendall(message: types.Message):
    if str(message.chat.id) != ADMIN_ID: return 
    text_to_send = message.text.replace("/sendall", "").strip()
    if not text_to_send:
        await message.answer("Введіть текст розсилки.")
        return
    await message.answer("⏳ Розпочинаю розсилку...")
    keys = await redis.keys("user:*")
    success, error = 0, 0
    for key in keys:
        uid = key.decode('utf-8').split(":")[1]
        try:
            await bot.send_message(chat_id=int(uid), text=text_to_send, parse_mode="HTML")
            success += 1
        except: error += 1
    await message.answer(f"✅ Результат розсилки:\nУспішно: {success}\nНе доставлено: {error}")

@dp.message(F.text == "🎁 Умови розіграшу")
async def show_rules(message: types.Message):
    products_list = "\n".join([f"• {p}" for p in PROMO_PRODUCTS_LIST])
    await message.answer(f"Купуйте товари брендів:\n{products_list}\n\nЗавантажуйте чек та вигравайте!", parse_mode="HTML")

@dp.message(F.text == "👤 Мій кабінет")
async def show_cabinet_msg(message: types.Message):
    await process_show_cabinet(message, message.from_user.id)

@dp.callback_query(F.data == "my_cabinet")
async def show_cabinet_call(call: CallbackQuery):
    await call.answer() 
    await process_show_cabinet(call.message, call.from_user.id)

async def process_show_cabinet(target_message, user_id):
    user_data = await redis.hgetall(f"user:{user_id}")
    if not user_data:
        await target_message.answer("Ви ще не зареєстровані.", reply_markup=get_main_reply_kb())
        return
    fio = user_data.get(b'fio', b'').decode('utf-8')
    receipts_count = user_data.get(b'receipts', b'0').decode('utf-8')
    await target_message.answer(f"👤 <b>Особистий кабінет:</b>\n\n🔸 ПІБ: {fio}\n🎫 Чеків: {receipts_count}", parse_mode="HTML")

@dp.message(F.text == "🧾 Завантажити чек")
async def start_upload_msg(message: types.Message, state: FSMContext):
    await process_start_upload(message, message.from_user.id, state)

@dp.callback_query(F.data == "upload_receipt")
async def start_upload_call(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await process_start_upload(call.message, call.from_user.id, state)

async def process_start_upload(target_message, user_id, state):
    user_data = await redis.hgetall(f"user:{user_id}")
    if not user_data or b'phone' not in user_data:
        await target_message.answer("📝 Введіть ваше Прізвище та Ім'я:", reply_markup=get_cancel_kb())
        await state.set_state(Registration.waiting_for_fio)
    else:
        await target_message.answer("📸 Надішліть фото чека (система автоматично перевірить наявність товару).", reply_markup=get_cancel_kb())
        await state.set_state(Registration.waiting_for_receipt)

@dp.message(Registration.waiting_for_fio)
async def process_fio(message: types.Message, state: FSMContext):
    await state.update_data(fio=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Поділитися номером", request_contact=True)]], resize_keyboard=True)
    await message.answer("Чудово! Натисніть кнопку, щоб поділитися номером:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_phone)

@dp.message(Registration.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = message.contact.phone_number if message.contact else message.text
    fsm_data = await state.get_data()
    user_id = message.from_user.id
    await redis.hset(f"user:{user_id}", mapping={"fio": fsm_data.get("fio"), "phone": phone, "receipts": 0})
    await message.answer("✅ Реєстрація успішна! Тепер надішліть фото чека 📸", reply_markup=get_cancel_kb())
    await state.set_state(Registration.waiting_for_receipt)

# --- ГОЛОВНА ЛОГІКА ОБРОБКИ ФОТО ---
@dp.message(Registration.waiting_for_receipt, F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    waiting_msg = await message.answer("⏳ <b>AI сканує чек... (це може зайняти до 5 сек)</b>", parse_mode="HTML")
    
    # 1. Завантажуємо фото
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    photo_bytes = BytesIO()
    await bot.download_file(file_info.file_path, destination=photo_bytes)
    photo_data = photo_bytes.getvalue()

    # 2. Перевіряємо через Gemini AI
    is_valid, ai_response = await check_receipt_with_ai(photo_data)

    if not is_valid:
        await waiting_msg.delete()
        await state.update_data(last_photo_id=photo.file_id)
        
        # --- ВАЖЛИВО: Шлемо звіт адміну про те, чому відмова ---
        # Щоб ти бачив, що саме прочитав бот
        report = (
            f"⚠️ <b>АВТО-ВІДМОВА</b>\n\n"
            f"🤖 <b>Відповідь AI:</b>\n{ai_response[:300]}..." # Обрізаємо, якщо дуже довга
        )
        try:
            await bot.send_message(chat_id=ADMIN_ID, text=report, parse_mode="HTML")
        except: pass

        await message.answer(
            "⚠️ <b>Система не знайшла акційні товари.</b>\n\n"
            "Можливо, назва товару скорочена або фото нечітке.\n"
            "Якщо ви впевнені, натисніть кнопку нижче для ручної перевірки.",
            reply_markup=get_manual_review_kb(),
            parse_mode="HTML"
        )
        return

    # 3. Якщо AI підтвердив - зберігаємо
    await finalize_receipt(message, state, photo.file_id, f"✅ AI OK: {ai_response[:50]}...")
    await waiting_msg.delete()

# Обробка кнопки "Ручна перевірка"
@dp.callback_query(F.data == "force_manual_review")
async def process_manual_review(call: CallbackQuery, state: FSMContext):
    await call.answer()
    data = await state.get_data()
    photo_id = data.get("last_photo_id")
    
    if not photo_id:
        await call.message.answer("Помилка: фото втрачено. Спробуйте завантажити знову.")
        return

    await finalize_receipt(call.message, state, photo_id, "⚠️ РУЧНА ПЕРЕВІРКА (Клієнт наполягає)")

# Допоміжна функція збереження даних
async def finalize_receipt(message, state, photo_id, admin_status_text):
    user_id = message.chat.id
    user_data = await redis.hgetall(f"user:{user_id}")
    fio = user_data.get(b'fio', b'').decode('utf-8')
    phone = user_data.get(b'phone', b'').decode('utf-8')
    username = f"@{message.chat.username}" if message.chat.username else "Немає"

    # Збільшуємо лічильник чеків
    await redis.hincrby(f"user:{user_id}", "receipts", 1)
    new_count = await redis.hget(f"user:{user_id}", "receipts")
    new_count = new_count.decode('utf-8')

    # Відправка в адмін-групу
    try:
        await bot.send_photo(
            chat_id=ADMIN_ID, 
            photo=photo_id, 
            caption=f"{admin_status_text}\nЧек №{new_count}\n👤 {fio}\n📱 {phone}", 
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Error sending to admin: {e}")

    # Відправка в Google Таблицю
    if GOOGLE_WEBHOOK_URL:
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(GOOGLE_WEBHOOK_URL, json={
                    "fio": fio, 
                    "phone": phone, 
                    "username": username, 
                    "receipt_number": new_count
                })
        except: pass

    # Відповідь користувачу
    success_text = f"✅ <b>Чек прийнято!</b> (Ваш чек №{new_count})\nДякуємо за участь!"
    
    if isinstance(message, types.Message): 
        await message.answer(success_text, reply_markup=get_main_reply_kb(), parse_mode="HTML")
    else:
        # Якщо це callback від кнопки
        await message.answer(f"✅ <b>Чек відправлено адміністратору!</b> (№{new_count})", reply_markup=get_main_reply_kb(), parse_mode="HTML")
    
    await state.set_state(None)

@dp.message(Registration.waiting_for_receipt, F.text)
async def error_receipt_format(message: types.Message):
    await message.answer("Будь ласка, відправте саме <b>ФОТО</b> чека 📸", parse_mode="HTML")

# --- WEBHOOK ДЛЯ VERCEL ---
@app.get("/")
async def health_check(): return {"status": "ok"}

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    try:
        update = types.Update(**await request.json())
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error: {e}")
        return {"status": "error"}
