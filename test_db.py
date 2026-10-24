
import asyncio
from database import connect_db, close_db


async def main():
    try:
        await connect_db()
    except Exception as error:
        print(f"Bazaga ulanish amalga oshmadi: {type(error).__name__}")
        raise
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
