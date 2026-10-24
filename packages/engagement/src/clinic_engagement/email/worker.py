"""Run only transactional email delivery: python -m clinic_engagement.email.worker [--once]."""

import argparse
import asyncio
import logging

from clinic_core.database import dispose_engines
from clinic_core.settings import EmailWorkerSettings
from clinic_engagement.email.service import deliver_due


async def main(once=False):
    settings = EmailWorkerSettings()
    try:
        while True:
            count = await deliver_due(settings, limit=20)
            logging.getLogger("email.worker").info("email_provider_accepted=%d", count)
            if once:
                return
            await asyncio.sleep(10)
    finally:
        await dispose_engines()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(parser.parse_args().once))
