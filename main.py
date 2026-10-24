
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from database import (
    connect_db,
    close_db,
    save_user,
    get_user,
    save_user_city,
    save_user_profile,
    set_prayer_reminders,
    get_reminder_users,
    claim_prayer_reminder,
    release_prayer_reminder,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher()
UZBEKISTAN_TZ = timezone(timedelta(hours=5))


# =========================================================
# SHAHARLAR
# =========================================================

CITIES = {
    "Tashkent": "Toshkent",
    "Samarkand": "Samarqand",
    "Bukhara": "Buxoro",
    "Jizzax": "Jizzax",
    "Navoiy": "Navoiy",
    "Sirdaryo": "Sirdaryo",
    "Andijan": "Andijon",
    "Namangan": "Namangan",
    "Fergana": "Farg‘ona",
    "Karshi": "Qarshi",
    "Nukus": "Nukus",
    "Termez": "Termiz",
    "Urgench": "Urganch",
}

CITY_SLUGS = {
    "Tashkent": "toshkent",
    "Samarkand": "samarqand",
    "Bukhara": "buxoro",
    "Navoiy": "navoiy-viloyati",
    "Jizzax": "jizzax-viloyati",
    "Sirdaryo": "sirdaryo",
    "Andijan": "andijon",
    "Namangan": "namangan",
    "Fergana": "fargona",
    "Karshi": "qarshi",
    "Nukus": "nukus",
    "Termez": "termiz",
    "Urgench": "urganch",
}


# =========================================================
# JOY NOMLARINI ANIQLASH
# =========================================================

def normalize_place(value: str) -> str:
    value = value.lower().strip()
    value = value.replace("ʻ", "'").replace("’", "'")
    value = value.replace("‘", "'").replace("`", "'")

    for word in (
        "viloyati", "viloyat", "region", "province",
        "shahri", "shahar", "city", "district", "tumani", "tuman",
    ):
        value = re.sub(rf"\b{re.escape(word)}\b", " ", value)

    value = value.replace("'", "")
    value = re.sub(r"[^a-zа-яё0-9\s-]", "", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


PLACE_ALIASES = {
    "toshkent": "Tashkent",
    "tashkent": "Tashkent",
    "samarqand": "Samarkand",
    "samarkand": "Samarkand",
    "buxoro": "Bukhara",
    "bukhara": "Bukhara",
    "bukhoro": "Bukhara",
    "jizzax": "Jizzax",
    "jizzakh": "Jizzax",
    "navoiy": "Navoiy",
    "navoi": "Navoiy",
    "sirdaryo": "Sirdaryo",
    "guliston": "Sirdaryo",
    "gulistan": "Sirdaryo",
    "shirin": "Sirdaryo",
    "andijon": "Andijan",
    "andijan": "Andijan",
    "namangan": "Namangan",
    "fargona": "Fergana",
    "fergana": "Fergana",
    "qoqon": "Fergana",
    "kokand": "Fergana",
    "margilon": "Fergana",
    "margilan": "Fergana",
    "qarshi": "Karshi",
    "karshi": "Karshi",
    "qashqadaryo": "Karshi",
    "kashkadarya": "Karshi",
    "nukus": "Nukus",
    "qoraqalpogiston": "Nukus",
    "karakalpakstan": "Nukus",
    "termiz": "Termez",
    "termez": "Termez",
    "surxondaryo": "Termez",
    "surkhandarya": "Termez",
    "urganch": "Urgench",
    "urgench": "Urgench",
    "xorazm": "Urgench",
    "khorezm": "Urgench",
}


def identify_city(address: dict) -> str | None:
    candidates = [
        address.get("state"),
        address.get("province"),
        address.get("region"),
        address.get("state_district"),
        address.get("county"),
        address.get("city"),
        address.get("town"),
        address.get("municipality"),
        address.get("village"),
    ]

    for candidate in candidates:
        if candidate:
            normalized = normalize_place(candidate)
            if normalized in PLACE_ALIASES:
                return PLACE_ALIASES[normalized]

    return None


async def reverse_geocode(latitude: float, longitude: float) -> dict:
    url = "https://nominatim.openstreetmap.org/reverse"

    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "jsonv2",
        "addressdetails": 1,
        "accept-language": "uz,en",
    }

    headers = {"User-Agent": "YetaklovchiTelegramBot/1.0"}
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            url,
            params=params,
            headers=headers,
        ) as response:
            response.raise_for_status()
            result = await response.json(content_type=None)

    if not isinstance(result, dict):
        raise ValueError("Geocoding xizmati noto‘g‘ri javob qaytardi.")

    address = result.get("address")

    if not isinstance(address, dict):
        raise ValueError("Hududni aniqlab bo‘lmadi.")

    return {
        "city": identify_city(address),
        "display_name": result.get("display_name", ""),
    }


