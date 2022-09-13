import json
import logging
import aioredis

from config import settings
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

class redisClass:
    
    def __init__(self):
        self.redis: Optional[aioredis.Redis] = None
        
    async def init(self) -> None :
        self.redis = await aioredis.from_url(settings.redis_url)
    
    async def close(self) -> None :
        self.redis_cache.close()
        await self.redis_cache.wait_closed()

    async def keys(self, pattern) -> List:
        return await self.redis.keys(pattern)

    async def set(self, key, value) -> Dict:
        return await self.redis.set(key, json.dumps(value))
    
    async def setex(self, key, value, seconds=300000) -> Dict: 
        return await self.redis.setex(key, seconds, json.dumps(value))

    async def delete(self, key):
        await self.redis.delete(key)

    async def get(self, key) -> Dict:
        resp = await self.redis.get(key)
        if resp:
            return json.loads(resp)
        return None

    async def lpop(self, key) -> Dict:
        resp = await self.redis.lpop(key)
        if resp:
            return json.loads(resp)
        return None

    async def rpop(self, key)  -> Dict :
        resp = await self.redis.rpop(key)
        if resp:
            return json.loads(resp)
        return None
    
    async def lpush(self, key, value)  -> Dict:
        return await self.redis.lpush(key, json.dumps(value))

    async def lrange(self, list) -> List: 
        return await self.redis.lrange(list, 0, -1)