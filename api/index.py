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
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
)
from redis.asyncio import Redis

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
REDIS_URL = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")
GOOGLE_WEBHOOK_URL = os.environ.get("GOOGLE_WEBHOOK_URL") 
ADMIN_ID = "-1003731208847" 
SUPPORT_TOPIC_ID = None  # <-- ВПИШИ СЮДА ID ТЕМЫ ДЛЯ ТЕХПОДДЕРЖКИ (например: 45)
RECEIPTS_TOPIC_ID = None # <-- ВПИШИ СЮДА ID ТЕМЫ ДЛЯ ЧЕКОВ (например: 56)
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
    waiting_for_message = State()

# --- КЛАВІАТУРИ ---
def get_inline_start_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧾 Зареєструвати чек", callback_data="upload_receipt")
            ],
            [
                InlineKeyboardButton(text="🎁 Умови розіграшу та призи", callback_data="show_info")
            ],
            [
                InlineKeyboardButton(text="👤 Мої чеки", callback_data="my_cabinet"),
                InlineKeyboardButton(text="💬 Техпідтримка", callback_data="support_btn")
            ],
            [
                InlineKeyboardButton(text="🌐 Instagram - SAMA", url=INSTAGRAM_LINK_1)
            ],
            [
                InlineKeyboardButton(text="🌐 Instagram - koshik_shop", url=INSTAGRAM_LINK_2)
            ]
        ]
    )

def get_back_to_main_inline_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В головне меню", callback_data="back_to_main")]])

def get_inline_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="back_action")]])

def get_inline_back_cancel_kb():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="back_action"),
                InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_action")
            ]
        ]
    )

def get_inline_cancel_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Скасувати", callback_data="cancel_action")]])

def get_phone_reply_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Поділитися номером", request_contact=True)], [KeyboardButton(text="⬅️ Назад")]], resize_keyboard=True, one_time_keyboard=True)

# --- ЛОГИКА МЕНЮ ---
async def show_main_menu(target_message: types.Message, state: FSMContext):
    await state.set_state(None)
    welcome_text = (
        "👋 <b>Вітаємо у нашому святковому розіграші!</b> 🎉\n\n"
        "Тут ви можете реєструвати чеки за покупку нашої продукції та вигравати призи! 🎁\n\n"
        "Оберіть потрібний розділ нижче 👇"
    )
    try:
        await target_message.edit_text(welcome_text, reply_markup=get_inline_start_kb(), parse_mode="HTML")
    except:
        await target_message.answer(welcome_text, reply_markup=get_inline_start_kb(), parse_mode="HTML")

# --- КОМАНДЫ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.set_state(None)
    await message.answer("🔄 Завантаження меню...", reply_markup=ReplyKeyboardRemove())
    await show_main_menu(message, state)

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if str(message.chat.id) != ADMIN_ID: return 
    users = len(await redis.keys("user:*"))
    receipts = await redis.scard("used_receipts") 
    await message.answer(f"📊 Статистика: {users} уч., {receipts} чек.")

@dp.message(Command("sendall"))
async def cmd_sendall(message: types.Message):
    if str(message.chat.id) != ADMIN_ID: return 
    text = message.text.replace("/sendall", "").strip()
    if not text: return
    keys = await redis.keys("user:*")
    for key in keys:
        try: await bot.send_message(chat_id=int(key.decode('utf-8').split(":")[1]), text=text, parse_mode="HTML")
        except: pass
    await message.answer("✅ Розсилку завершено.")

# --- ПОДДЕРЖКА (ОТВЕТ АДМИНА) ---
@dp.message(F.chat.id == int(ADMIN_ID), F.reply_to_message)
async def admin_reply(message: types.Message):
    orig = message.reply_to_message
    if orig.from_user.id != bot.id: return
    match = re.search(r"ID:\s*(\d+)", orig.text or orig.caption or "")
    if match:
        try:
            await message.copy_to(int(match.group(1)))
            msg = await message.reply("✅ Доставлено!")
            await asyncio.sleep(2); await msg.delete()
        except: await message.reply("⚠️ Помилка.")

# --- НАВИГАЦИЯ ---
@dp.callback_query(F.data == "back_to_main")
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await call.answer(); await show_main_menu(call.message, state)

