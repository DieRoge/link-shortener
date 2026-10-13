import redis.asyncio as redis
import time
from fastapi import HTTPException

redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

# Lua-скрипт для атомарного Token Bucket
# ARGV[1] - rate (токенов в секунду)
# ARGV[2] - capacity (максимум токенов)
# ARGV[3] - текущее время в секундах
TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = 1

local info = redis.call('HMGET', key, 'tokens', 'last_refresh')
local tokens = tonumber(info[1])
local last_refresh = tonumber(info[2])

if not tokens then
    tokens = capacity
    last_refresh = now
end

local delta = math.max(0, now - last_refresh)
local generated = math.floor(delta * rate)
tokens = math.min(capacity, tokens + generated)

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refresh', now)
    redis.call('EXPIRE', key, math.ceil(capacity/rate))
    return 1
else
    return 0
end
"""


async def check_rate_limit(client_ip: str):
    capacity = 10  
    rate = 1       
    now = int(time.time())

    key = f"rate_limit:{client_ip}"

    allowed = await redis_client.eval(
        TOKEN_BUCKET_SCRIPT, 1, key, rate, capacity, now
    )

    if not allowed:
        raise HTTPException(status_code=429, detail="Too Many Requests. Rate limit exceeded.")