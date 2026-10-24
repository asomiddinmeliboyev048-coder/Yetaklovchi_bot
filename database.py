
import os
import asyncpg
import logging

from datetime import date
from typing import Optional, Any

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

pool: Optional[asyncpg.Pool] = None


async def connect_db():
    """PostgreSQL bazasiga ulanadi va kerakli jadvallarni tayyorlaydi."""
    global pool

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL topilmadi. .env faylini tekshiring."
        )

    pool = await asyncpg.create_pool(
        DATABASE_URL,
        min_size=1,
        max_size=5,
        command_timeout=30,
    )

    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                language VARCHAR(10) NOT NULL DEFAULT 'uz',
                city VARCHAR(100),
                prayer_reminders BOOLEAN NOT NULL DEFAULT TRUE,
                daily_reminders BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # Eski bazalarga ham yangi ustunni xavfsiz qo'shadi.
        await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS
            prayer_reminders_enabled BOOLEAN NOT NULL DEFAULT FALSE;
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS prayer_reminder_log (
                id BIGSERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL
                    REFERENCES users(telegram_id)
                    ON DELETE CASCADE,
                reminder_date DATE NOT NULL,
                prayer_key VARCHAR(20) NOT NULL,
                sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (telegram_id, reminder_date, prayer_key)
            );
        """)

    logger.info("PostgreSQL bazasiga ulanish muvaffaqiyatli!")


async def close_db():
    """Baza ulanishini yopadi."""
    global pool

    if pool is not None:
        await pool.close()
        pool = None
        logger.info("PostgreSQL ulanishi yopildi.")


def _require_pool() -> asyncpg.Pool:
    """Baza pool'i mavjudligini tekshiradi."""
    if pool is None:
        raise RuntimeError(
            "Baza bilan ulanish mavjud emas. Avval connect_db() chaqiring."
        )

    return pool


async def save_user(
    telegram_id: int,
    language: str = "uz",
) -> None:
    """Foydalanuvchini yaratadi yoki tilini yangilaydi."""
    db = _require_pool()

    if language not in ("uz", "uz_cyr"):
        language = "uz"

    async with db.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, language)
            VALUES ($1, $2)
            ON CONFLICT (telegram_id)
            DO UPDATE SET
                language = EXCLUDED.language,
                updated_at = NOW();
        """, telegram_id, language)


async def get_user(telegram_id: int) -> Optional[dict[str, Any]]:
    """Foydalanuvchi ma'lumotlarini qaytaradi."""
    db = _require_pool()

    async with db.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT
                telegram_id,
                language,
                city,
                prayer_reminders,
                daily_reminders,
                prayer_reminders_enabled,
                created_at,
                updated_at
            FROM users
            WHERE telegram_id = $1;
        """, telegram_id)

    return dict(row) if row else None


async def save_user_city(
    telegram_id: int,
    city: str,
) -> None:
    """Foydalanuvchining shahrini saqlaydi."""
    db = _require_pool()

    async with db.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (telegram_id, city)
            VALUES ($1, $2)
            ON CONFLICT (telegram_id)
            DO UPDATE SET
                city = EXCLUDED.city,
                updated_at = NOW();
        """, telegram_id, city)


async def set_prayer_reminders(
    telegram_id: int,
    enabled: bool,
) -> None:
    """Namoz eslatmalarini yoqadi yoki o'chiradi."""
    db = _require_pool()

    async with db.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (
                telegram_id,
                prayer_reminders_enabled
            )
            VALUES ($1, $2)
            ON CONFLICT (telegram_id)
            DO UPDATE SET
                prayer_reminders_enabled = EXCLUDED.prayer_reminders_enabled,
                updated_at = NOW();
        """, telegram_id, enabled)


async def get_reminder_users() -> list[dict[str, Any]]:
    """Eslatmalarni yoqqan va shahri saqlangan foydalanuvchilarni oladi."""
    db = _require_pool()

    async with db.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                telegram_id,
                language,
                city,
                prayer_reminders_enabled
            FROM users
            WHERE prayer_reminders_enabled = TRUE
              AND city IS NOT NULL
              AND TRIM(city) <> '';
        """)

    return [dict(row) for row in rows]


async def claim_prayer_reminder(
    telegram_id: int,
    reminder_date: date,
    prayer_key: str,
) -> bool:
    """
    Bir namoz uchun shu kuni takroriy yuborishni cheklaydi.
    True — qayd yaratildi; False — bu namoz avval qayd etilgan.
    """
    db = _require_pool()

    async with db.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO prayer_reminder_log (
                telegram_id,
                reminder_date,
                prayer_key
            )
            VALUES ($1, $2, $3)
            ON CONFLICT (
                telegram_id,
                reminder_date,
                prayer_key
            ) DO NOTHING
            RETURNING id;
        """, telegram_id, reminder_date, prayer_key)

    return row is not None


async def release_prayer_reminder(
    telegram_id: int,
    reminder_date: date,
    prayer_key: str,
) -> None:
    """Yuborish xato bilan tugasa, qaydini o'chirib, qayta urinishga imkon beradi."""
    db = _require_pool()

    async with db.acquire() as conn:
        await conn.execute("""
            DELETE FROM prayer_reminder_log
            WHERE telegram_id = $1
              AND reminder_date = $2
              AND prayer_key = $3;
        """, telegram_id, reminder_date, prayer_key)
