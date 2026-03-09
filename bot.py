import asyncio
import logging
import os
import sys
import re

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import aiohttp

# === Настройки ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
OKDESK_API_TOKEN = os.getenv("OKDESK_API_TOKEN") or "80ce0681fc84a44a7ca11450b24587b9fa367fa8"
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN") or "teken2027"

if not TELEGRAM_TOKEN or not OKDESK_API_TOKEN or not OKDESK_SUBDOMAIN:
    print("КРИТИЧЕСКАЯ ОШИБКА: Не все переменные найдены!")
    sys.exit(1)

OKDESK_API_BASE = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1"

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Form(StatesGroup):
    phone = State()
    menu = State()
    serial_input = State()     # новый стейт для ввода серийного номера
    issue_description = State() # для описания заявки (если нужно)


# Клавиатуры
start_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="СТАРТ")]],
    resize_keyboard=True,
    one_time_keyboard=False
)

main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Срок действия подписки")],
        [KeyboardButton(text="Обслуживание")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

back_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Назад в меню")]],
    resize_keyboard=True,
    one_time_keyboard=False
)

another_phone_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Ввести другой номер")],
        [KeyboardButton(text="СТАРТ")]
    ],
    resize_keyboard=True
)

confirm_issue_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Создать заявку")],
        [KeyboardButton(text="Назад")]
    ],
    resize_keyboard=True
)


def normalize_phone(raw: str) -> str:
    digits = re.sub(r'[^0-9+]', '', raw.strip())
    if digits.startswith('8'):
        digits = '+7' + digits[1:]
    if not digits.startswith('+'):
        digits = '+7' + digits
    if len(digits) > 12:
        digits = digits[:12]
    return digits


async def get_contact_by_phone(phone: str):
    params = {"api_token": OKDESK_API_TOKEN, "phone": phone}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/contacts", params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if isinstance(data, list) and data:
                return data[0]
            elif isinstance(data, dict) and "id" in data:
                return data
            return None


async def search_equipment_by_serial(serial: str):
    params = {"api_token": OKDESK_API_TOKEN, "serial_number": serial}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/equipments", params=params) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            if isinstance(data, dict) and "id" in data:
                return data
            return None


async def create_issue(company_id: int, equipment_id: int, description: str):
    payload = {
        "api_token": OKDESK_API_TOKEN,
        "issue": {
            "company_id": company_id,
            "maintenance_entity_id": None,  # если нужно — добавь
            "equipment_id": equipment_id,
            "kind_id": 1,  # ID типа заявки — узнай в справочнике OkDesk
            "priority_id": 1,  # ID приоритета
            "title": "Заявка из Telegram-бота",
            "content": description,
            "channel_id": 1  # канал — уточни
        }
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{OKDESK_API_BASE}/issues", json=payload) as resp:
            if resp.status in (200, 201):
                data = await resp.json()
                return data.get("id")  # номер созданной заявки
            else:
                text = await resp.text()
                logging.error(f"Ошибка создания заявки: {resp.status} - {text}")
                return None


@dp.message(CommandStart())
@dp.message(F.text == "СТАРТ")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Здравствуйте!\nУкажите ваш номер телефона в формате +7...",
        reply_markup=start_kb
    )
    await state.set_state(Form.phone)


@dp.message(Form.phone)
async def process_phone(message: Message, state: FSMContext):
    phone = normalize_phone(message.text.strip())
    contact = await get_contact_by_phone(phone)

    if not contact:
        await message.answer("Клиент не найден. Попробуйте другой номер.", reply_markup=another_phone_kb)
        return

    fio = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip() or "Клиент"
    await message.answer(
        f"Здравствуйте, <b>{fio}</b>!\n\nКакой у вас вопрос?",
        reply_markup=main_menu_kb
    )
    await state.update_data(contact=contact)
    await state.set_state(Form.menu)


@dp.message(Form.menu, F.text == "Обслуживание")
async def process_service(message: Message, state: FSMContext):
    await message.answer(
        "Введите серийный номер (или инвентарный) вашего робота / оборудования:",
        reply_markup=back_kb
    )
    await state.set_state(Form.serial_input)


@dp.message(Form.serial_input, F.text == "Назад")
async def cancel_serial(message: Message, state: FSMContext):
    await message.answer("Главное меню:", reply_markup=main_menu_kb)
    await state.set_state(Form.menu)


@dp.message(Form.serial_input)
async def process_serial(message: Message, state: FSMContext):
    serial = message.text.strip()
    if not serial:
        await message.answer("Введите номер, пожалуйста.")
        return

    data = await state.get_data()
    contact = data.get("contact", {})
    company_id = contact.get("company_id")

    equipment = await search_equipment_by_serial(serial)

    if not equipment:
        await message.answer(
            f"Оборудование с номером {serial} не найдено.\nПопробуйте другой номер или обратитесь к менеджеру.",
            reply_markup=main_menu_kb
        )
        await state.set_state(Form.menu)
        return

    # Показываем информацию
    kind = equipment.get("equipment_kind", {}).get("name", "Не указан")
    model = equipment.get("equipment_model", {}).get("name", "")
    serial_found = equipment.get("serial_number", "не указан")
    info_text = f"<b>Найдено оборудование:</b>\nВид: {kind}\nМодель: {model}\nСерийный №: {serial_found}"

    await message.answer(info_text, reply_markup=confirm_issue_kb)
    await state.update_data(equipment=equipment)
    await state.set_state(Form.issue_description)


@dp.message(Form.issue_description, F.text == "Создать заявку")
async def create_new_issue(message: Message, state: FSMContext):
    data = await state.get_data()
    contact = data.get("contact", {})
    equipment = data.get("equipment", {})

    company_id = contact.get("company_id")
    equipment_id = equipment.get("id")

    if not company_id or not equipment_id:
        await message.answer("Ошибка данных. Попробуйте заново.", reply_markup=main_menu_kb)
        await state.set_state(Form.menu)
        return

    # Здесь можно запросить описание проблемы
    await message.answer("Опишите проблему кратко (или напишите 'Срочная поломка'):")
    await state.set_state(Form.issue_description)  # пока оставим тот же стейт


@dp.message(Form.issue_description)
async def process_issue_description(message: Message, state: FSMContext):
    description = message.text.strip()
    if not description:
        await message.answer("Опишите проблему, пожалуйста.")
        return

    data = await state.get_data()
    contact = data.get("contact", {})
    equipment = data.get("equipment", {})

    company_id = contact.get("company_id")
    equipment_id = equipment.get("id")

    issue_id = await create_issue(company_id, equipment_id, description)

    if issue_id:
        await message.answer(
            f"Заявка создана успешно!\nНомер заявки: {issue_id}\nСпасибо за обращение.",
            reply_markup=main_menu_kb
        )
    else:
        await message.answer("Не удалось создать заявку. Обратитесь к менеджеру.", reply_markup=main_menu_kb)

    await state.set_state(Form.menu)


# Остальные хендлеры (Срок подписки, назад и т.д.) — без изменений


async def main():
    print("KubonSupportBot запущен (aiogram 3.x + OKDesk)")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