# =========================================================
# MATNLAR
# =========================================================

TEXTS = {
    "uz": {
        "welcome": (
            "Assalomu alaykum, <b>{name}</b>! 🌙\n\n"
            "Yetaklovchi botiga xush kelibsiz.\n"
            "Namoz vaqtlari va foydali eslatmalarni olish uchun "
            "telefon raqamingizni ulashing."
        ),
        "language": "🌐 Tilni tanlang:",
        "menu": "🏠 <b>Asosiy menyu</b>\n\nKerakli bo‘limni tanlang:",
        "prayer": "🕌 Namoz vaqtlari",
        "reminders": "🔔 Eslatmalar",
        "settings": "⚙️ Sozlamalar",
        "choose_city": (
            "📍 Namoz vaqtlarini ko‘rish uchun usulni tanlang.\n\n"
            "Lokatsiyangizni yuboring yoki shaharni qo‘lda tanlang."
        ),
        "location_button": "📍 Lokatsiyani yuborish",
        "location_prompt": (
            "Quyidagi tugmani bosib, Telegram orqali lokatsiyangizni yuboring.\n\n"
            "🔒 Koordinatalar bot bazasida saqlanmaydi."
        ),
        "location_received": "📍 Lokatsiya qabul qilindi. Hudud aniqlanmoqda...",
        "location_success": "✅ Aniqlangan hudud: <b>{city}</b>",
        "location_not_found": (
            "Hududingizni avtomatik aniqlay olmadim.\n"
            "Iltimos, shaharni qo‘lda tanlang."
        ),
        "location_error": (
            "Lokatsiyani qayta ishlashda xatolik yuz berdi.\n"
            "Shaharni qo‘lda tanlashingiz mumkin."
        ),
        "reminder_info": "🔔 <b>Namoz eslatmalari</b>",
        "reminder_status_on": "🟢 Eslatmalar: yoqilgan",
        "reminder_status_off": "🔴 Eslatmalar: o‘chirilgan",
        "reminder_enable": "🔔 Eslatmalarni yoqish",
        "reminder_disable": "🔕 Eslatmalarni o‘chirish",
        "reminder_need_city": (
            "Avval shahringizni tanlab saqlang. "
            "Keyin eslatmalarni yoqishingiz mumkin."
        ),
        "reminder_enabled": "✅ Namoz eslatmalari yoqildi!",
        "reminder_disabled": "🔕 Namoz eslatmalari o‘chirildi.",
        "reminder_message": (
            "🕌 <b>{prayer}</b> vaqti kirdi.\n"
            "📍 Shahar: <b>{city}</b>\n"
            "🕰 Vaqt: <b>{time}</b>\n\n"
            "Alloh ibodatlaringizni qabul qilsin! 🤲"
        ),
        "settings_info": (
            "⚙️ <b>Sozlamalar</b>\n\n"
            "Tilni o‘zgartirish yoki shaharni qayta tanlash mumkin."
        ),
        "select_language": "🌐 Tilni tanlang:",
        "saved": "Til muvaffaqiyatli tanlandi! ✅",
        "back": "⬅️ Asosiy menyu",
        "choose_city_button": "📍 Shaharni tanlash",
        "city_saved": "Shahringiz saqlandi! ✅",
        "prayer_title": "🕌 <b>{city} — namoz vaqtlari</b>",
        "date": "📅 Sana: {date}",
        "prayer_error": (
            "Namoz vaqtlarini hozircha olib bo‘lmadi.\n\n"
            "Internet aloqasini tekshirib, birozdan keyin qayta urinib ko‘ring."
        ),
        "city_error": "Shaharni saqlashda xatolik yuz berdi. Qayta urinib ko‘ring.",
    },

    "uz_cyr": {
        "welcome": (
            "Ассалому алайкум, <b>{name}</b>! 🌙\n\n"
            "Yetaklovchi ботига хуш келибсиз.\n"
            "Намоз вақтлари ва фойдали эслатмаларни олиш учун "
            "телефон рақамингизни улашинг."
        ),
        "language": "🌐 Тилни танланг:",
        "menu": "🏠 <b>Асосий меню</b>\n\nКеракли бўлимни танланг:",
        "prayer": "🕌 Намоз вақтлари",
        "reminders": "🔔 Эслатмалар",
        "settings": "⚙️ Созламалар",
        "choose_city": (
            "📍 Намоз вақтларини кўриш усулини танланг.\n\n"
            "Локациянгизни юборинг ёки шаҳарни қўлда танланг."
        ),
        "location_button": "📍 Локацияни юбориш",
        "location_prompt": (
            "Қуйидаги тугмани босиб, Telegram орқали локациянгизни юборинг.\n\n"
            "🔒 Координаталар базада сақланмайди."
        ),
        "location_received": "📍 Локация қабул қилинди. Ҳудуд аниқланмоқда...",
        "location_success": "✅ Аниқланган ҳудуд: <b>{city}</b>",
        "location_not_found": (
            "Ҳудудингизни автоматик аниқлай олмадим.\n"
            "Илтимос, шаҳарни қўлда танланг."
        ),
        "location_error": (
            "Локацияни қайта ишлашда хатолик юз берди.\n"
            "Шаҳарни қўлда танлашингиз мумкин."
        ),
        "reminder_info": "🔔 <b>Намоз эслатмалари</b>",
        "reminder_status_on": "🟢 Эслатмалар: ёқилган",
        "reminder_status_off": "🔴 Эслатмалар: ўчирилган",
        "reminder_enable": "🔔 Эслатмаларни ёқиш",
        "reminder_disable": "🔕 Эслатмаларни ўчириш",
        "reminder_need_city": (
            "Аввал шаҳарингизни танлаб сақланг. "
            "Кейин эслатмаларни ёқишингиз мумкин."
        ),
        "reminder_enabled": "✅ Намоз эслатмалари ёқилди!",
        "reminder_disabled": "🔕 Намоз эслатмалари ўчирилди.",
        "reminder_message": (
            "🕌 <b>{prayer}</b> вақти кирди.\n"
            "📍 Шаҳар: <b>{city}</b>\n"
            "🕰 Вақт: <b>{time}</b>\n\n"
            "Аллоҳ ибодатларингизни қабул қилсин! 🤲"
        ),
        "settings_info": (
            "⚙️ <b>Созламалар</b>\n\n"
            "Тилни ўзгартириш ёки шаҳарни қайта танлаш мумкин."
        ),
        "select_language": "🌐 Тилни танланг:",
        "saved": "Тил муваффақиятли танланди! ✅",
        "back": "⬅️ Асосий меню",
        "choose_city_button": "📍 Шаҳарни танлаш",
        "city_saved": "Шаҳрингиз сақланди! ✅",
        "prayer_title": "🕌 <b>{city} — намоз вақтлари</b>",
        "date": "📅 Сана: {date}",
        "prayer_error": (
            "Намоз вақтларини ҳозирча олиб бўлмади.\n\n"
            "Интернет алоқасини текшириб, бироздан кейин қайта уриниб кўринг."
        ),
        "city_error": "Шаҳарни сақлашда хатолик юз берди. Қайта уриниб кўринг.",
    },
}


