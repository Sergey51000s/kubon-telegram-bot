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
AMO_SUBDOMAIN = "demon51000"
AMO_TOKEN = os.getenv("AMO_ACCESS_TOKEN")

AMO_PIPELINE_ID = 10684430
AMO_STATUS_ID = 10684431  # "Заявка" — подправь после теста, если не туда

if not TELEGRAM_TOKEN or not AMO_TOKEN:
    print("КРИТИЧЕСКАЯ ОШИБКА: Не все переменные найдены!")
    sys.exit(1)

AMO_API_BASE = f"https://{AMO_SUBDOMAIN}.amocrm.ru/api/v4"

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Registration(StatesGroup):
    fio = State()
    inn = State()
    phone = State()
    filial_info = State()  # город + улица + номер здания одним сообщением

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


def normalize_phone(raw: str) -> str:
    digits = re.sub(r'[^0-9+]', '', raw.strip())
    if digits.startswith('8'):
        digits = '+7' + digits[1:]
    if not digits.startswith('+'):
        digits = '+7' + digits
    return digits


async def get_amo_contact_by_telegram_id(telegram_id: int):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{AMO_API_BASE}/contacts", headers=headers) as resp:
            if resp.status != 200:
                logging.error(f"Amo /contacts ошибка: {resp.status}")
                return None
            data = await resp.json()
            contacts = data.get('_embedded', {}).get('contacts', [])
            for contact in contacts:
                notes = contact.get('notes', [])
                for note in notes:
                    if note.get('note_type') == 'common' and f"Telegram ID: {telegram_id}" in note.get('text', ''):
                        return contact
            return None


async def create_amo_contact(fio: str, inn: str, phone: str, telegram_id: int, filial_info: str):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}", "Content-Type": "application/json"}
    payload = [{
        "name": fio,
        "custom_fields_values": [
            {"field_code": "PHONE", "values": [{"value": phone, "enum_code": "WORK"}]},
        ]
    }]

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{AMO_API_BASE}/contacts", json=payload, headers=headers) as resp:
            if resp.status in (200, 201):
                data = await resp.json()
                contact_id = data['_embedded']['contacts'][0]['id']
                note_text = f"Telegram ID: {telegram_id}\nИНН: {inn}\nФилиал: {filial_info}"
                await add_note_to_contact(contact_id, note_text)
                return contact_id
            else:
                text = await resp.text()
                logging.error(f"Amo создание контакта ошибка: {resp.status} - {text}")
                return None


async def add_note_to_contact(contact_id: int, text: str):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}", "Content-Type": "application/json"}
    payload = [{
        "note_type": "common",
        "params": {"text": text}
    }]

    async with aiohttp.ClientSession() as session:
        url = f"{AMO_API_BASE}/contacts/{contact_id}/notes"
        async with session.post(url, json=payload, headers=headers) as resp:
            if resp.status not in (200, 201):
                logging.error(f"Amo добавление примечания ошибка: {resp.status}")


async def create_amo_lead(contact_id: int, description: str, equipment_info: str):
    headers = {"Authorization": f"Bearer {AMO_TOKEN}", "Content-Type": "application/json"}
    payload = [{
        "name": "Заявка из Telegram-бота",
        "pipeline_id": AMO_PIPELINE_ID,
        "status_id": AMO_STATUS_ID,
        "contacts": [{"id": contact_id}],
        "custom_fields_values": [
            {"field_code": "DESCRIPTION", "values": [{"value": description}]},
            {"field_code": "SERIAL_NUMBER", "values": [{"value": equipment_info}]}
        ]
    }]

    async with aiohttp.ClientSession() as session:
        async with session.post(f"{AMO_API_BASE}/leads", json=payload, headers=headers) as resp:
            if resp.status in (200, 201):
                data = await resp.json()
                lead_id = data['_embedded']['leads'][0]['id']
                logging.info(f"Создана сделка: {lead_id}")
                return lead_id
            else:
                text = await resp.text()
                logging.error(f"Amo создание сделки ошибка: {resp.status} - {text}")
                return None


async def upload_file_to_amo_lead(lead_id: int, file_bytes: bytes, filename: str):
    form = aiohttp.FormData()
    form.add_field("file", file_bytes, filename=filename, content_type="image/jpeg")

    headers = {"Authorization": f"Bearer {AMO_TOKEN}"}

    async with aiohttp.ClientSession() as session:
        url = f"{AMO_API_BASE}/leads/{lead_id}/files"
        async with session.post(url, data=form, headers=headers) as resp:
            text = await resp.text()
            logging.info(f"Amo загрузка файла: {resp.status} - {text}")
            return resp.status in (200, 201)


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


@dp.message(Registration.fio)
async def reg_fio(message: Message, state: FSMContext):
    await state.update_data(fio=message.text)
    await message.answer("Введите ИНН:")
    await state.set_state(Registration.inn)


@dp.message(Registration.inn)
async def reg_inn(message: Message, state: FSMContext):
    await state.update_data(inn=message.text)
    await message.answer("Введите номер телефона:")
    await state.set_state(Registration.phone)


@dp.message(Registration.phone)
async def reg_phone(message: Message, state: FSMContext):
    phone = normalize_phone(message.text)
    await state.update_data(phone=phone)
    await message.answer("Введите информацию о филиале (название, город, улица, номер здания):")
    await state.set_state(Registration.filial_info)


@dp.message(Registration.filial_info)
async def reg_filial_info(message: Message, state: FSMContext):
    data = await state.get_data()
    telegram_id = message.from_user.id
    filial_info = message.text
    contact_id = await create_amo_contact(data['fio'], data['inn'], data['phone'], telegram_id, filial_info)
    if contact_id:
        await message.answer("Регистрация завершена! Теперь вы авторизованы.")
        await message.answer("Какой у вас вопрос?", reply_markup=main_menu_kb)
        await state.update_data(contact={"id": contact_id})
        await state.set_state(Form.menu)
    else:
        await message.answer("Ошибка регистрации. Попробуйте заново /start")


@dp.message(Form.menu, F.text == "Обслуживание")
async def process_service(message: Message, state: FSMContext):
    await message.answer("Введите серийный номер вашего робота:", reply_markup=back_kb)
    await state.set_state(Form.serial_input)


# ... (добавь process_serial, issue_description, attach — как в твоём старом коде, только с create_amo_lead и upload_file_to_amo_lead)


async def main():
    print("KubonSupportBot запущен (aiogram 3.x + AmoCRM)")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
