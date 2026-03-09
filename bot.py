import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Text
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import aiohttp

# === Настройки ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
OKDESK_API_TOKEN = "80ce0681fc84a44a7ca11450b24587b9fa367fa8"
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

async def get_contact_by_phone(phone: str):
    params = {"api_token": OKDESK_API_TOKEN, "phone": phone}
    async with aiohttp.ClientSession() as session:
        logging.info(f"Запрос по телефону: {phone}")
        async with session.get(f"{OKDESK_API_BASE}/contacts", params=params) as resp:
            logging.info(f"Статус: {resp.status}")
            text = await resp.text()
            logging.info(f"Сырой ответ контакта: {text}")

            if resp.status != 200:
                return None

            try:
                data = await resp.json()

                # Обрабатываем оба варианта: массив или одиночный объект
                if isinstance(data, list):
                    contacts = data
                elif isinstance(data, dict):
                    contacts = data.get("contacts", [])
                    if not contacts and "id" in data:
                        contacts = [data]
                else:
                    contacts = []

                logging.info(f"Найдено контактов: {len(contacts)}")
                if not contacts:
                    return None

                return contacts[0]
            except Exception as e:
                logging.error(f"Ошибка парсинга контакта: {e}")
                return None

async def get_objects_by_company(company_id: int):
    params = {"api_token": OKDESK_API_TOKEN, "company_id": company_id}
    async with aiohttp.ClientSession() as session:
        logging.info(f"Запрос объектов компании {company_id}")
        async with session.get(f"{OKDESK_API_BASE}/maintenance_entities", params=params) as resp:
            logging.info(f"Статус: {resp.status}")
            text = await resp.text()
            logging.info(f"Сырой ответ объектов: {text}")

            if resp.status != 200:
                logging.error(text)
                return []

            try:
                data = await resp.json()

                # OKDesk возвращает список напрямую — берём его
                if isinstance(data, list):
                    objects = data
                elif isinstance(data, dict):
                    objects = data.get("maintenance_entities", []) or []
                else:
                    objects = []

                logging.info(f"Найдено объектов: {len(objects)}")
                return objects
            except Exception as e:
                logging.error(f"Ошибка парсинга объектов: {e}")
                return []

@dp.message(CommandStart())
@dp.message(lambda message: message.text == "СТАРТ")
async def cmd_start(message: Message, state: FSMContext):
    logging.info(f"СТАРТ от {message.from_user.id}")
    await state.clear()
    await message.answer("Здравствуйте! Укажите ваш номер телефона (+7...):", reply_markup=start_kb)
    await state.set_state(Form.phone)

@dp.message(Form.phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    logging.info(f"Телефон введён: {phone}")
    await state.update_data(phone=phone)

    contact = await get_contact_by_phone(phone)

    if not contact:
        await message.answer("Клиент с таким телефоном не найден. Обратитесь к менеджеру.", reply_markup=start_kb)
        await state.clear()
        return

    fio = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip() or "клиент"

    await message.answer(
        f"Здравствуйте, {fio}!\n\n"
        f"Какой у вас вопрос?",
        reply_markup=main_menu_kb
    )

    await state.update_data(contact=contact)
    await state.set_state(Form.menu)

@dp.message(Form.menu, Text("Обслуживание"))
async def process_service(message: Message, state: FSMContext):
    data = await state.get_data()
    contact = data.get("contact")
    company_id = contact.get("company_id")

    if not company_id:
        await message.answer("Карточка не привязана к компании.", reply_markup=main_menu_kb)
        return

    objects = await get_objects_by_company(company_id)

    if not objects:
        await message.answer("У вас пока нет зарегистрированных объектов обслуживания.", reply_markup=main_menu_kb)
        return

    # Клавиатура с отдельными кнопками для каждого робота
    service_kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=False, row_width=1)
    for obj in objects:
        name = obj.get('name', 'Без названия') if isinstance(obj, dict) else "Без названия"
        serial = obj.get('serial_number', 'не указан') if isinstance(obj, dict) else "не указан"
        button_text = f"{name} (№ {serial})"
        service_kb.add(KeyboardButton(text=button_text))

    service_kb.add(KeyboardButton(text="Назад в меню"))

    await message.answer("Выберите робот:", reply_markup=service_kb)

@dp.message(Form.menu, Text("Срок действия подписки"))
async def process_subscription(message: Message, state: FSMContext):
    await message.answer("Срок действия подписки: пока не реализован. Скоро добавим!", reply_markup=main_menu_kb)

@dp.message(Form.menu, Text("Назад в меню"))
async def back_to_menu(message: Message, state: FSMContext):
    await message.answer("Главное меню:", reply_markup=main_menu_kb)

@dp.message(Form.menu)
async def unknown_menu(message: Message, state: FSMContext):
    await message.answer("Выберите действие из меню:", reply_markup=main_menu_kb)

async def main():
    print("Бот запущен! Используем polling.")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
