import os
import logging
import aiohttp
import asyncio
import re
from datetime import datetime, timedelta
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from redis.asyncio import Redis

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REDIS_URL = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")
GOOGLE_WEBHOOK_URL = os.environ.get("GOOGLE_WEBHOOK_URL") 
ADMIN_ID = "-1003731208847" 
SUPPORT_TOPIC_ID = None # <-- ВПИШИ СЮДА ID ТЕМЫ (например: 45). Если None - будет слать в общую группу
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

class Support(StatesGroup):
    waiting_for_message = State() # Стан для очікування повідомлення в підтримку

# --- КЛАВІАТУРИ ---
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
                InlineKeyboardButton(text="💬 Техпідтримка", callback_data="support_btn")
            ],
            [
                InlineKeyboardButton(text="📸 tm.sama.ua", url=INSTAGRAM_LINK_1),
                InlineKeyboardButton(text="📸 koshik_shop_", url=INSTAGRAM_LINK_2)
            ]
        ]
    )

def get_back_to_main_inline_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 В головне меню", callback_data="back_to_main")]
        ]
    )

def get_inline_cancel_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_action")]]
    )

def get_inline_back_cancel_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_action"),
                InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_action")
            ]
        ]
    )

def get_inline_back_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_action")]]
    )

def get_phone_reply_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Поділитися номером", request_contact=True)],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# --- СПІЛЬНА ЛОГІКА ---
async def show_main_menu(target_message: types.Message, state: FSMContext):
    await state.set_state(None)
    rm_msg = await target_message.answer("🔄 Оновлення...", reply_markup=ReplyKeyboardRemove())
    await rm_msg.delete()
    
    welcome_text = (
        "👋 <b>Вітаємо у нашому святковому розіграші!</b> 🎉\n\n"
        "Тут ви можете реєструвати чеки за покупку нашої продукції та вигравати неймовірні призи! 🎁\n\n"
        "⚠️ <b>Обов'язкова умова:</b> підписка на наші дві Instagram сторінки!\n\n"
        "Оберіть потрібний розділ нижче 👇"
    )
    await target_message.answer(welcome_text, reply_markup=get_inline_start_kb(), parse_mode="HTML")

async def process_show_cabinet(target_message, user_id: int):
    user_data = await redis.hgetall(f"user:{user_id}")
    if not user_data:
        await target_message.answer("🤷‍♂️ Ви ще не зареєстровані.\nНатисніть «🧾 Завантажити чек».", reply_markup=get_back_to_main_inline_kb())
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
            except: pass
    else:
        history_text = "\n\n📋 <b>Історія ваших чеків:</b>\nПоки що порожньо."

    cabinet_text = (
        "👤 <b>Ваш особистий кабінет:</b>\n\n"
        f"🔸 <b>ПІБ:</b> {fio}\n🔸 <b>Телефон:</b> {phone}\n🔸 <b>Instagram:</b> {ig}\n"
        f"🎫 <b>Успішно схвалено чеків:</b> {receipts_count}{history_text}\n\n"
        "Так тримати! Чим більше чеків, тим ближче перемога 🏆"
    )
    await target_message.answer(cabinet_text, parse_mode="HTML", reply_markup=get_back_to_main_inline_kb())

async def process_start_upload(target_message, user_id: int, state: FSMContext):
    user_data = await redis.hgetall(f"user:{user_id}")
    if not user_data or b'ig' not in user_data:
        await target_message.answer("📝 Для початку реєстрації напишіть ваше <b>ПІБ</b>:", reply_markup=get_inline_cancel_kb(), parse_mode="HTML")
        await state.set_state(Registration.waiting_for_fio)
    else:
        await target_message.answer("🧾 <b>Введіть НОМЕР вашого чека:</b>", reply_markup=get_inline_cancel_kb(), parse_mode="HTML")
        await state.set_state(Registration.waiting_for_receipt_number)

async def process_show_rules(target_message):
    rules = "📜 <b>Умови дуже прості:</b>\n\n1️⃣ Підписка на 2 сторінки.\n2️⃣ Купівля акційної продукції.\n3️⃣ Завантаження чека.\n\nБільше чеків — більше шансів!"
    await target_message.answer(rules, parse_mode="HTML", reply_markup=get_back_to_main_inline_kb())