@dp.callback_query(F.data == "support_btn")
async def support_init(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.edit_text("💬 <b>Служба підтримки</b>\n\nОпишіть проблему. Наш менеджер відповість прямо тут:", reply_markup=get_inline_back_kb(), parse_mode="HTML")
    await state.set_state(Support.waiting_for_message)

@dp.callback_query(F.data == "my_cabinet")
async def cabinet_init(call: CallbackQuery):
    await call.answer()
    u = await redis.hgetall(f"user:{call.from_user.id}")
    if not u:
        await call.message.edit_text("🤷‍♂️ Ви ще не зареєстровані.\nНатисніть «🧾 Зареєструвати чек».", reply_markup=get_back_to_main_inline_kb())
        return
    cnt = u.get(b'receipts', b'0').decode()
    h = await redis.lrange(f"user_receipts:{call.from_user.id}", 0, 5)
    hist = "\n".join([f"🔹 {i.decode().split('|')[0]} - №{i.decode().split('|')[1]}" for i in h]) or "Порожньо"
    text = f"👤 <b>Мої чеки:</b>\n\nПІБ: {u.get(b'fio',b'').decode()}\nТел: {u.get(b'phone',b'').decode()}\nЧеки: {cnt}\n\n📋 Останні:\n{hist}"
    await call.message.edit_text(text, parse_mode="HTML", reply_markup=get_back_to_main_inline_kb())

@dp.callback_query(F.data == "upload_receipt")
async def upload_init(call: CallbackQuery, state: FSMContext):
    await call.answer()
    u = await redis.hgetall(f"user:{call.from_user.id}")
    if not u or b'ig' not in u:
        await call.message.edit_text("📝 Введіть ПІБ:", reply_markup=get_inline_back_kb())
        await state.set_state(Registration.waiting_for_fio)
    else:
        await call.message.edit_text("🧾 Введіть НОМЕР чека:", reply_markup=get_inline_back_kb())
        await state.set_state(Registration.waiting_for_receipt_number)

@dp.callback_query(F.data == "show_info")
async def info_init(call: CallbackQuery):
    await call.answer()
    info_text = (
        "📜 <b>Як взяти участь:</b>\n"
        "1️⃣ Підписатися на наші 2 сторінки в Instagram.\n"
        "2️⃣ Купити нашу акційну продукцію.\n"
        "3️⃣ Натиснути «Зареєструвати чек» та надіслати його фото.\n\n"
        "🏆 <b>Що можна виграти?</b>\n"
        "• Головний приз: <b>[Вкажи головний приз]</b>\n"
        "• Щотижневі призи: <b>[Вкажи інші призи]</b>\n\n"
        "📅 <b>Коли відбудеться розіграш?</b>\n"
        "Розіграш пройде <b>[Вкажи дату]</b> у прямому ефірі в Instagram.\n\n"
        "❓ <b>Важливо знати:</b>\n"
        "• Кількість чеків від одного учасника <b>необмежена</b>! Більше унікальних чеків — більше шансів на перемогу.\n"
        "• <b>ОБОВ'ЯЗКОВО</b> зберігайте паперовий оригінал чека до кінця розіграшу. Без нього отримати приз буде неможливо!"
    )
    await call.message.edit_text(info_text, parse_mode="HTML", reply_markup=get_back_to_main_inline_kb())

@dp.callback_query(F.data == "back_action")
async def back_logic(call: CallbackQuery, state: FSMContext):
    await call.answer()
    s = await state.get_state()
    if s in [Registration.waiting_for_receipt_photo.state, Registration.waiting_for_ig.state, Registration.waiting_for_subscription.state]:
        await state.set_state(Registration.waiting_for_receipt_number)
        await call.message.edit_text("🧾 Введіть НОМЕР чека:", reply_markup=get_inline_back_kb())
    else: await show_main_menu(call.message, state)

@dp.callback_query(F.data == "cancel_action")
async def cancel_action_call(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await call.message.delete()
    await show_main_menu(call.message, state)

# --- ВОРОНКИ (ЧАТ) ---
@dp.message(Support.waiting_for_message)
async def sup_msg(message: types.Message):
    u = await redis.hgetall(f"user:{message.from_user.id}")
    fio = u.get(b'fio', b'Гість').decode() if u else "Гість"
    head = f"🆘 <b>ПІДТРИМКА</b>\nВід: {fio} (ID:{message.from_user.id})\n\n"
    args = {"chat_id": ADMIN_ID, "parse_mode": "HTML", "message_thread_id": SUPPORT_TOPIC_ID}
    try:
        if message.text: await bot.send_message(text=head + message.html_text, **args)
        elif message.photo: await bot.send_photo(photo=message.photo[-1].file_id, caption=head + (message.caption or ""), **args)
        await message.answer("✅ Надіслано! Можете писати ще.", reply_markup=get_back_to_main_inline_kb())
    except: pass

@dp.message(Registration.waiting_for_fio)
async def reg_fio(message: types.Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await message.answer("📱 Поділіться номером або введіть вручну:", reply_markup=get_phone_reply_kb())
    await state.set_state(Registration.waiting_for_phone)

@dp.message(Registration.waiting_for_phone)
async def reg_phone(message: types.Message, state: FSMContext):
    if message.text == "⬅️ Назад":
        await message.answer("📝 Введіть ПІБ:", reply_markup=get_inline_back_kb())
        await state.set_state(Registration.waiting_for_fio); return
    p = message.contact.phone_number if message.contact else message.text
    await state.update_data(phone=p)
    await message.answer("🧾 Введіть НОМЕР чека:", reply_markup=get_inline_back_kb(), reply_markup=ReplyKeyboardRemove())
    await state.set_state(Registration.waiting_for_receipt_number)

@dp.message(Registration.waiting_for_receipt_number)
async def reg_num(message: types.Message, state: FSMContext):
    n = message.text.strip().upper()
    if await redis.sismember("used_receipts", n):
        await message.answer("⚠️ Цей номер вже є."); return
    await state.update_data(receipt_number=n)
    u = await redis.hgetall(f"user:{message.from_user.id}")
    if u and u.get(b'sub_checked') == b'1':
        await message.answer("📸 Надішліть ФОТО чека:", reply_markup=get_inline_back_kb())
        await state.set_state(Registration.waiting_for_receipt_photo)
    else:
        await message.answer("📸 Вкажіть ваш Instagram нікнейм:", reply_markup=get_inline_back_kb())
        await state.set_state(Registration.waiting_for_ig)

@dp.message(Registration.waiting_for_ig)
async def reg_ig(message: types.Message, state: FSMContext):
    d = await state.get_data()
    await redis.hset(f"user:{message.from_user.id}", mapping={"fio":d['fio'], "phone":d['phone'], "ig":message.text, "receipts":0, "sub_checked":0})
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🌐 Instagram - SAMA", url=INSTAGRAM_LINK_1)], [InlineKeyboardButton(text="🔄 Перевірити підписку", callback_data="check_sub_1")]])
    await message.answer("⚠️ Підпишіться на сторінку:", reply_markup=kb)
    await state.set_state(Registration.waiting_for_subscription)

@dp.callback_query(F.data == "check_sub_1")
async def sub_1(call: CallbackQuery, state: FSMContext):
    await call.answer(); await call.message.edit_text("⏳ Перевірка..."); await asyncio.sleep(1)
    await redis.hset(f"user:{call.from_user.id}", "sub_checked", 1)
    await call.message.answer("✅ Готово! Надішліть ФОТО чека:", reply_markup=get_inline_back_kb())
    await state.set_state(Registration.waiting_for_receipt_photo)

@dp.message(Registration.waiting_for_receipt_photo, F.photo)
async def reg_photo(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    d = await state.get_data()
    num = d['receipt_number']
    
    await message.answer(f"✅ Чек №{num} прийнято! Дякуємо! 🍀", reply_markup=get_back_to_main_inline_kb())
    await state.set_state(None)

    await redis.sadd("used_receipts", num)
    now = (datetime.utcnow() + timedelta(hours=2)).strftime("%d.%m %H:%M")
    await redis.rpush(f"user_receipts:{user_id}", f"{now}|{num}")
    await redis.hincrby(f"user:{user_id}", "receipts", 1)
    
    u = await redis.hgetall(f"user:{user_id}")
    g_data = {"fio": u[b'fio'].decode(), "phone": u[b'phone'].decode(), "tg_username": f"@{message.from_user.username}", "ig_username": u[b'ig'].decode(), "receipt_count": u[b'receipts'].decode(), "receipt_number": num}
    
    try:
        async with aiohttp.ClientSession() as s: await s.post(GOOGLE_WEBHOOK_URL, json=g_data)
    except: pass

    akb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Ок", callback_data="approve_hide"), InlineKeyboardButton(text="❌ Відхилити", callback_data=f"reject_{user_id}_{num}")]])
    cap = f"🆕 <b>ЧЕК</b>\n№: {num}\nПІБ: {g_data['fio']}\nТел: {g_data['phone']}\nInst: {g_data['ig_username']}"
    try: await bot.send_photo(chat_id=ADMIN_ID, photo=message.photo[-1].file_id, caption=cap, reply_markup=akb, parse_mode="HTML", message_thread_id=RECEIPTS_TOPIC_ID)
    except: pass

@dp.callback_query(F.data == "approve_hide")
async def adm_ok(call: CallbackQuery):
    await call.message.edit_caption(caption=call.message.caption + "\n\n✅ Перевірено", reply_markup=None)

@dp.callback_query(F.data.startswith("reject_"))
async def adm_no(call: CallbackQuery):
    _, uid, num = call.data.split("_")
    await redis.srem("used_receipts", num)
    await redis.hincrby(f"user:{uid}", "receipts", -1)
    try: await bot.send_message(chat_id=int(uid), text=f"⚠️ Ваш чек №{num} ВІДХИЛЕНО модератором. Завантажте ще раз.")
    except: pass
    await call.message.edit_caption(caption=call.message.caption + "\n\n❌ Відхилено", reply_markup=None)

# --- WEBHOOK ---
@app.get("/")
async def h(): return {"ok": True}

@app.post("/api/webhook")
async def webhook(request: Request):
    try:
        body = await request.body()
        if not body: return {"ok": True}
        update = types.Update(**await request.json())
        await dp.feed_update(bot, update)
        return {"ok": True}
    except: return {"ok": False}