# =========================================================
# NAMOZ NOMLARI
# =========================================================

PRAYER_NAMES = {
    "uz": [
        ("Fajr", "🌄 Bomdod"),
        ("Sunrise", "☀️ Quyosh"),
        ("Dhuhr", "🌞 Peshin"),
        ("Asr", "🌤 Asr"),
        ("Maghrib", "🌇 Shom"),
        ("Isha", "🌙 Xufton"),
    ],
    "uz_cyr": [
        ("Fajr", "🌄 Бомдод"),
        ("Sunrise", "☀️ Қуёш"),
        ("Dhuhr", "🌞 Пешин"),
        ("Asr", "🌤 Аср"),
        ("Maghrib", "🌇 Шом"),
        ("Isha", "🌙 Хуфтон"),
    ],
}


# =========================================================
# KLAVIATURALAR
# =========================================================

def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="🇺🇿 O‘zbekcha (lotin)",
                callback_data="lang:uz",
            )],
            [InlineKeyboardButton(
                text="🇺🇿 Ўзбекча (кирилл)",
                callback_data="lang:uz_cyr",
            )],
        ]
    )


def main_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=t["prayer"],
                callback_data="menu:prayer",
            )],
            [InlineKeyboardButton(
                text=t["reminders"],
                callback_data="menu:reminders",
            )],
            [InlineKeyboardButton(
                text=t["settings"],
                callback_data="menu:settings",
            )],
        ]
    )