async def process_show_faq(target_message):
    faq_text = "🏆 <b>Призи:</b>\n• Головний приз...\n\n❓ Зберігати чек ОБОВ'ЯЗКОВО."
    await target_message.answer(faq_text, parse_mode="HTML", reply_markup=get_back_to_main_inline_kb())

# --- ОБРОБНИКИ КОМАНД ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await show_main_menu(message, state)

@dp.message(Command("cleardb"))
async def cmd_cleardb(message: types.Message):
    if str(message.chat.id) != ADMIN_ID: return 
    await redis.flushdb()
    await message.answer("🧹 База очищена.")

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if str(message.chat.id) != ADMIN_ID: return 
    users = len(await redis.keys("user:*"))
    receipts = await redis.scard("used_receipts") 
    await message.answer(f"📊 <b>Статистика:</b>\nУчасників: {users}\nЧеків: {receipts}", parse_mode="HTML")

@dp.message(Command("sendall"))
async def cmd_sendall(message: types.Message):
    if str(message.chat.id) != ADMIN_ID: return 
    text = message.text.replace("/sendall", "").strip()
    if not text:
        await message.answer("⚠️ Введіть текст.")
        return
    await message.answer("⏳ Розсилка...")
    keys, success, error = await redis.keys("user:*"), 0, 0
    for key in keys:
        try:
            await bot.send_message(chat_id=int(key.decode('utf-8').split(":")[1]), text=text, parse_mode="HTML")
            success += 1
        except: error += 1
    await message.answer(f"✅ Доставлено: {success}\n🔴 Помилок: {error}")


# --- ЗВОРОТНИЙ ЗВ'ЯЗОК (АДМІН ВІДПОВІДАЄ КОРИСТУВАЧУ) ---
@dp.message(F.chat.id == int(ADMIN_ID), F.reply_to_message)
async def admin_reply_to_support(message: types.Message):
    # Перевіряємо, чи це відповідь на повідомлення від самого бота
    orig = message.reply_to_message
    if orig.from_user.id != bot.id: return
        
    text_to_search = orig.text or orig.caption or ""
    # Шукаємо ID: 12345678 в тексті
    match = re.search(r"ID:\s*(\d+)", text_to_search)
    
    if match:
        target_user_id = int(match.group(1))
        try:
            # Копіюємо відповідь адміна (текст, фото, відео) клієнту
            await message.copy_to(target_user_id)
            # Відправляємо адміну підтвердження (можна видалити, якщо дратує)
            reply_msg = await message.reply("✅ Відповідь доставлено!")
            await asyncio.sleep(3)
            await reply_msg.delete()
        except Exception as e:
            await message.reply(f"⚠️ Помилка відправки. Можливо, клієнт заблокував бота. ({e})")


