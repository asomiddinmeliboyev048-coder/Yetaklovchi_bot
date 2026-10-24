
import asyncio
import json

import aiohttp


API_URL = "https://namoz-vaqti.uz/index.php"

# API'da ishlatilishi tekshirilishi kerak bo'lgan hududlar.
REGIONS = {
    "Toshkent shahri": "toshkent",
    "Toshkent viloyati": "toshkent-viloyati",
    "Andijon viloyati": "andijon",
    "Buxoro viloyati": "buxoro",
    "Farg‘ona viloyati": "fargona",
    "Jizzax viloyati": "jizzax",
    "Xorazm viloyati": "urganch",
    "Namangan viloyati": "namangan",
    "Navoiy viloyati": "navoiy",
    "Qashqadaryo viloyati": "qarshi",
    "Samarqand viloyati": "samarqand",
    "Sirdaryo viloyati": "sirdaryo",
    "Surxondaryo viloyati": "termiz",
    "Qoraqalpog‘iston Respublikasi": "nukus",
}

PRAYER_TIMES = [
    ("bomdod", "Bomdod"),
    ("quyosh", "Quyosh"),
    ("peshin", "Peshin"),
    ("asr", "Asr"),
    ("shom", "Shom"),
    ("xufton", "Xufton"),
]


async def check_region(
    session: aiohttp.ClientSession,
    name: str,
    slug: str,
) -> bool:
    """Bitta hudud uchun API javobini tekshiradi."""

    params = {
        "region": slug,
        "lang": "lotin",
        "period": "today",
        "format": "json",
    }

    try:
        async with session.get(API_URL, params=params) as response:
            if response.status != 200:
                print(f"\n❌ {name}: HTTP {response.status}")
                return False

            try:
                data = await response.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                print(f"\n❌ {name}: javob JSON formatida emas")
                return False

            times = data.get("today", {}).get("times", {})
            meta = data.get("meta", {})
            actual_region = meta.get("region", {}).get("name", "Noma'lum hudud")

            required = ("bomdod", "peshin", "asr", "shom", "xufton")
            missing = [key for key in required if not times.get(key)]

            if missing:
                print(f"\n❌ {name}: namoz vaqtlari to'liq emas")
                print("Topilmagan maydonlar:", ", ".join(missing))
                print("API javobi:")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                return False

            print(f"\n✅ {name}")
            print(f"   API hududi: {actual_region}")

            for key, label in PRAYER_TIMES:
                value = times.get(key, "Mavjud emas")
                print(f"   {label}: {value}")

            return True

    except asyncio.TimeoutError:
        print(f"\n❌ {name}: API javobi vaqtida kelmadi")
    except aiohttp.ClientError as error:
        print(f"\n❌ {name}: ulanish xatosi: {error}")

    return False


async def main():
    timeout = aiohttp.ClientTimeout(total=20)

    print("=" * 45)
    print("YETAKLOVCHI — NAMOZ VAQTLARI API TESTI")
    print("=" * 45)

    success_count = 0
    failed_regions = []

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for name, slug in REGIONS.items():
            success = await check_region(session, name, slug)

            if success:
                success_count += 1
            else:
                failed_regions.append(name)

    print("\n" + "=" * 45)
    print(f"Jami hududlar: {len(REGIONS)}")
    print(f"Muvaffaqiyatli: {success_count}")
    print(f"Xatolik: {len(failed_regions)}")

    if failed_regions:
        print("\nAPI'da qayta tekshirilishi kerak bo'lgan hududlar:")
        for name in failed_regions:
            print(f" - {name}")

    print("=" * 45)


if __name__ == "__main__":
    asyncio.run(main())
