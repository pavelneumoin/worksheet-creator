"""Authenticated MAX webhook: durable acceptance before any outbound API call."""
import hmac
import os

from flask import Blueprint, jsonify, request
from utils import bot_login

api = Blueprint('max_bot', __name__)


@api.post('/api/max/webhook')
def webhook():
    secret = os.environ.get('MAX_WEBHOOK_SECRET', '')
    supplied = request.headers.get('X-Max-Bot-Api-Secret', '')
    if (not bot_login.enabled() or len(secret) < 32 or len(supplied) > 256
            or not hmac.compare_digest(secret.encode(), supplied.encode())):
        return jsonify(ok=False), 403
    if request.content_length is not None and request.content_length > 65536:
        return jsonify(ok=False), 413
    # Flask also bounds bodies without a Content-Length header.
    request.max_content_length = 65536
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(ok=False), 400
    bot_login.enqueue(data)
    return jsonify(ok=True)