# --- ОБРОБНИКИ НАВІГАЦІЇ (INLINE) ---
@dp.callback_query(F.data == "support_btn")
async def support_btn_call(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text(
        "💬 <b>Служба підтримки</b>\n\n"
        "Опишіть вашу проблему або запитання в одному повідомленні (можна додати фото).\n"
        "Наш менеджер відповість вам прямо в цьому боті найближчим часом:",
        reply_markup=get_inline_back_kb(),
        parse_mode="HTML"
    )
    await state.set_state(Support.waiting_for_message)

@dp.callback_query(F.data == "cancel_action")
async def cancel_action_call(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.delete()
    await show_main_menu(call.message, state)

@dp.callback_query(F.data == "back_action")
async def back_action_call(call: CallbackQuery, state: FSMContext):
    await call.answer()
    current_state = await state.get_state()
    
    if current_state == Registration.waiting_for_receipt_photo.state:
        await state.set_state(Registration.waiting_for_receipt_number)
        await call.message.edit_text("🧾 <b>Введіть НОМЕР вашого чека:</b>", reply_markup=get_inline_back_cancel_kb(), parse_mode="HTML")
    elif current_state == Registration.waiting_for_ig.state:
        await state.set_state(Registration.waiting_for_receipt_number)
        await call.message.edit_text("🧾 <b>Введіть НОМЕР вашого чека:</b>", reply_markup=get_inline_back_cancel_kb(), parse_mode="HTML")
    elif current_state == Registration.waiting_for_subscription.state:
        await state.set_state(Registration.waiting_for_ig)
        await call.message.edit_text("📸 <b>Введіть ваш нікнейм в Instagram:</b>", reply_markup=get_inline_back_kb(), parse_mode="HTML")
    elif current_state == Registration.waiting_for_receipt_number.state:
        user_data = await redis.hgetall(f"user:{call.from_user.id}")
        if not user_data or b'ig' not in user_data:
            await state.set_state(Registration.waiting_for_phone)
            await call.message.delete()
            await call.message.answer("📱 Натисніть кнопку <b>«📱 Поділитися номером»</b> внизу екрана:", reply_markup=get_phone_reply_kb(), parse_mode="HTML")
        else:
            await call.message.delete()
            await show_main_menu(call.message, state)
    elif current_state == Registration.waiting_for_phone.state:
        await state.set_state(Registration.waiting_for_fio)
        rm_msg = await call.message.answer("🔄...", reply_markup=ReplyKeyboardRemove())
        await rm_msg.delete()
        await call.message.answer("📝 Введіть ваше <b>ПІБ</b>:", reply_markup=get_inline_cancel_kb(), parse_mode="HTML")
    else:
        await call.message.delete()
        await show_main_menu(call.message, state)

@dp.callback_query(F.data == "back_to_main")
async def back_to_main_call(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.delete()
    await show_main_menu(call.message, state)

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


# --- ВОРОНКА ТЕХПІДТРИМКИ ---
@dp.message(Support.waiting_for_message)
async def process_support_msg(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await redis.hgetall(f"user:{user_id}")
    fio = user_data.get(b'fio', b'Не вказано').decode('utf-8') if user_data else "Гість"
    username = f"@{message.from_user.username}" if message.from_user.username else "Без юзернейму"
    
    header = f"🆘 <b>ЗАПИТ У ПІДТРИМКУ</b>\n👤 <b>Від:</b> {fio} ({username})\n🆔 <b>ID:</b> {user_id}\n\n"
    
    kwargs = {"chat_id": ADMIN_ID, "parse_mode": "HTML"}
    if SUPPORT_TOPIC_ID:
        kwargs["message_thread_id"] = int(SUPPORT_TOPIC_ID)
        
    try:
        if message.text:
            await bot.send_message(text=header + message.html_text, **kwargs)
        elif message.photo:
            caption = header + (message.html_text or "")
            await bot.send_photo(photo=message.photo[-1].file_id, caption=caption, **kwargs)
        else:
            await message.answer("⚠️ Будь ласка, надішліть текст або фотографію.", reply_markup=get_inline_back_kb())
            return
            
        await message.answer("✅ <b>Ваш запит успішно надіслано!</b>\nОчікуйте на відповідь.", reply_markup=get_back_to_main_inline_kb(), parse_mode="HTML")
        await state.set_state(None)
    except Exception as e:
        logging.error(f"Support Error: {e}")
        await message.answer(f"⚠️ Виникла технічна помилка.", reply_markup=get_inline_back_kb())


# --- ВОРОНКА РЕЄСТРАЦІЇ ---
@dp.message(Registration.waiting_for_fio)
async def process_fio(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Введіть ПІБ текстом:", reply_markup=get_inline_back_kb())
        return
    await state.update_data(fio=message.text)
    await message.answer("Чудово! Натисніть кнопку <b>«📱 Поділитися номером»</b> внизу екрана:", reply_markup=get_phone_reply_kb(), parse_mode="HTML")
    await state.set_state(Registration.waiting_for_phone)

@dp.message(Registration.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        rm_msg = await message.answer("🔄 Повертаємось...", reply_markup=ReplyKeyboardRemove())
        await rm_msg.delete()
        await message.answer("📝 Введіть ваше <b>ПІБ</b>:", reply_markup=get_inline_cancel_kb(), parse_mode="HTML")
        await state.set_state(Registration.waiting_for_fio)
        return

    phone = message.contact.phone_number if message.contact else message.text
    if not phone:
        await message.answer("⚠️ Надішліть контакт або введіть номер текстом:", reply_markup=get_phone_reply_kb())
        return

    await state.update_data(phone=phone)
    rm_msg = await message.answer("🔄 Зберігаємо...", reply_markup=ReplyKeyboardRemove())
    await rm_msg.delete()
    
    await message.answer("🧾 <b>Введіть НОМЕР вашого чека:</b>", reply_markup=get_inline_back_cancel_kb(), parse_mode="HTML")
    await state.set_state(Registration.waiting_for_receipt_number)

@dp.message(Registration.waiting_for_receipt_number)
async def process_receipt_number(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Введіть номер чека текстом:", reply_markup=get_inline_back_kb())
        return
    receipt_num = message.text.strip().upper() 
    if len(receipt_num) > 30:
        await message.answer("⚠️ Номер занадто довгий.", reply_markup=get_inline_back_kb())
        return

    if await redis.sismember("used_receipts", receipt_num):
        await message.answer("⚠️ Чек з таким номером вже є в системі.", reply_markup=get_inline_back_cancel_kb())
        return 
        
    await state.update_data(receipt_number=receipt_num)
    
    user_id = message.from_user.id
    user_data = await redis.hgetall(f"user:{user_id}")
    is_sub_checked = user_data.get(b'sub_checked', b'0').decode('utf-8') == '1'
    
    if user_data and b'ig' in user_data:
        if is_sub_checked:
            await message.answer("📸 Тепер відправте <b>ФОТО вашого чека</b>:", reply_markup=get_inline_back_cancel_kb(), parse_mode="HTML")
            await state.set_state(Registration.waiting_for_receipt_photo)
        else:
            await send_subscription_step_1(message, state)
    else:
        await message.answer("📸 <b>Введіть ваш нікнейм в Instagram:</b>", reply_markup=get_inline_back_cancel_kb(), parse_mode="HTML")
        await state.set_state(Registration.waiting_for_ig)

@dp.message(Registration.waiting_for_ig)
async def process_ig(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Введіть нікнейм текстом:", reply_markup=get_inline_back_kb())
        return
    
    fsm_data = await state.get_data()
    user_id = message.from_user.id
    await redis.hset(f"user:{user_id}", mapping={"fio": fsm_data.get("fio"), "phone": fsm_data.get("phone"), "ig": message.text, "receipts": 0, "sub_checked": "0"})
    await send_subscription_step_1(message, state)

async def send_subscription_step_1(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Перейти: tm.sama.ua", url=INSTAGRAM_LINK_1)],
        [InlineKeyboardButton(text="🔄 Перевірити підписку 1", callback_data="check_sub_1")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_action")]
    ])
    await message.answer("⚠️ <b>Обов'язкова умова! (Крок 1)</b>\nПідпишіться на нашу першу сторінку.", reply_markup=kb, parse_mode="HTML")
    await state.set_state(Registration.waiting_for_subscription)

@dp.callback_query(Registration.waiting_for_subscription, F.data == "check_sub_1")
async def process_check_sub_1(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("⏳ <i>Перевірка...</i>", parse_mode="HTML")
    await asyncio.sleep(2) 
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Перейти: koshik_shop_", url=INSTAGRAM_LINK_2)],
        [InlineKeyboardButton(text="🔄 Перевірити підписку 2", callback_data="check_sub_2")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_action")]
    ])
    await call.message.edit_text("✅ <b>Перша є! Крок 2:</b>\nПідпишіться на другу сторінку.", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(Registration.waiting_for_subscription, F.data == "check_sub_2")
async def process_check_sub_2(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("⏳ <i>Перевірка...</i>", parse_mode="HTML")
    await asyncio.sleep(2) 
    
    await redis.hset(f"user:{call.from_user.id}", "sub_checked", "1")
    await call.message.edit_text("✅ <b>Всі підписки підтверджено!</b> 🎉", parse_mode="HTML")
    await call.message.answer("📸 Тепер відправте <b>ФОТО вашого чека</b>:", reply_markup=get_inline_back_cancel_kb(), parse_mode="HTML")
    await state.set_state(Registration.waiting_for_receipt_photo)

# --- ПРИЙОМ ФОТО ---
@dp.message(Registration.waiting_for_receipt_photo, F.photo)
async def process_receipt_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    user_data = await redis.hgetall(f"user:{user_id}")
    
    receipt_number_text = (await state.get_data()).get("receipt_number", "Не вказано")
    
    if receipt_number_text != "Не вказано":
        await redis.sadd("used_receipts", receipt_number_text)
        now_str = (datetime.utcnow() + timedelta(hours=2)).strftime("%d.%m.%Y %H:%M")
        await redis.rpush(f"user_receipts:{user_id}", f"{now_str}|{receipt_number_text}")
    
    await redis.hincrby(f"user:{user_id}", "receipts", 1)
    new_count = (await redis.hget(f"user:{user_id}", "receipts")).decode('utf-8')
    
    tg_username = f"@{message.from_user.username}" if message.from_user.username else "Немає"
    await redis.hset(f"user:{user_id}", "tg_username", tg_username)

    rm_msg = await message.answer("🔄 Обробка...", reply_markup=ReplyKeyboardRemove())
    await rm_msg.delete()
    
    await message.answer(f"✅ <b>Чек успішно прийнято!</b>\n\nЦе ваш чек №{new_count}. 🍀", reply_markup=get_back_to_main_inline_kb(), parse_mode="HTML")
    await state.set_state(None)

    if GOOGLE_WEBHOOK_URL:
        google_data = {
            "fio": user_data.get(b'fio', b'').decode('utf-8'),
            "phone": user_data.get(b'phone', b'').decode('utf-8'),
            "tg_username": tg_username,
            "ig_username": user_data.get(b'ig', b'').decode('utf-8'),
            "receipt_count": new_count,
            "receipt_number": receipt_number_text
        }
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(GOOGLE_WEBHOOK_URL, json=google_data)
        except: pass

    admin_caption = (
        f"🆕 <b>Новий чек!</b> (У клієнта: {new_count})\n\n🧾 <b>Номер:</b> {receipt_number_text}\n"
        f"👤 <b>ПІБ:</b> {google_data['fio']}\n📱 <b>Телефон:</b> {google_data['phone']}\n"
        f"📸 <b>Instagram:</b> {google_data['ig_username']}\n💬 <b>Юзернейм:</b> {tg_username}"
    )
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Ок (Сховати)", callback_data="approve_hide"),
         InlineKeyboardButton(text="❌ ВІДХИЛИТИ", callback_data=f"reject_{user_id}_{receipt_number_text}")]
    ])
    
    kwargs = {"chat_id": ADMIN_ID, "parse_mode": "HTML", "reply_markup": admin_kb}
    if SUPPORT_TOPIC_ID: kwargs["message_thread_id"] = int(SUPPORT_TOPIC_ID) # Чеки теж можна слати в загальний топік або залишити без нього
    
    try: await bot.send_photo(photo=message.photo[-1].file_id, caption=admin_caption, **kwargs)
    except: pass

@dp.message(Registration.waiting_for_receipt_photo)
async def error_receipt_format(message: types.Message):
    await message.answer("⚠️ Надішліть саме <b>ФОТО</b>.", parse_mode="HTML", reply_markup=get_inline_back_kb())

# --- МОДЕРАЦІЯ ЧЕКІВ ---
@dp.callback_query(F.data == "approve_hide")
async def admin_approve(call: CallbackQuery):
    caption = call.message.html_text or call.message.caption or "Чек"
    admin_name = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
    await call.message.edit_caption(caption=caption + f"\n\n✅ <b>Перевірено:</b> {admin_name}", parse_mode="HTML", reply_markup=None)

@dp.callback_query(F.data.startswith("reject_"))
async def admin_reject(call: CallbackQuery):
    parts = call.data.split("_")
    user_id, receipt_number = int(parts[1]), parts[2]
    
    await redis.srem("used_receipts", receipt_number)
    items = await redis.lrange(f"user_receipts:{user_id}", 0, -1)
    for item in items:
        if item.decode('utf-8').endswith(f"|{receipt_number}"):
            await redis.lrem(f"user_receipts:{user_id}", 1, item)
            break
            
    await redis.hincrby(f"user:{user_id}", "receipts", -1)
    try: await bot.send_message(chat_id=user_id, text=f"⚠️ Ваш чек №{receipt_number} <b>ВІДХИЛЕНО</b> модератором.", parse_mode="HTML", reply_markup=get_back_to_main_inline_kb())
    except: pass
        
    caption = call.message.html_text or call.message.caption or "Чек"
    admin_name = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
    await call.message.edit_caption(caption=caption + f"\n\n❌ <b>ВІДХИЛЕНО:</b> {admin_name}", parse_mode="HTML", reply_markup=None)

# --- WEBHOOK ---
@app.get("/")
async def health_check(): return {"status": "ok"}

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    try:
        await dp.feed_update(bot, types.Update(**await request.json()))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error"}
