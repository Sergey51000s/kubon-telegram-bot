import asyncio
import logging
import os
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import aiohttp

# === Настройки ===
TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN") or
    os.getenv("TELEGRAM_BOT_TOKEN") or
    os.getenv("BOT_TOKEN") or
    os.getenv("TOKEN")
)

OKDESK_API_TOKEN = os.getenv("OKDESK_API_TOKEN")
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN")

if not TELEGRAM_TOKEN or not OKDESK_API_TOKEN or not OKDESK_SUBDOMAIN:
    print("КРИТИЧЕСКАЯ ОШИБКА: Не все переменные OKDesk/Telegram найдены в окружении!")
    sys.exit(1)

OKDESK_API_BASE = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1"

bot = Bot(token=TELEGRAM_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Form(StatesGroup):
    select_object = State()   # Выбор объекта обслуживания
    problem = State()         # Описание проблемы

# Кнопка СТАРТ — всегда видна
start_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="СТАРТ")]],
    resize_keyboard=True,
    one_time_keyboard=False
)

async def get_contact_by_username(username: str):
    """Поиск контакта по полю telegram_username (без @)"""
    params = {"api_token": OKDESK_API_TOKEN, "telegram_username": username}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/contacts", params=params) as resp:
            print(f"Запрос к /contacts: статус {resp.status}, params={params}")
            if resp.status != 200:
                text = await resp.text()
                print(f"Ответ сервера: {text}")
                return None
            data = await resp.json()
            contacts = data.get("contacts", [])
            print(f"Найдено контактов: {len(contacts)}")
            if not contacts:
                return None
            return contacts[0]

async def get_objects_by_company(company_id: int):
    """Получить все объекты обслуживания компании"""
    params = {"api_token": OKDESK_API_TOKEN, "company_id": company_id}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/maintenance_entities", params=params) as resp:
            print(f"Запрос к /maintenance_entities: статус {resp.status}")
            if resp.status != 200:
                print(f"Ошибка: {await resp.text()}")
                return []
            data = await resp.json()
            objects = data.get("maintenance_entities", [])
            print(f"Найдено объектов: {len(objects)}")
            return objects

@dp.message(CommandStart())
@dp.message(lambda message: message.text == "СТАРТ")
async def cmd_start(message: Message, state: FSMContext):
    username = message.from_user.username
    user_id = message.from_user.id

    if not username:
        await message.answer(
            "У вас не установлен @username в Telegram.\n"
            "Установите его в настройках профиля и попробуйте снова.",
            reply_markup=start_kb
        )
        return

    print(f"СТАРТ от @{username} (ID: {user_id})")

    await state.clear()
    await message.answer("Пожалуйста, подождите...", reply_markup=start_kb)

    contact = await get_contact_by_username(username)

    if not contact:
        await message.answer(
            f"Здравствуйте!\n\n"
            f"Ваш Telegram-аккаунт @{username} не найден в нашей базе клиентов.\n"
            "Пожалуйста, обратитесь к вашему менеджеру для регистрации.",
            reply_markup=start_kb
        )
        return

    fio = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip() or "клиент"
    company_id = contact.get("company_id")

    if not company_id:
        await message.answer(
            f"Здравствуйте, {fio}!\n"
            "Ваша карточка не привязана к компании. Обратитесь к менеджеру.",
            reply_markup=start_kb
        )
        return

    objects = await get_objects_by_company(company_id)

    if not objects:
        await message.answer(
            f"Здравствуйте, {fio}!\n"
            "У вас пока нет зарегистрированных объектов обслуживания.",
            reply_markup=start_kb
        )
        return

    # Формируем список объектов
    object_list = "\n".join(
        f"{i+1}. {obj.get('name', 'Без названия')} (№ {obj.get('serial_number', 'не указан')})"
        for i, obj in enumerate(objects)
    )

    await message.answer(
        f"Здравствуйте, {fio}!\n\n"
        f"Пожалуйста, выберите объект, с которым возникла проблема:\n\n"
        f"{object_list}\n\n"
        "Напишите номер (1, 2, 3...)",
        reply_markup=start_kb
    )

    await state.update_data(contact=contact, objects=objects)
    await state.set_state(Form.select_object)

@dp.message(Form.select_object)
async def process_object_selection(message: Message, state: FSMContext):
    text = message.text.strip()
    try:
        num = int(text) - 1
        data = await state.get_data()
        objects = data.get("objects", [])
        if 0 <= num < len(objects):
            selected = objects[num]
            await state.update_data(selected_object=selected)
            await message.answer(
                f"Вы выбрали: {selected.get('name', 'Без названия')} (№ {selected.get('serial_number', 'не указан')})\n\n"
                "Опишите проблему:"
            )
            await state.set_state(Form.problem)
            return
    except:
        pass

    await message.answer("Пожалуйста, введите номер из списка (1, 2, 3...)")

@dp.message(Form.problem)
async def process_problem(message: Message, state: FSMContext):
    problem = message.text.strip()
    print(f"Получено описание проблемы: {problem}")
    data = await state.get_data()

    fio = data.get("contact", {}).get("first_name", "клиент")
    obj_name = data.get("selected_object", {}).get("name", "не выбран")

    summary = (
        f"Спасибо, {fio}! Ожидайте звонок.\n\n"
        f"Объект: {obj_name}\n"
        f"Проблема: {problem}"
    )
    await message.answer(summary, reply_markup=start_kb)

    # Отправка заявки в OKDesk
    if OKDESK_API_TOKEN and OKDESK_SUBDOMAIN:
        issue_data = {
            "issue": {
                "title": f"Заявка из Telegram: {fio}",
                "description": summary,
                "priority": "normal",
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1/issues/?api_token={OKDESK_API_TOKEN}",
                    json=issue_data
                ) as resp:
                    if resp.status in (200, 201):
                        print("Заявка создана успешно!")
                        await message.answer("Заявка успешно отправлена в систему OKDesk!")
                    else:
                        text = await resp.text()
                        print(f"Ошибка OKDesk: {resp.status} - {text}")
                        await message.answer("Ошибка при отправке заявки. Свяжемся вручную.")
        except Exception as e:
            print(f"Ошибка отправки: {e}")
            await message.answer("Не удалось отправить заявку. Свяжемся вручную.")
    else:
        await message.answer("OKDesk не настроен — данные получены.")

    await state.clear()

async def main():
    print("Бот запущен! Используем polling.")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
