import asyncio
import logging
import sys
from datetime import datetime

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import aiohttp
import os

# Получаем переменные из окружения (Bothost их уже добавил)
TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN") or
    os.getenv("TELEGRAM_BOT_TOKEN") or
    os.getenv("BOT_TOKEN") or
    os.getenv("TOKEN")
)

OKDESK_API_TOKEN = os.getenv("OKDESK_API_TOKEN")
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN")

if not TELEGRAM_TOKEN:
    print("КРИТИЧЕСКАЯ ОШИБКА: TELEGRAM_TOKEN не найден в окружении!")
    sys.exit(1)

if not OKDESK_API_TOKEN or not OKDESK_SUBDOMAIN:
    print("ОШИБКА: OKDesk переменные не найдены. Добавьте OKDESK_API_TOKEN и OKDESK_SUBDOMAIN в Environment variables.")
    # Можно продолжить без OKDesk, но лучше добавить
    # sys.exit(1)

OKDESK_URL = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1/issues/?api_token={OKDESK_API_TOKEN}" if OKDESK_SUBDOMAIN and OKDESK_API_TOKEN else None

bot = Bot(
    token=TELEGRAM_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

class Form(StatesGroup):
    full_name = State()
    phone = State()
    city = State()
    company = State()
    problem = State()

@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Здравствуйте, я — технический специалист компании Kubon.\n"
        "Пожалуйста, заполните анкету и мы с вами свяжемся.\n\n"
        "ФИО:"
    )
    await state.set_state(Form.full_name)

# ... (остальные handlers без изменений)

@dp.message(Form.problem)
async def process_problem(message: Message, state: FSMContext):
    await state.update_data(problem=message.text.strip())
    data = await state.get_data()

    summary = (
        "Спасибо, ожидайте звонок!\n\n"
        f"Ваши данные:\n"
        f"ФИО: {data.get('full_name')}\n"
        f"Телефон: {data.get('phone')}\n"
        f"Город: {data.get('city')}\n"
        f"Компания/ИП: {data.get('company')}\n"
        f"Проблема: {data.get('problem')}"
    )
    await message.answer(summary)

    if not OKDESK_URL:
        print("OKDesk не настроен — заявка не отправлена")
        await message.answer("Данные получены, но OKDesk не подключён.")
        await state.clear()
        return

    issue_data = {
        "issue": {
            "title": f"Заявка из Telegram: {data.get('full_name', 'Клиент')}",
            "description": (
                f"ФИО: {data.get('full_name')}\n"
                f"Телефон: {data.get('phone')}\n"
                f"Город: {data.get('city')}\n"
                f"Компания/ИП: {data.get('company')}\n"
                f"Описание проблемы: {data.get('problem')}\n\n"
                f"Источник: Telegram-бот Kubon"
            ),
            "priority": "medium",
            "kind_id": 1,
        }
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OKDESK_URL, json=issue_data) as resp:
                print(f"OKDesk статус: {resp.status}")
                if resp.status in (200, 201):
                    print("Заявка создана!")
                else:
                    text = await resp.text()
                    print(f"Ошибка OKDesk: {text}")
                    await message.answer("Ошибка отправки в OKDesk.")
    except Exception as e:
        print(f"Ошибка отправки: {e}")
        await message.answer("Не удалось отправить в OKDesk.")

    await state.clear()

async def main():
    print("Бот запущен! Токен:", TELEGRAM_TOKEN[:10] + "...")  # маскируем токен в логах
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
