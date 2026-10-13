import string
import random
from fastapi import FastAPI, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import init_db, SessionLocal, URLModel
from rate_limiter import check_rate_limit, redis_client

app = FastAPI(title="URL Shortener with Rate Limiting")


class URLCreate(BaseModel):
    url: HttpUrl


async def get_db():
    async with SessionLocal() as session:
        yield session


def generate_short_id(length=6):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


@app.on_event("startup")
async def startup_event():
    await init_db()


@app.post("/shorten")
async def shorten_url(
    request: Request, 
    url_data: URLCreate, 
    db: AsyncSession = Depends(get_db)
):
    # 1. Проверяем Rate Limit по IP пользователя
    client_ip = request.client.host
    await check_rate_limit(client_ip)

    # 2. Генерируем короткий ID и сохраняем в Postgres
    short_id = generate_short_id()
    new_url = URLModel(short_id=short_id, original_url=str(url_data.url))
    db.add(new_url)
    await db.commit()
    
    # 3. Инвалидируем кэш в Redis, если нужно (в данном случае просто отдаем ответ)
    return {"short_url": f"http://127.0.0.1:8000/{short_id}"}

@app.get("/{short_id}")
async def redirect_to_url(short_id: str, db: AsyncSession = Depends(get_db)):
    cache_key = f"url_cache:{short_id}"
    
    # 1. Пробуем получить ссылку из Redis (O(1) сложность, без похода в БД)
    cached_url = await redis_client.get(cache_key)
    if cached_url:
        return RedirectResponse(url=cached_url)

    # 2. Если в кэше нет - идем в Postgres
    result = await db.execute(select(URLModel).where(URLModel.short_id == short_id))
    db_url = result.scalar_one_or_none()
    
    if db_url is None:
        return {"error": "URL not found"}
        
    # 3. Сохраняем в кэш на 1 час (3600 секунд) для будущих запросов
    await redis_client.setex(cache_key, 3600, db_url.original_url)
    
    return RedirectResponse(url=db_url.original_url)