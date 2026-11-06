"""Deliver replies to explicitly requested private MAX commands from the durable inbox."""
import os
from pathlib import Path
import signal
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env', override=False)
from utils import bot_login, db, job_store, max_bot


def main():
    if not bot_login.enabled() or len(os.environ.get('MAX_WEBHOOK_SECRET', '')) < 32:
        raise SystemExit('Enable bot login and configure a webhook secret of at least 32 characters.')
    max_bot.app_origin()
    db.init_db()
    client = max_bot.Client()
    worker = 'bot-' + uuid.uuid4().hex
    stop = False

    def stopping(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    print('MAX bot worker ready', flush=True)
    try:
        while not stop:
            job_store.heartbeat(worker, 'bot')
            item = bot_login.claim()
            if item is None:
                time.sleep(1)
                continue
            try:
                max_bot.reply(client, item)
            except Exception as exc:
                bot_login.finish(item['id'], False)
                # Exception details may contain outbound payloads; log only the class.
                print('MAX reply failed (' + type(exc).__name__ + '); a new /start can be requested.', flush=True)
            else:
                bot_login.finish(item['id'], True)
                print('MAX private command processed', flush=True)
    finally:
        client.close()


if __name__ == '__main__':
    main()