def back_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text=TEXTS[lang]["back"],
                callback_data="menu:home",
            )
        ]]
    )


def city_keyboard(lang: str) -> InlineKeyboardMarkup:
    items = list(CITIES.items())
    rows = []

    for index in range(0, len(items), 2):
        rows.append([
            InlineKeyboardButton(
                text=f"📍 {name}",
                callback_data=f"city:{key}",
            )
            for key, name in items[index:index + 2]
        ])

    rows.append([
        InlineKeyboardButton(
            text=TEXTS[lang]["back"],
            callback_data="menu:home",
        )
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def location_request_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text=TEXTS[lang]["location_button"],
                request_location=True,
            )
        ]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder=TEXTS[lang]["location_button"],
    )


def contact_request_keyboard(lang: str) -> ReplyKeyboardMarkup:
    text = (
        "📱 Телефон рақамни улашиш"
        if lang == "uz_cyr"
        else "📱 Telefon raqamni ulashish"
    )

    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(
                text=text,
                request_contact=True,
            )
        ]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder=text,
    )


def settings_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=t["select_language"],
                callback_data="settings:language",
            )],
            [InlineKeyboardButton(
                text=t["choose_city_button"],
                callback_data="menu:choose_city",
            )],
            [InlineKeyboardButton(
                text=t["back"],
                callback_data="menu:home",
            )],
        ]
    )


def reminders_keyboard(lang: str, enabled: bool) -> InlineKeyboardMarkup:
    t = TEXTS[lang]

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=t["reminder_status_on"] if enabled
                else t["reminder_status_off"],
                callback_data="reminder:status",
            )],
            [InlineKeyboardButton(
                text=t["reminder_disable"] if enabled
                else t["reminder_enable"],
                callback_data="reminder:disable" if enabled
                else "reminder:enable",
            )],
            [InlineKeyboardButton(
                text=t["choose_city_button"],
                callback_data="menu:choose_city",
            )],
            [InlineKeyboardButton(
                text=t["back"],
                callback_data="menu:home",
            )],
        ]
    )


# =========================================================
# FOYDALANUVCHI TILI
# =========================================================

async def get_saved_language(user_id: int) -> str:
    user_data = await get_user(user_id)

    if user_data is None:
        await save_user(user_id, "uz")
        return "uz"

    lang = user_data.get("language", "uz")
    return lang if lang in TEXTS else "uz"


# =========================================================
# NAMOZ VAQTLARI API
# =========================================================

