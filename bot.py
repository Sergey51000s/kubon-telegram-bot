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
from aiogram.types import Message
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import aiohttp

# Токены из окружения Bothost
TELEGRAM_TOKEN = (
    os.getenv("TELEGRAM_TOKEN") or
    os.getenv("TELEGRAM_BOT_TOKEN") or
    os.getenv("BOT_TOKEN") or
    os.getenv("TOKEN")
)

OKDESK_API_TOKEN = os.getenv("OKDESK_API_TOKEN")
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN")

if not TELEGRAM_TOKEN:
    print("КРИТИЧЕСКАЯ ОШИБКА: TELEGRAM_TOKEN не найден!")
    sys.exit(1)

if not OKDESK_API_TOKEN or not OKDESK_SUBDOMAIN:
    print("ОШИБКА: OKDesk переменные не найдены. Добавьте OKDESK_API_TOKEN и OKDESK_SUBDOMAIN в Environment variables.")
    OKDESK_URL = None
else:
    OKDESK_URL = f"https://{OKDESK_SUBDOMAIN}.okdesk.ru/api/v1/issues/?api_token={OKDESK_API_TOKEN}"

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
    print(f"Получен /start от {message.from_user.id}")
    await state.clear()
    await message.answer(
        "Здравствуйте, я — технический специалист компании Kubon.\n"
        "Пожалуйста, заполните анкету и мы с вами свяжемся.\n\n"
        "ФИО:"
    )
    await state.set_state(Form.full_name)

@dp.message(Form.full_name)
async def process_full_name(message: Message, state: FSMContext):
    print(f"Получено ФИО: {message.text}")
    await state.update_data(full_name=message.text.strip())
    await message.answer("Номер телефона:")
    await state.set_state(Form.phone)

@dp.message(Form.phone)
async def process_phone(message: Message, state: FSMContext):
    print(f"Получен телефон: {message.text}")
    await state.update_data(phone=message.text.strip())
    await message.answer("Город:")
    await state.set_state(Form.city)

@dp.message(Form.city)
async def process_city(message: Message, state: FSMContext):
    print(f"Получен город: {message.text}")
    await state.update_data(city=message.text.strip())
    await message.answer("Компания/ИП:")
    await state.set_state(Form.company)

@dp.message(Form.company)
async def process_company(message: Message, state: FSMContext):
    print(f"Получена компания: {message.text}")
    await state.update_data(company=message.text.strip())
    await message.answer("Краткое описание проблемы (если возможно):")
    await state.set_state(Form.problem)

@dp.message(Form.problem)
async def process_problem(message: Message, state: FSMContext):
    print(f"Получено описание проблемы: {message.text}")
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

    if OKDESK_URL:
        issue_data = {
            "issue": {
                "title": f"Заявка из Telegram: {data.get('full_name', 'Клиент')}",
                "description": (
                    f"ФИО: {data.get('full_name')}\n"
                    f"Телефон: {data.get('phone')}\n"
                    f"Город: {data.get('city')}\n"
                    f"Компания/ИП: {data.get('company')}\n"
                    f"Описание проблемы: {data.get('problem')}\n\n"
                    f"Источник: Telegram-бот Kubon\n"
                    f"Дата: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
                ),
                "priority": "medium",
                "kind_id": 1,  # если знаешь реальный ID типа заявки — замени
            }
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(OKDESK_URL, json=issue_data) as resp:
                    if resp.status in (200, 201):
                        print("Заявка создана успешно в OKDesk!")
                        await message.answer("Заявка успешно отправлена в систему OKDesk!")
                    else:
                        text = await resp.text()
                        print(f"Ошибка OKDesk: статус {resp.status}, ответ: {text}")
                        await message.answer("Данные получены, но произошла ошибка при создании заявки в OKDesk. Мы свяжемся вручную.")
        except Exception as e:
            print(f"Ошибка отправки в OKDesk: {type(e).__name__}: {str(e)}")
            await message.answer("Не удалось отправить заявку в систему. Свяжемся вручную.")
    else:
        print("OKDesk URL не настроен")
        await message.answer("OKDesk не подключён — данные получены.")

    await state.clear()

async def main():
    print("Бот запущен! Используем polling.")
    print("Токен:", TELEGRAM_TOKEN[:10] + "...")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
