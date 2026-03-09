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
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, ContentType
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import aiohttp

# === Настройки ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
OKDESK_API_TOKEN = os.getenv("OKDESK_API_TOKEN") or "80ce0681fc84a44a7ca11450b24587b9fa367fa8"
OKDESK_SUBDOMAIN = os.getenv("OKDESK_SUBDOMAIN") or "teken2027"

# Из твоих настроек
ISSUE_KIND_ID = 2          # Обслуживание
ISSUE_PRIORITY_ID = 2      # Обычный
ISSUE_CHANNEL_ID = 1       # По умолчанию

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
    serial_input = State()
    issue_description = State()
    ask_attach = State()
    wait_attach = State()


# Клавиатуры
start_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="СТАРТ")]],
    resize_keyboard=True
)

main_menu_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Срок действия подписки")],
        [KeyboardButton(text="Обслуживание")]
    ],
    resize_keyboard=True
)

back_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Назад в меню")]],
    resize_keyboard=True
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
        [KeyboardButton(text="Назад в меню")]
    ],
    resize_keyboard=True
)

attach_choice_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Да, прикрепить фото/видео")],
        [KeyboardButton(text="Нет, создать заявку без файлов")]
    ],
    resize_keyboard=True
)

done_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Готово, отправить заявку")]],
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
        logging.info(f"Поиск контакта: {phone}")
        async with session.get(f"{OKDESK_API_BASE}/contacts", params=params) as resp:
            if resp.status != 200:
                logging.error(f"Ошибка /contacts: {resp.status}")
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
        logging.info(f"Поиск оборудования по serial: {serial}")
        async with session.get(f"{OKDESK_API_BASE}/equipments", params=params) as resp:
            if resp.status != 200:
                logging.error(f"Ошибка поиска: {resp.status}")
                return None
            data = await resp.json()
            if isinstance(data, dict) and "id" in data:
                return data
            return None


async def create_issue(company_id: int, equipment_id: int, maintenance_entity_id: int, description: str):
    payload = {
        "api_token": OKDESK_API_TOKEN,
        "issue[company_id]": str(company_id),
        "issue[equipment_id]": str(equipment_id),
        "issue[maintenance_entity_id]": str(maintenance_entity_id) if maintenance_entity_id else None,
        "issue[title]": "Заявка из Telegram-бота",
        "issue[content]": description or "Без описания",
        "issue[kind_id]": str(ISSUE_KIND_ID),
        "issue[priority_id]": str(ISSUE_PRIORITY_ID),
        "issue[channel_id]": str(ISSUE_CHANNEL_ID),
    }
    payload = {k: v for k, v in payload.items() if v is not None}

    async with aiohttp.ClientSession() as session:
        logging.info(f"Создание заявки с payload: {payload}")
        async with session.post(f"{OKDESK_API_BASE}/issues", data=payload) as resp:
            text = await resp.text()
            logging.info(f"Ответ создания заявки: {resp.status} - {text}")
            if resp.status in (200, 201):
                data = await resp.json()
                return data.get("id")
            return None


async def upload_attachment(issue_id: int, file_bytes: bytes, filename: str):
    form = aiohttp.FormData()
    form.add_field("api_token", OKDESK_API_TOKEN)
    form.add_field("attachment[0]", file_bytes, filename=filename, content_type="application/octet-stream")

    async with aiohttp.ClientSession() as session:
        url = f"{OKDESK_API_BASE}/issues/{issue_id}/attachments"
        logging.info(f"Загрузка файла к заявке {issue_id}: {filename}")
        async with session.post(url, data=form) as resp:
            text = await resp.text()
            logging.info(f"Ответ на загрузку файла: {resp.status} - {text}")
            return resp.status in (200, 201)


# Хендлеры
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
        "Введите серийный номер вашего робота или оборудования:",
        reply_markup=back_kb
    )
    await state.set_state(Form.serial_input)


@dp.message(Form.serial_input, F.text == "Назад в меню")
async def cancel_serial(message: Message, state: FSMContext):
    await message.answer("Главное меню:", reply_markup=main_menu_kb)
    await state.set_state(Form.menu)


@dp.message(Form.serial_input)
async def process_serial(message: Message, state: FSMContext):
    serial = message.text.strip()
    if not serial:
        await message.answer("Введите номер, пожалуйста.")
        return

    equipment = await search_equipment_by_serial(serial)

    if not equipment:
        await message.answer(
            f"Оборудование с номером {serial} не найдено.\nПроверьте номер или обратитесь к менеджеру.",
            reply_markup=main_menu_kb
        )
        await state.set_state(Form.menu)
        return

    kind = equipment.get("equipment_kind", {}).get("name", "Не указан")
    manufacturer = equipment.get("equipment_manufacturer", {}).get("name", "")
    model = equipment.get("equipment_model", {}).get("name", "")
    serial_found = equipment.get("serial_number", "не указан")
    maintenance_entity_id = equipment.get("maintenance_entity_id", None)

    info = (
        f"<b>Найдено оборудование:</b>\n"
        f"Вид: {kind}\n"
        f"Производитель: {manufacturer}\n"
        f"Модель: {model}\n"
        f"Серийный №: {serial_found}\n"
        f"Объект обслуживания ID: {maintenance_entity_id or 'Не привязан'}"
    )

    await message.answer(info, reply_markup=confirm_issue_kb)
    await state.update_data(equipment=equipment, maintenance_entity_id=maintenance_entity_id)
    await state.set_state(Form.issue_description)


