import asyncio
import time
from typing import Any, AsyncGenerator
from httpx import AsyncClient, Timeout
from contextlib import asynccontextmanager


class APIConfig:
    def __init__(self):
        self.timeout = Timeout(600)
        self.proxy_pool = [
            "http://user401975:if26ez@85.115.208.50:4990",
            "http://fZM3hu:eC4AoG@196.18.13.244:8000",
            "http://URwNZhR2C:7mGvYF6KK@154.81.198.239:64804"
                           ]
        self.client = None
        self.url_to_ping = "https://api.ipify.org"

        self.working_proxy = []


    def create_client(self, proxy: str) -> AsyncClient:
        if self.client is None:
            self.client = AsyncClient(timeout=self.timeout, proxy=proxy)
        return self.client


    @asynccontextmanager
    async def get_session(self) -> AsyncGenerator[Any, Any]:
        async with self.client() as session:
            yield session


    async def get_actual_proxy_list(self):
        await self.ping_proxy_list()
        return self.working_proxy


    async def ping_proxy(self, proxy: str):
        start = time.perf_counter()

        try:
            async with AsyncClient(
                proxy=proxy,
                timeout=10
            ) as client:

                response = await client.get(self.url_to_ping)

                latency = round(
                    (time.perf_counter() - start) * 1000,
                    2
                )

                return {
                    "proxy": proxy,
                    "latency": latency,
                    "ip": response.text.strip()
                }

        except Exception:
            return None


    async def ping_proxy_list(self):
        results = await asyncio.gather(
            *(self.ping_proxy(proxy) for proxy in self.proxy_pool)
        )

        working = [r for r in results if r is not None]
        working.sort(key=lambda x: x["latency"])

        self.working_proxy = [
            proxy_info["proxy"]
            for proxy_info in working
        ]

        return self.working_proxy


