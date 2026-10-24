
import os
import logging
from datetime import date
from typing import Optional, Any

import asyncpg

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
pool: Optional[asyncpg.Pool] = None


async def connect_db() -> None:
    """PostgreSQL bilan ulanish va zarur jadvallarni tayyorlash."""
    global pool

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL topilmadi. Muhit o'zgaruvchilarini tekshiring."
        )

    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        command_timeout=30,
    )

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id BIGINT PRIMARY KEY,
                    language VARCHAR(10) NOT NULL DEFAULT 'uz',
                    city VARCHAR(100),
                    prayer_reminders BOOLEAN NOT NULL DEFAULT TRUE,
                    daily_reminders BOOLEAN NOT NULL DEFAULT TRUE,
                    prayer_reminders_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    phone_number TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

            # Avvaldan mavjud users jadvaliga ustunlar qo'shiladi.
            await conn.execute(
                """
                ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS language VARCHAR(10)
                        NOT NULL DEFAULT 'uz',
                    ADD COLUMN IF NOT EXISTS city VARCHAR(100),
                    ADD COLUMN IF NOT EXISTS prayer_reminders BOOLEAN
                        NOT NULL DEFAULT TRUE,
                    ADD COLUMN IF NOT EXISTS daily_reminders BOOLEAN
                        NOT NULL DEFAULT TRUE,
                    ADD COLUMN IF NOT EXISTS prayer_reminders_enabled BOOLEAN
                        NOT NULL DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS first_name TEXT,
                    ADD COLUMN IF NOT EXISTS last_name TEXT,
                    ADD COLUMN IF NOT EXISTS username TEXT,
                    ADD COLUMN IF NOT EXISTS phone_number TEXT,
                    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW(),
                    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ
                        NOT NULL DEFAULT NOW();
                """
            )

            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS prayer_reminder_log (
                    id BIGSERIAL PRIMARY KEY,
                    telegram_id BIGINT NOT NULL
                        REFERENCES users(telegram_id) ON DELETE CASCADE,
                    reminder_date DATE NOT NULL,
                    prayer_key VARCHAR(20) NOT NULL,
                    sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (telegram_id, reminder_date, prayer_key)
                );
                """
            )

        logger.info("PostgreSQL bazasiga ulanish muvaffaqiyatli!")

    except Exception:
        await pool.close()
        pool = None
        logger.exception("Ma'lumotlar bazasini tayyorlashda xatolik.")
        raise


async def close_db() -> None:
    """Ma'lumotlar bazasi ulanishini yopish."""
    global pool

    if pool is not None:
        await pool.close()
        pool = None
        logger.info("PostgreSQL ulanishi yopildi.")


def _require_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError(
            "Ma'lumotlar bazasiga ulanish yo'q. Avval connect_db() chaqiring."
        )
    return pool


async def save_user(
    telegram_id: int,
    language: str = "uz",
) -> None:
    """Foydalanuvchini yaratish yoki tilini yangilash."""
    db = _require_pool()

    if language not in ("uz", "uz_cyr"):
        language = "uz"

    await db.execute(
        """
        INSERT INTO users (telegram_id, language)
        VALUES ($1, $2)
        ON CONFLICT (telegram_id)
        DO UPDATE SET
            language = EXCLUDED.language,
            updated_at = NOW();
        """,
        telegram_id,
        language,
    )


async def get_user(telegram_id: int) -> Optional[dict[str, Any]]:
    """Telegram ID bo'yicha foydalanuvchi profilini olish."""
    db = _require_pool()

    row = await db.fetchrow(
        """
        SELECT
            telegram_id,
            language,
            city,
            prayer_reminders,
            daily_reminders,
            prayer_reminders_enabled,
            first_name,
            last_name,
            username,
            phone_number,
            created_at,
            updated_at
        FROM users
        WHERE telegram_id = $1;
        """,
        telegram_id,
    )

    return dict(row) if row else None


async def save_user_profile(
    telegram_id: int,
    first_name: str,
    last_name: Optional[str] = None,
    username: Optional[str] = None,
    phone_number: Optional[str] = None,
) -> None:
    """Telegram profil ma'lumotlarini saqlash."""
    db = _require_pool()

    await db.execute(
        """
        INSERT INTO users (
            telegram_id,
            first_name,
            last_name,
            username,
            phone_number
        )
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (telegram_id)
        DO UPDATE SET
            first_name = EXCLUDED.first_name,
            last_name = EXCLUDED.last_name,
            username = EXCLUDED.username,
            phone_number = COALESCE(
                EXCLUDED.phone_number,
                users.phone_number
            ),
            updated_at = NOW();
        """,
        telegram_id,
        first_name,
        last_name,
        username,
        phone_number,
    )


async def save_user_city(
    telegram_id: int,
    city: str,
) -> None:
    """Foydalanuvchi shahrini saqlash."""
    db = _require_pool()

    await db.execute(
        """
        INSERT INTO users (telegram_id, city)
        VALUES ($1, $2)
        ON CONFLICT (telegram_id)
        DO UPDATE SET
            city = EXCLUDED.city,
            updated_at = NOW();
        """,
        telegram_id,
        city,
    )


async def set_prayer_reminders(
    telegram_id: int,
    enabled: bool,
) -> None:
    """Namoz eslatmalarini bot va Mini App uchun bir xil saqlash."""
    db = _require_pool()

    await db.execute(
        """
        INSERT INTO users (
            telegram_id,
            prayer_reminders,
            prayer_reminders_enabled
        )
        VALUES ($1, $2, $2)
        ON CONFLICT (telegram_id)
        DO UPDATE SET
            prayer_reminders = EXCLUDED.prayer_reminders,
            prayer_reminders_enabled =
                EXCLUDED.prayer_reminders_enabled,
            updated_at = NOW();
        """,
        telegram_id,
        enabled,
    )


async def get_reminder_users() -> list[dict[str, Any]]:
    """Namoz eslatmalari yoqilgan foydalanuvchilarni olish."""
    db = _require_pool()

    rows = await db.fetch(
        """
        SELECT
            telegram_id,
            language,
            city,
            prayer_reminders_enabled
        FROM users
        WHERE prayer_reminders_enabled = TRUE
          AND city IS NOT NULL
          AND city <> '';
        """
    )

    return [dict(row) for row in rows]


async def claim_prayer_reminder(
    telegram_id: int,
    reminder_date: date,
    prayer_key: str,
) -> bool:
    """
    Eslatma yuborilishini takrorlanishdan himoya qilish.
    True qaytsa, ushbu eslatma uchun yozuv yaratildi.
    """
    db = _require_pool()

    result = await db.fetchval(
        """
        INSERT INTO prayer_reminder_log (
            telegram_id,
            reminder_date,
            prayer_key
        )
        VALUES ($1, $2, $3)
        ON CONFLICT (telegram_id, reminder_date, prayer_key)
        DO NOTHING
        RETURNING TRUE;
        """,
        telegram_id,
        reminder_date,
        prayer_key,
    )

    return result is True


async def release_prayer_reminder(
    telegram_id: int,
    reminder_date: date,
    prayer_key: str,
) -> None:
    """Yuborish muvaffaqiyatsiz bo'lsa, eslatma belgisini olib tashlash."""
    db = _require_pool()

    await db.execute(
        """
        DELETE FROM prayer_reminder_log
        WHERE telegram_id = $1
          AND reminder_date = $2
          AND prayer_key = $3;
        """,
        telegram_id,
        reminder_date,
        prayer_key,
    )
