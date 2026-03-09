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


# ─────────────── Клавиатуры ───────────────
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


# ─────────────── Утилиты ───────────────
def normalize_phone(raw: str) -> str:
    """Приводим телефон к виду +7XXXXXXXXXX"""
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
        logging.info(f"Поиск контакта по телефону: {phone}")
        async with session.get(f"{OKDESK_API_BASE}/contacts", params=params) as resp:
            logging.info(f"Статус /contacts: {resp.status}")
            if resp.status != 200:
                text = await resp.text()
                logging.error(f"Ошибка API /contacts {resp.status}: {text}")
                return None

            try:
                data = await resp.json()
                logging.info(f"Тип ответа /contacts: {type(data).__name__}")

                if isinstance(data, list):
                    return data[0] if data else None
                elif isinstance(data, dict):
                    if "contacts" in data and isinstance(data["contacts"], list):
                        return data["contacts"][0] if data["contacts"] else None
                    if "id" in data:  # одиночный объект
                        return data
                return None
            except Exception as e:
                logging.error(f"Ошибка парсинга контакта: {e}", exc_info=True)
                return None


async def get_equipment_by_company(company_id: int):
    params = {"api_token": OKDESK_API_TOKEN, "company_id": company_id}
    async with aiohttp.ClientSession() as session:
        logging.info(f"Запрос оборудования компании {company_id}")
        async with session.get(f"{OKDESK_API_BASE}/equipments", params=params) as resp:
            logging.info(f"Статус /equipments: {resp.status}")
            if resp.status != 200:
                text = await resp.text()
                logging.error(f"Ошибка {resp.status}: {text}")
                return []

            try:
                data = await resp.json()
                logging.info(f"Тип ответа оборудования: {type(data).__name__}")

                if isinstance(data, list):
                    logging.info(f"Получен список из {len(data)} единиц оборудования")
                    return data

                if isinstance(data, dict):
                    for key in [
                        "equipments",
                        "equipment",
                        "items",
                        "data",
                        "results",
                        "maintenance_entities"  # на случай, если вернётся старый формат
                    ]:
                        if key in data and isinstance(data[key], list):
                            logging.info(f"Найден ключ '{key}' → {len(data[key])}")
                            return data[key]

                logging.warning("Не удалось найти список оборудования в ответе")
                return []

            except Exception as e:
                logging.error(f"Ошибка парсинга оборудования: {e}", exc_info=True)
                return []


# ─────────────── Хендлеры ───────────────
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
    raw_phone = message.text.strip()
    phone = normalize_phone(raw_phone)
    logging.info(f"Нормализованный телефон: {phone} (было: {raw_phone})")

    if not phone.startswith("+7") or len(phone) != 12:
        await message.answer(
            "Пожалуйста, введите номер в формате +7XXXXXXXXXX",
            reply_markup=another_phone_kb
        )
        return

    await state.update_data(phone=phone)

    contact = await get_contact_by_phone(phone)

    if not contact:
        await message.answer(
            "Клиент с таким номером не найден в системе.\n"
            "Попробуйте другой номер или обратитесь к менеджеру.",
            reply_markup=another_phone_kb
        )
        await state.clear()
        return

    first = contact.get("first_name", "").strip()
    last = contact.get("last_name", "").strip()
    fio = f"{first} {last}".strip() or "Клиент"

    await message.answer(
        f"Здравствуйте, <b>{fio}</b>!\n\n"
        f"Какой у вас вопрос?",
        reply_markup=main_menu_kb
    )

    await state.update_data(contact=contact)
    await state.set_state(Form.menu)


@dp.message(Form.menu, F.text == "Обслуживание")
async def process_service(message: Message, state: FSMContext):
    data = await state.get_data()
    contact = data.get("contact", {})

    company_id = contact.get("company_id")
    if not company_id:
        await message.answer(
            "Ваша карточка не привязана к компании.\nОбратитесь к менеджеру.",
            reply_markup=main_menu_kb
        )
        return

    equipments = await get_equipment_by_company(company_id)

    if not equipments:
        await message.answer(
            "У вас пока нет зарегистрированного оборудования / роботов.",
            reply_markup=main_menu_kb
        )
        return

    # Клавиатура с оборудованием
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    for item in equipments:
        name = item.get("name", "Без названия")
        serial = item.get("serial_number", "не указан")
        text = f"{name} (сер. № {serial})"
        kb.add(KeyboardButton(text=text))

    kb.add(KeyboardButton(text="Назад в меню"))

    await message.answer("Выберите оборудование / робота:", reply_markup=kb)


@dp.message(Form.menu, F.text == "Срок действия подписки")
async def process_subscription(message: Message, state: FSMContext):
    await message.answer(
        "Функция «Срок действия подписки» пока в разработке.\n"
        "Скоро появится!",
        reply_markup=main_menu_kb
    )


@dp.message(Form.menu, F.text.in_({"Назад в меню", "В главное меню"}))
async def back_to_main_menu(message: Message, state: FSMContext):
    await message.answer("Главное меню:", reply_markup=main_menu_kb)


@dp.message(Form.menu)
async def unknown_in_menu(message: Message, state: FSMContext):
    await message.answer("Пожалуйста, выберите действие из меню:", reply_markup=main_menu_kb)


@dp.message(F.text == "Ввести другой номер")
async def retry_phone(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Введите новый номер телефона (+7...):",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Form.phone)


async def main():
    print("KubonSupportBot запущен (aiogram 3.x + OKDesk)")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
