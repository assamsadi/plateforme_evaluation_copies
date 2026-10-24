import asyncio, uuid
from app.infra_services.storage_service import storage_service

async def test():
    client = storage_service._get_client()
    print("URL:", client.url)
    
asyncio.run(test())