async def fetch_prayer_times(city: str) -> dict:
    slug = CITY_SLUGS.get(city)

    if not slug:
        raise ValueError(f"Shahar topilmadi: {city}")

    url = "https://namoz-vaqti.uz/index.php"
    params = {
        "region": slug,
        "lang": "lotin",
        "period": "today",
        "format": "json",
    }

    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as response:
            response.raise_for_status()
            result = await response.json(content_type=None)

    if not isinstance(result, dict):
        raise ValueError("API noto‘g‘ri formatda javob qaytardi.")

    today_data = result.get("today")
    if not isinstance(today_data, dict):
        raise ValueError("API javobida bugungi kun ma’lumoti yo‘q.")

    timings = today_data.get("times")
    if not isinstance(timings, dict):
        raise ValueError("API javobida namoz vaqtlari topilmadi.")

    mapping = {
        "Fajr": "bomdod",
        "Sunrise": "quyosh",
        "Dhuhr": "peshin",
        "Asr": "asr",
        "Maghrib": "shom",
        "Isha": "xufton",
    }

    if any(not timings.get(key) for key in mapping.values()):
        raise ValueError("API barcha namoz vaqtlarini qaytarmadi.")

    return {
        key: str(timings[api_key]).strip()
        for key, api_key in mapping.items()
    }


async def send_prayer_times(
    message: Message,
    city: str,
    lang: str,
    location_based: bool = False,
) -> None:
    t = TEXTS[lang]

    try:
        timings = await fetch_prayer_times(city)
        current_date = datetime.now(UZBEKISTAN_TZ).strftime("%d.%m.%Y")

        lines = [
            t["prayer_title"].format(city=CITIES.get(city, city)),
            t["date"].format(date=current_date),
            "",
        ]

        for key, name in PRAYER_NAMES[lang]:
            value = timings.get(key)
            if value:
                lines.append(f"{name}: <b>{value.split()[0]}</b>")

        if location_based:
            lines.insert(1, "📍 <i>Hudud lokatsiya orqali aniqlandi.</i>")
            lines.insert(2, "")

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=t["choose_city_button"],
                    callback_data="menu:choose_city",
                )],
                [InlineKeyboardButton(
                    text=t["back"],
                    callback_data="menu:home",
                )],
            ]
        )

        await message.answer(
            "\n".join(lines),
            reply_markup=keyboard,
        )

    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
        logger.exception("Namoz vaqtlarini olishda xatolik. Shahar: %s", city)
        await message.answer(
            t["prayer_error"],
            reply_markup=back_keyboard(lang),
        )


# =========================================================
# /START VA TELEFON RAQAMI
# =========================================================

@dp.message(CommandStart())
async def start_handler(message: Message) -> None:
    user = message.from_user
    if user is None:
        return

    await save_user(user.id, "uz")
    user_data = await get_user(user.id)

    lang = user_data.get("language", "uz") if user_data else "uz"
    if lang not in TEXTS:
        lang = "uz"

    # Telegram'dan kelgan ism va username profilga yangilanadi.
    await save_user_profile(
        telegram_id=user.id,
        first_name=user.first_name or "",
        last_name=user.last_name,
        username=user.username,
    )

    user_data = await get_user(user.id)

    if user_data and user_data.get("phone_number"):
        await message.answer(
            TEXTS[lang]["menu"],
            reply_markup=main_keyboard(lang),
        )
        return

    await message.answer(
        TEXTS[lang]["welcome"].format(name=user.full_name)
        + "\n\n📱 Davom etish uchun telefon raqamingizni ulashing.",
        reply_markup=contact_request_keyboard(lang),
    )


@dp.message(F.contact)
async def contact_handler(message: Message) -> None:
    user = message.from_user
    contact = message.contact

    if user is None or contact is None:
        return

    lang = await get_saved_language(user.id)

    # Faqat jo'natuvchining o'z Telegram kontakti qabul qilinadi.
    if contact.user_id != user.id:
        await message.answer(
            "Iltimos, faqat o'zingizning Telegram kontaktingizni "
            "ulashing.",
            reply_markup=contact_request_keyboard(lang),
        )
        return

    phone_number = contact.phone_number.strip()

    if not phone_number:
        await message.answer(
            "Telefon raqami olinmadi. Qayta urinib ko'ring.",
            reply_markup=contact_request_keyboard(lang),
        )
        return

    await save_user_profile(
        telegram_id=user.id,
        first_name=user.first_name or "",
        last_name=user.last_name,
        username=user.username,
        phone_number=phone_number,
    )

    await message.answer(
        "✅ Telefon raqamingiz va profilingiz saqlandi!",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        TEXTS[lang]["menu"],
        reply_markup=main_keyboard(lang),
    )


