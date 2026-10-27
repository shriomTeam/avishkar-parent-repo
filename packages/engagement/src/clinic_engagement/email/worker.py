"""Run only transactional email delivery: python -m clinic_engagement.email.worker [--once]."""

import argparse
import asyncio
import logging

from clinic_core.database import dispose_engines
from clinic_core.settings import EmailWorkerSettings
from clinic_engagement.email.tasks import dispatch_due


async def main(once=False):
    settings = EmailWorkerSettings()
    try:
        while True:
            count = await dispatch_due(settings, limit=20)
            metric = "email_tasks_published" if settings.email_tasks_queue else "email_provider_accepted"
            logging.getLogger("email.worker").info("%s=%d", metric, count)
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