@dp.message(Form.issue_description, F.text == "Назад в меню")
async def cancel_issue(message: Message, state: FSMContext):
    await message.answer("Главное меню:", reply_markup=main_menu_kb)
    await state.set_state(Form.menu)


@dp.message(Form.issue_description)
async def process_description(message: Message, state: FSMContext):
    desc = message.text.strip()
    if desc == "Назад в меню":
        await cancel_issue(message, state)
        return

    await state.update_data(issue_description=desc)

    await message.answer(
        "Желаете прикрепить фото или видео к заявке?",
        reply_markup=attach_choice_kb
    )
    await state.set_state(Form.ask_attach)


@dp.message(Form.ask_attach, F.text == "Нет, создать заявку без файлов")
async def create_without_attach(message: Message, state: FSMContext):
    await create_and_finish_issue(message, state, [])


@dp.message(Form.ask_attach, F.text == "Да, прикрепить фото/видео")
async def request_attach(message: Message, state: FSMContext):
    await message.answer(
        "Пришлите фото, видео или документ (можно несколько).\n\nКогда закончите — нажмите «Готово, отправить заявку»",
        reply_markup=done_kb
    )
    await state.set_state(Form.wait_attach)


@dp.message(Form.wait_attach, F.content_type.in_({ContentType.PHOTO, ContentType.DOCUMENT, ContentType.VIDEO}))
async def collect_attach(message: Message, state: FSMContext):
    data = await state.get_data()
    attachments = data.get("attachments", [])

    file_id = None
    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document:
        file_id = message.document.file_id
    elif message.video:
        file_id = message.video.file_id

    if file_id:
        attachments.append(file_id)
        await state.update_data(attachments=attachments)
        await message.answer("Файл добавлен. Присылайте ещё или нажмите «Готово».")
    else:
        await message.answer("Поддерживаются фото, видео, документы.")


@dp.message(Form.wait_attach, F.text == "Готово, отправить заявку")
async def finish_with_attach(message: Message, state: FSMContext):
    data = await state.get_data()
    attachments = data.get("attachments", [])
    await create_and_finish_issue(message, state, attachments)


async def create_and_finish_issue(message: Message, state: FSMContext, attachments: list):
    data = await state.get_data()
    contact = data.get("contact", {})
    equipment = data.get("equipment", {})
    description = data.get("issue_description", "Без описания")
    maintenance_entity_id = data.get("maintenance_entity_id", None)

    company_id = contact.get("company_id")
    equipment_id = equipment.get("id")

    if not company_id or not equipment_id:
        await message.answer("Ошибка данных. Попробуйте заново.", reply_markup=main_menu_kb)
        await state.set_state(Form.menu)
        return

    issue_id = await create_issue(company_id, equipment_id, maintenance_entity_id, description)

    if not issue_id:
        await message.answer("Не удалось создать заявку. Обратитесь к менеджеру.", reply_markup=main_menu_kb)
        await state.set_state(Form.menu)
        return

    # Загрузка файлов
    uploaded = 0
    for idx, file_id in enumerate(attachments):
        try:
            file = await bot.get_file(file_id)
            file_path = file.file_path
            file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"

            async with aiohttp.ClientSession() as session:
                async with session.get(file_url) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        content_type = resp.headers.get("Content-Type", "application/octet-stream")
                        ext = content_type.split('/')[-1] or "bin"
                        filename = f"attach_{idx + 1}.{ext}"
                        success = await upload_attachment(issue_id, content, filename)
                        if success:
                            uploaded += 1
        except Exception as e:
            logging.error(f"Ошибка загрузки файла {file_id}: {e}")

    text = f"Заявка создана успешно!\nНомер заявки: {issue_id}"
    if uploaded > 0:
        text += f"\nПрикреплено файлов: {uploaded}"
    await message.answer(text, reply_markup=main_menu_kb)
    await state.clear()
    await state.set_state(Form.menu)


@dp.message(Form.menu, F.text == "Срок действия подписки")
async def process_subscription(message: Message, state: FSMContext):
    await message.answer(
        "Функция «Срок действия подписки» пока в разработке.\nСкоро появится!",
        reply_markup=main_menu_kb
    )


@dp.message(F.text.in_({"Назад в меню", "Назад"}))
async def back_to_menu(message: Message, state: FSMContext):
    await message.answer("Главное меню:", reply_markup=main_menu_kb)
    await state.set_state(Form.menu)


@dp.message(Form.menu)
async def unknown_menu(message: Message, state: FSMContext):
    await message.answer("Выберите пункт меню:", reply_markup=main_menu_kb)


async def main():
    print("KubonSupportBot запущен (aiogram 3.x + OKDesk)")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
