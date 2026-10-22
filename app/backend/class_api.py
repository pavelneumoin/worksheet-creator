"""Teacher-owned classes, rosters and fixed worksheet assignments."""
from flask import Blueprint, g, jsonify, request
from utils import class_store
from utils.gigachat_client import AIServiceError

api = Blueprint('classes', __name__, url_prefix='/api/v2')


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise AIServiceError('Не удалось прочитать запрос.', 'invalid_json', 400)
    return value


@api.get('/classes')
def classes():
    return jsonify(classes=class_store.list_classes(g.identity['owner_id']))


@api.post('/classes')
def create():
    return jsonify(classroom=class_store.create_class(g.identity['owner_id'], body())), 201


@api.get('/classes/<class_id>')
def detail(class_id):
    return jsonify(classroom=class_store.get_class(g.identity['owner_id'], class_id))


@api.put('/classes/<class_id>')
def update(class_id):
    return jsonify(classroom=class_store.update_class(g.identity['owner_id'], class_id, body()))


@api.post('/classes/<class_id>/students')
def add_students(class_id):
    return jsonify(classroom=class_store.add_students(g.identity['owner_id'], class_id, body())), 201


@api.put('/classes/<class_id>/students/<student_id>')
def update_student(class_id, student_id):
    return jsonify(classroom=class_store.update_student(g.identity['owner_id'], class_id, student_id, body()))


@api.post('/classes/<class_id>/assignments')
def assign(class_id):
    assignment, created = class_store.assign(g.identity['owner_id'], class_id, body())
    return jsonify(assignment=assignment), 201 if created else 200


@api.get('/assignments/<assignment_id>')
def assignment(assignment_id):
    return jsonify(assignment=class_store.get_assignment(g.identity['owner_id'], assignment_id))


@api.put('/assignments/<assignment_id>')
def update_assignment(assignment_id):
    return jsonify(assignment=class_store.update_assignment(g.identity['owner_id'], assignment_id, body()))
