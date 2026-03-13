from __future__ import annotations

import asyncio
import logging

from voxagent.config import load_config
from voxagent.db import close_pool, init_pool
from voxagent.jobs.runner import run_job_batch

logger = logging.getLogger(__name__)


async def worker_loop() -> None:
    config = load_config()
    pool = await init_pool(config.database_url)
    try:
        while True:
            jobs = await run_job_batch(pool, config, limit=20)
            if not jobs:
                await asyncio.sleep(1.0)
    finally:
        await close_pool(pool)


def main() -> None:
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
