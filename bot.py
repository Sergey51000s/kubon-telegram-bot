import asyncio
import logging
import os
import sys
import re
import io

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ContentType
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import aiohttp

# ==================== НАСТРОЙКИ ====================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
AMO_SUBDOMAIN = os.getenv("AMO_SUBDOMAIN") or "demon51000"
AMO_TOKEN = os.getenv("AMO_ACCESS_TOKEN")

AMO_PIPELINE_ID = 10684430  # твоя воронка "ТЕХОБСЛУЖИВАНИЕ"
AMO_STATUS_ID = 10684431    # "Заявка" (подправь, если не то)

AMO_API_BASE = f"https://{AMO_SUBDOMAIN}.amocrm.ru/api/v4"

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Registration(StatesGroup):
    fio = State()
    inn = State()
    phone = State()
    filial_name = State()
    filial_city = State()
    filial_street = State()
    filial_building = State()
    kkt_number = State()

class Form(StatesGroup):
    menu = State()
    serial_input = State()
    issue_description = State()
    ask_attach = State()
    wait_attach = State()


# Клавиатуры
start_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="СТАРТ", request_contact=True)]], resize_keyboard=True)
main_menu_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Обслуживание")]], resize_keyboard=True)
back_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Назад в меню")]], resize_keyboard=True)
confirm_issue_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Создать заявку")], [KeyboardButton(text="Назад в меню")]], resize_keyboard=True)
attach_choice_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Да, прикрепить фото/видео")], [KeyboardButton(text="Нет, создать заявку без файлов")]], resize_keyboard=True)
done_kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Готово, отправить заявку")]], resize_keyboard=True)


async def get_amo_contact_by_telegram_id(telegram_id: int):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}
    params = {"query": str(telegram_id)}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{AMO_API_BASE}/contacts", headers=headers, params=params) as resp:
            if resp.status != 200:
                logging.error(f"Amo /contacts ошибка: {resp.status} - {await resp.text()}")
                return None
            data = await resp.json()
            contacts = data.get('_embedded', {}).get('contacts', [])
            if contacts:
                return contacts[0]
            return None


async def create_amo_contact(fio: str, inn: str, phone: str, telegram_id: int, filial_info: str):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}", "Content-Type": "application/json"}
    payload = [{
        "name": fio,
        "custom_fields_values": [
            {"field_code": "INN", "values": [{"value": inn}]},
            {"field_code": "PHONE", "values": [{"value": phone, "enum_code": "WORK"}]},
            {"field_code": "TELEGRAM_ID", "values": [{"value": str(telegram_id)}]},
            {"field_code": "FILIAL_INFO", "values": [{"value": filial_info}]}
        ]
    }]

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{AMO_API_BASE}/contacts", json=payload, headers=headers) as resp:
            if resp.status in (200, 201):
                data = await resp.json()
                contact_id = data['_embedded']['contacts'][0]['id']
                logging.info(f"Создан контакт: {contact_id}")
                return contact_id
            else:
                text = await resp.text()
                logging.error(f"Amo создание контакта ошибка: {resp.status} - {text}")
                return None


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    telegram_id = message.from_user.id
    contact = await get_amo_contact_by_telegram_id(telegram_id)
    if contact:
        fio = contact.get('name', 'Клиент')
        await message.answer(f"Здравствуйте, <b>{fio}</b>!\n\nКакой у вас вопрос?", reply_markup=main_menu_kb)
        await state.update_data(contact=contact)
        await state.set_state(Form.menu)
    else:
        await message.answer("Здравствуйте! Для начала зарегистрируйтесь.")
        await message.answer("Введите ФИО:")
        await state.set_state(Registration.fio)


# Хендлеры для регистрации
@dp.message(Registration.fio)
async def reg_fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await message.answer("Введите ИНН:")
    await state.set_state(Registration.inn)

# Аналогично для остальных полей регистрации (inn, phone, filial_name, city, street, building, kkt_number)
# В конце регистрации:
@dp.message(Registration.kkt_number)
async def reg_finish(message: Message, state: FSMContext):
    data = await state.get_data()
    telegram_id = message.from_user.id
    filial_info = f"Название: {data['filial_name']}, Город: {data['filial_city']}, Улица: {data['filial_street']}, Номер: {data['filial_building']}, ККТ: {message.text}"
    contact_id = await create_amo_contact(data['fio'], data['inn'], data['phone'], telegram_id, filial_info)
    if contact_id:
        await message.answer("Регистрация завершена! Теперь вы авторизованы.")
        await message.answer("Какой у вас вопрос?", reply_markup=main_menu_kb)
        await state.update_data(contact={"id": contact_id})
        await state.set_state(Form.menu)
    else:
        await message.answer("Ошибка регистрации. Попробуйте заново /start")

# Остальные хендлеры (menu, serial, description, attach) — оставь как есть, только в create_and_finish_issue используй create_amo_lead

# ... (полный код как раньше, с новыми функциями)
