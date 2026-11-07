"""Teacher feedback is editable, authenticated, and aggregated for the review panel."""
import unittest

import test_personal as personal


class FeedbackTests(unittest.TestCase):
    setUp = personal.PersonalTests.setUp
    call = personal.PersonalTests.call
    login = personal.PersonalTests.login
    signed = personal.PersonalTests.signed

    def test_feedback_requires_login_and_csrf(self):
        self.assertEqual(self.call(self.anon, 'get', '/api/v2/feedback').status_code, 401)
        self.assertEqual(self.call(self.client, 'get', '/api/v2/feedback').status_code, 200)
        response = self.call(self.client, 'post', '/api/v2/feedback', json={'stars': 5}, headers={'X-CSRF-Token': 'wrong'})
        self.assertEqual(response.status_code, 403)

    def test_feedback_is_validated_editable_and_listed(self):
        body = {'stars': 5, 'display_name': 'Анна К.', 'liked': 'Быстро собрать PDF',
                'inconvenient': 'Не сразу нашла очередь', 'improve': 'Добавить подсказку', 'recommend': True}
        response = self.call(self.client, 'post', '/api/v2/feedback', json=body)
        self.assertEqual(response.status_code, 201, response.json)
        self.assertEqual(response.json['feedback']['stars'], 5)
        second = {**body, 'stars': 4, 'improve': 'Сделать кнопку заметнее', 'recommend': False}
        response = self.call(self.client, 'post', '/api/v2/feedback', json=second)
        self.assertEqual(response.status_code, 201)
        listing = self.call(self.client, 'get', '/api/v2/feedback').json
        self.assertEqual(listing['summary']['count'], 1)
        self.assertEqual(listing['summary']['average'], 4.0)
        self.assertEqual(listing['summary']['recommend_count'], 0)
        self.assertEqual(listing['mine']['improve'], 'Сделать кнопку заметнее')

    def test_feedback_does_not_expose_owner_ids_and_rejects_bad_values(self):
        for body in ({'stars': 0}, {'stars': 6}, {'stars': True}, {'stars': 5, 'display_name': 'x' * 81},
                     {'stars': 5, 'recommend': 1}, {'stars': 5, 'liked': 'x' * 1201}):
            with self.subTest(body=body):
                self.assertEqual(self.call(self.client, 'post', '/api/v2/feedback', json=body).status_code, 400)
        self.call(self.client, 'post', '/api/v2/feedback', json={'stars': 3, 'display_name': 'Проверяющий'})
        item = self.call(self.client, 'get', '/api/v2/feedback').json['feedback'][0]
        self.assertNotIn('owner_id', item)