@dp.message(Command("language"))
async def language_handler(message: Message) -> None:
    user = message.from_user
    if user is None:
        return

    lang = await get_saved_language(user.id)
    await message.answer(
        TEXTS[lang]["select_language"],
        reply_markup=language_keyboard(),
    )


@dp.callback_query(F.data.startswith("lang:"))
async def language_callback(callback: CallbackQuery) -> None:
    lang = (callback.data or "").split(":", 1)[1]

    if lang not in TEXTS:
        await callback.answer("Noto‘g‘ri til tanlandi.")
        return

    await save_user(callback.from_user.id, lang)
    await callback.answer(TEXTS[lang]["saved"])

    if callback.message:
        await callback.message.answer(
            TEXTS[lang]["menu"],
            reply_markup=main_keyboard(lang),
        )


# =========================================================
# SHAHAR TANLASH
# =========================================================

@dp.callback_query(F.data.startswith("city:"))
async def city_callback(callback: CallbackQuery) -> None:
    city = (callback.data or "").split(":", 1)[1]

    if city not in CITIES:
        await callback.answer("Shahar tanlovi noto‘g‘ri.")
        return

    await callback.answer("Namoz vaqtlari yuklanmoqda...")

    try:
        await save_user_city(callback.from_user.id, city)
        lang = await get_saved_language(callback.from_user.id)

        if callback.message:
            await callback.message.answer(
                TEXTS[lang]["city_saved"],
                reply_markup=ReplyKeyboardRemove(),
            )
            await send_prayer_times(callback.message, city, lang)

    except Exception:
        logger.exception("Shaharni saqlashda xatolik.")
        lang = await get_saved_language(callback.from_user.id)

        if callback.message:
            await callback.message.answer(
                TEXTS[lang]["city_error"],
                reply_markup=back_keyboard(lang),
            )


# =========================================================
# LOKATSIYA
# =========================================================

@dp.callback_query(F.data == "location:request")
async def request_location_callback(callback: CallbackQuery) -> None:
    lang = await get_saved_language(callback.from_user.id)

    if callback.message:
        await callback.message.answer(
            TEXTS[lang]["location_prompt"],
            reply_markup=location_request_keyboard(lang),
        )

    await callback.answer()


@dp.message(F.location)
async def location_handler(message: Message) -> None:
    user = message.from_user
    if user is None or message.location is None:
        return

    lang = await get_saved_language(user.id)
    latitude = message.location.latitude
    longitude = message.location.longitude

    await message.answer(
        TEXTS[lang]["location_received"],
        reply_markup=ReplyKeyboardRemove(),
    )

    try:
        place = await reverse_geocode(latitude, longitude)
        city = place.get("city")

        if not city or city not in CITIES:
            await message.answer(
                TEXTS[lang]["location_not_found"],
                reply_markup=city_keyboard(lang),
            )
            return

        # GPS koordinatalari saqlanmaydi. Eslatmalar uchun shahar
        # tanlanishini foydalanuvchining o'zi tasdiqlashi kerak.
        await message.answer(
            TEXTS[lang]["location_success"].format(city=CITIES[city]),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(
                        text="✅ Shu shaharni saqlash",
                        callback_data=f"city:{city}",
                    )],
                    [InlineKeyboardButton(
                        text=TEXTS[lang]["choose_city_button"],
                        callback_data="menu:choose_city",
                    )],
                ]
            ),
        )

        await send_prayer_times(
            message,
            city,
            lang,
            location_based=True,
        )

    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError):
        logger.warning("Lokatsiya hududini aniqlash muvaffaqiyatsiz tugadi.")
        await message.answer(
            TEXTS[lang]["location_error"],
            reply_markup=city_keyboard(lang),
        )

    except Exception:
        logger.exception("Lokatsiyani qayta ishlashda kutilmagan xatolik.")
        await message.answer(
            TEXTS[lang]["location_error"],
            reply_markup=city_keyboard(lang),
        )


