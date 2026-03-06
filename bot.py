# ... (начало файла без изменений)

async def get_contact_by_telegram_account(username: str):
    params = {"api_token": OKDESK_API_TOKEN, "telegram_account": f"@{username}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{OKDESK_API_BASE}/contacts", params=params) as resp:
            if resp.status != 200:
                print(f"Ошибка API: {resp.status} - {await resp.text()}")
                return None
            data = await resp.json()
            contacts = data.get("contacts", [])
            if not contacts:
                return None
            return contacts[0]

@dp.message(CommandStart())
@dp.message(lambda message: message.text == "СТАРТ")
async def cmd_start(message: Message, state: FSMContext):
    username = message.from_user.username
    user_id = message.from_user.id
    print(f"СТАРТ от @{username} (ID: {user_id})")

    await state.clear()
    await message.answer("Пожалуйста, подождите...", reply_markup=start_kb)

    if not username:
        await message.answer("У вас не установлен username в Telegram.", reply_markup=start_kb)
        return

    contact = await get_contact_by_telegram_account(username)

    if not contact:
        await message.answer(
            f"Здравствуйте!\n\n"
            f"Ваш Telegram-аккаунт @{username} не найден в базе клиентов.\n"
            "Обратитесь к менеджеру для регистрации.",
            reply_markup=start_kb
        )
        return

    fio = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip() or "клиент"
    company_id = contact.get("company_id")

    if not company_id:
        await message.answer(f"Здравствуйте, {fio}!\nКарточка не привязана к компании.", reply_markup=start_kb)
        return

    objects = await get_objects_by_company(company_id)

    if not objects:
        await message.answer(f"Здравствуйте, {fio}!\nУ вас нет объектов обслуживания.", reply_markup=start_kb)
        return

    object_list = "\n".join(
        f"{i+1}. {obj.get('name', 'Без названия')} (№ {obj.get('serial_number', 'не указан')})"
        for i, obj in enumerate(objects)
    )

    await message.answer(
        f"Здравствуйте, {fio}!\n\n"
        f"Выберите объект с проблемой:\n\n"
        f"{object_list}\n\n"
        "Напишите номер (1, 2, 3...)",
        reply_markup=start_kb
    )

    await state.update_data(contact=contact, objects=objects)
    await state.set_state(Form.select_object)

# ... (остальные функции process_object_selection и process_problem без изменений)
