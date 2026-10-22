"""Server-side MAX launch signature and freshness verification."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from utils.gigachat_client import AIServiceError


def validate_init_data(raw, bot_token, now=None):
    def reject():
        raise AIServiceError("Откройте приложение заново через бота MAX.", "max_auth_invalid", 401)
    if not isinstance(raw, str) or not raw or len(raw) > 16384 or not bot_token:
        reject()
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(pairs) != len(data):
            reject()
        signature = data.pop("hash")
        payload = "\n".join(f"{key}={data[key]}" for key in sorted(data))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            reject()
        age = (time.time() if now is None else now) - int(data["auth_date"])
        if not -30 <= age <= 3600:
            reject()
        user = json.loads(data["user"])
        if not isinstance(user, dict) or type(user.get("id")) is not int or user["id"] <= 0:
            reject()
        return {"id": user["id"], "first_name": str(user.get("first_name", ""))[:100]}
    except (ValueError, KeyError, TypeError):
        reject()