# =========================================================
# ASOSIY MENYU
# =========================================================

@dp.callback_query(F.data.startswith("menu:"))
async def menu_callback(callback: CallbackQuery) -> None:
    lang = await get_saved_language(callback.from_user.id)
    t = TEXTS[lang]
    section = (callback.data or "").split(":", 1)[1]

    if section == "home":
        if callback.message:
            await callback.message.answer(
                t["menu"],
                reply_markup=main_keyboard(lang),
            )

    elif section == "prayer":
        user_data = await get_user(callback.from_user.id)
        saved_city = user_data.get("city") if user_data else None

        if saved_city and saved_city in CITIES:
            if callback.message:
                await send_prayer_times(callback.message, saved_city, lang)
        elif callback.message:
            await callback.message.answer(
                t["choose_city"],
                reply_markup=city_keyboard(lang),
            )
            await callback.message.answer(
                t["location_prompt"],
                reply_markup=location_request_keyboard(lang),
            )

    elif section == "choose_city":
        if callback.message:
            await callback.message.answer(
                t["choose_city"],
                reply_markup=city_keyboard(lang),
            )
            await callback.message.answer(
                t["location_prompt"],
                reply_markup=location_request_keyboard(lang),
            )

    elif section == "reminders":
        user_data = await get_user(callback.from_user.id)
        enabled = bool(
            user_data and user_data.get("prayer_reminders_enabled")
        )
        city = user_data.get("city") if user_data else None

        city_text = (
            f"\n📍 Shahar: <b>{CITIES.get(city, city)}</b>"
            if city and city in CITIES
            else "\n📍 Shahar: hali tanlanmagan"
        )

        reminder_text = (
            f"{t['reminder_info']}\n\n"
            f"{t['reminder_status_on'] if enabled else t['reminder_status_off']}"
            f"{city_text}\n\n"
            "Eslatmalar Bomdod, Peshin, Asr, Shom va Xufton "
            "vaqtlarida yuboriladi."
        )

        if callback.message:
            await callback.message.answer(
                reminder_text,
                reply_markup=reminders_keyboard(lang, enabled),
            )

    elif section == "settings":
        if callback.message:
            await callback.message.answer(
                t["settings_info"],
                reply_markup=settings_keyboard(lang),
            )

    await callback.answer()


# =========================================================
# NAMOZ ESLATMALARINI YOQISH/O'CHIRISH
# =========================================================

@dp.callback_query(F.data.startswith("reminder:"))
async def reminder_callback(callback: CallbackQuery) -> None:
    lang = await get_saved_language(callback.from_user.id)
    t = TEXTS[lang]
    user_id = callback.from_user.id
    action = (callback.data or "").split(":", 1)[1]

    try:
        user_data = await get_user(user_id)
        enabled = bool(
            user_data and user_data.get("prayer_reminders_enabled")
        )

        if action == "status":
            await callback.answer(
                t["reminder_status_on"] if enabled
                else t["reminder_status_off"],
                show_alert=True,
            )
            return

        if action == "enable":
            city = user_data.get("city") if user_data else None

            if not city or city not in CITY_SLUGS:
                await callback.answer(
                    t["reminder_need_city"],
                    show_alert=True,
                )
                if callback.message:
                    await callback.message.answer(
                        t["reminder_need_city"],
                        reply_markup=city_keyboard(lang),
                    )
                return

            await set_prayer_reminders(user_id, True)
            enabled = True
            answer_text = t["reminder_enabled"]

        elif action == "disable":
            await set_prayer_reminders(user_id, False)
            enabled = False
            answer_text = t["reminder_disabled"]

        else:
            await callback.answer("Noma’lum amal.")
            return

        await callback.answer(answer_text)

        if callback.message:
            await callback.message.answer(
                f"{t['reminder_info']}\n\n"
                f"{t['reminder_status_on'] if enabled else t['reminder_status_off']}",
                reply_markup=reminders_keyboard(lang, enabled),
            )

    except Exception:
        logger.exception("Eslatma sozlamasini o‘zgartirishda xatolik.")
        await callback.answer(
            "Xatolik yuz berdi. Qayta urinib ko‘ring.",
            show_alert=True,
        )


