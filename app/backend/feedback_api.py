from flask import Blueprint, g, jsonify, request
from utils import feedback_store

api = Blueprint('feedback', __name__, url_prefix='/api/v2')

@api.get('/feedback')
def list_feedback():
    return jsonify(**feedback_store.list_feedback(g.identity['owner_id']))

@api.post('/feedback')
def save_feedback():
    return jsonify(feedback=feedback_store.save(g.identity['owner_id'], g.identity.get('first_name', ''), request.get_json(silent=True))), 201