# =========================================================
# SOZLAMALAR: TILNI O'ZGARTIRISH
# =========================================================

@dp.callback_query(F.data == "settings:language")
async def settings_language_callback(callback: CallbackQuery) -> None:
    lang = await get_saved_language(callback.from_user.id)

    if callback.message:
        await callback.message.answer(
            TEXTS[lang]["select_language"],
            reply_markup=language_keyboard(),
        )

    await callback.answer()


# =========================================================
# NAMOZ ESLATMALARINI AVTOMATIK YUBORISH
# =========================================================

async def prayer_reminder_worker() -> None:
    prayer_keys = ("Fajr", "Dhuhr", "Asr", "Maghrib", "Isha")

    logger.info("Namoz eslatmalari xizmati ishga tushdi.")

    while True:
        try:
            now = datetime.now(UZBEKISTAN_TZ)
            today = now.date()
            current_time = now.strftime("%H:%M")

            users = await get_reminder_users()
            city_times = {}

            for user_data in users:
                user_id = user_data["telegram_id"]
                city = user_data.get("city")
                lang = user_data.get("language", "uz")

                if lang not in TEXTS:
                    lang = "uz"

                if not city or city not in CITY_SLUGS:
                    continue

                if city not in city_times:
                    try:
                        city_times[city] = await fetch_prayer_times(city)
                    except Exception:
                        logger.exception(
                            "Namoz vaqtlarini olishda xatolik: %s",
                            city,
                        )
                        city_times[city] = None

                timings = city_times[city]
                if not timings:
                    continue

                for prayer_key in prayer_keys:
                    prayer_time = timings.get(prayer_key)
                    if not prayer_time:
                        continue

                    prayer_time = prayer_time.split()[0]

                    if prayer_time != current_time:
                        continue

                    claimed = await claim_prayer_reminder(
                        user_id,
                        today,
                        prayer_key,
                    )

                    if not claimed:
                        continue

                    prayer_names = dict(PRAYER_NAMES[lang])
                    prayer_name = prayer_names.get(prayer_key, prayer_key)

                    text = TEXTS[lang]["reminder_message"].format(
                        prayer=prayer_name,
                        city=CITIES.get(city, city),
                        time=prayer_time,
                    )

                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=text,
                        )
                        logger.info(
                            "Namoz eslatmasi yuborildi: user_id=%s, prayer=%s",
                            user_id,
                            prayer_key,
                        )

                    except Exception:
                        logger.exception(
                            "Eslatma yuborilmadi: user_id=%s, prayer=%s",
                            user_id,
                            prayer_key,
                        )

                        try:
                            await release_prayer_reminder(
                                user_id,
                                today,
                                prayer_key,
                            )
                        except Exception:
                            logger.exception(
                                "Eslatma qaydini o‘chirishda xatolik."
                            )

        except asyncio.CancelledError:
            logger.info("Namoz eslatmalari xizmati to‘xtatildi.")
            raise

        except Exception:
            logger.exception("Eslatmalar siklida kutilmagan xatolik.")

        await asyncio.sleep(20)


# =========================================================
# BOTNI ISHGA TUSHIRISH
# =========================================================

async def main() -> None:
    logger.info("Yetaklovchi bot ishga tushmoqda...")

    await connect_db()
    reminder_task = asyncio.create_task(prayer_reminder_worker())

    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot)

    finally:
        reminder_task.cancel()

        try:
            await reminder_task
        except asyncio.CancelledError:
            pass

        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
