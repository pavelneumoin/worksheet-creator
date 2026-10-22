"""Library integration tests with signed offline MAX identities, no real bot token."""
import unittest

import test_personal as personal
from utils import workspace_store
from utils.worksheet import demo_worksheet


class LibraryTests(unittest.TestCase):
    setUp = personal.PersonalTests.setUp
    login = personal.PersonalTests.login
    signed = personal.PersonalTests.signed
    call = personal.PersonalTests.call
    create = personal.PersonalTests.create

    def publish(self, worksheet=None, author='Николай С.'):
        if worksheet:
            material = self.call(self.client, 'post', '/api/v2/materials', json={'worksheet': worksheet}).json['material']
        else:
            material = self.create()
        response = self.call(self.client, 'post', '/api/v2/materials/' + material['id'] + '/publish',
                             json={'revision': material['revision'], 'author': author,
                                   'description': 'Практика для урока', 'reviewed': True})
        self.assertEqual(response.status_code, 201, response.json)
        return material, response.json['publication']

    def detail(self, client, pub):
        return self.call(client, 'get', '/api/v2/library/' + pub['id'])

    def rate(self, client, pub, stars):
        return self.call(client, 'put', '/api/v2/library/' + pub['id'] + '/rating', json={'stars': stars})

    def copy(self, client, pub):
        return self.call(client, 'post', '/api/v2/library/' + pub['id'] + '/copy')

    def test_publication_requires_owner_review_and_current_revision(self):
        material = self.create()
        path = '/api/v2/materials/' + material['id'] + '/publish'
        body = {'author': 'Автор', 'revision': 1, 'reviewed': True}
        self.assertEqual(self.call(self.other, 'post', path, json=body).status_code, 404)
        for change, code in [({'reviewed': False}, 400), ({'reviewed': 1}, 400), ({'revision': 0}, 409),
                             ({'revision': True}, 409), ({'author': ''}, 400), ({'author': 'a' * 81}, 400),
                             ({'description': 'a' * 601}, 400)]:
            with self.subTest(change=change):
                self.assertEqual(self.call(self.client, 'post', path, json={**body, **change}).status_code, code)
        self.assertEqual(self.call(self.client, 'post', path, json=body).status_code, 201)
        self.assertEqual(self.call(self.client, 'post', path, json=body).status_code, 409)

    def test_snapshot_does_not_publish_private_headers_files_or_draft_edits(self):
        worksheet = demo_worksheet('math')
        worksheet['teacher_name'] = 'Личное имя из печатного листа'
        material, pub = self.publish(worksheet)
        self.assertEqual(pub['worksheet']['teacher_name'], '')
        self.assertNotIn('owner_id', pub)
        self.assertNotIn('material_id', pub)
        self.assertNotIn('result', pub)
        worksheet['title'] = 'Изменённый личный черновик'
        response = self.call(self.client, 'put', '/api/v2/materials/' + material['id'],
                             json={'worksheet': worksheet, 'revision': 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['material']['publication_id'], pub['id'])
        self.assertNotEqual(self.detail(self.other, pub).json['publication']['title'], worksheet['title'])
        self.assertEqual(self.call(self.other, 'get', '/api/v2/materials/' + material['id']).status_code, 404)
        listing = self.call(self.other, 'get', '/api/v2/library').json['publications'][0]
        self.assertNotIn('worksheet', listing)

    def test_library_requires_session_and_mutations_require_csrf(self):
        material, pub = self.publish()
        for method, path in [('get', '/api/v2/library'), ('get', '/api/v2/library/' + pub['id']),
                             ('post', '/api/v2/library/' + pub['id'] + '/copy'),
                             ('put', '/api/v2/library/' + pub['id'] + '/rating'),
                             ('delete', '/api/v2/library/' + pub['id']),
                             ('post', '/api/v2/materials/' + material['id'] + '/publish')]:
            self.assertEqual(self.call(self.anon, method, path).status_code, 401)
        response = self.call(self.other, 'put', '/api/v2/library/' + pub['id'] + '/rating',
                             json={'stars': 5}, headers={'X-CSRF-Token': 'wrong'})
        self.assertEqual(response.status_code, 403)

    def test_one_rating_per_profile_can_be_changed_across_devices(self):
        _, pub = self.publish()
        self.assertIsNone(pub['rating'])
        self.assertEqual(self.rate(self.other, pub, 5).status_code, 200)
        device = self.app.test_client()
        self.login(device, 22)
        updated = self.rate(device, pub, 3).json['publication']
        self.assertEqual((updated['rating'], updated['rating_count'], updated['my_rating']), (3, 1, 3))
        third = self.app.test_client()
        self.login(third, 33)
        final = self.rate(third, pub, 4).json['publication']
        self.assertEqual((final['rating'], final['rating_count']), (3.5, 2))
        self.assertIsNone(self.detail(self.client, pub).json['publication']['my_rating'])

    def test_self_rating_invalid_stars_and_foreign_withdraw_are_rejected(self):
        _, pub = self.publish()
        self.assertEqual(self.rate(self.client, pub, 5).status_code, 403)
        for stars in (True, False, 0, 6, '5', 4.5, None, [], {}):
            self.assertEqual(self.rate(self.other, pub, stars).status_code, 400)
        self.assertEqual(self.call(self.other, 'delete', '/api/v2/library/' + pub['id']).status_code, 404)
        self.assertEqual(self.detail(self.other, pub).status_code, 200)

    def test_copy_creates_private_draft_preserves_attribution_and_counts_people(self):
        original, pub = self.publish()
        copied = self.copy(self.other, pub)
        self.assertEqual(copied.status_code, 201)
        material = copied.json['material']
        self.assertIsNone(material['result'])
        self.assertEqual(material['source'], 'community')
        self.assertEqual(material['origin']['author'], pub['author'])
        self.assertEqual(self.call(self.client, 'get', '/api/v2/materials/' + material['id']).status_code, 404)
        material['worksheet']['title'] = 'Моя практика'
        changed = self.call(self.other, 'put', '/api/v2/materials/' + material['id'],
                            json={'worksheet': material['worksheet'], 'revision': 1, 'source': 'community'})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.detail(self.other, pub).json['publication']['title'], pub['title'])
        self.copy(self.other, pub)
        self.copy(self.client, pub)
        self.assertEqual(self.detail(self.other, pub).json['publication']['copies'], 1)
        self.assertEqual(self.call(self.client, 'get', '/api/v2/materials/' + original['id']).status_code, 200)

    def test_withdrawal_keeps_personal_copies_and_resets_ratings_on_republication(self):
        material, pub = self.publish()
        self.rate(self.other, pub, 5)
        copy = self.copy(self.other, pub).json['material']
        self.assertEqual(self.call(self.client, 'delete', '/api/v2/library/' + pub['id']).status_code, 200)
        self.assertEqual(self.detail(self.other, pub).status_code, 404)
        self.assertEqual(self.rate(self.other, pub, 4).status_code, 404)
        self.assertEqual(self.copy(self.other, pub).status_code, 404)
        saved = self.call(self.other, 'get', '/api/v2/materials/' + copy['id']).json['material']
        self.assertEqual(saved['origin']['author'], pub['author'])
        self.assertIsNone(saved['origin']['publication_id'])
        response = self.call(self.client, 'post', '/api/v2/materials/' + material['id'] + '/publish',
                             json={'revision': 1, 'author': 'Автор', 'reviewed': True})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['publication']['rating_count'], 0)
        self.assertNotEqual(response.json['publication']['id'], pub['id'])

    def test_deleting_source_withdraws_publication_without_deleting_others_copies(self):
        material, pub = self.publish()
        copy = self.copy(self.other, pub).json['material']
        deleted = self.call(self.client, 'delete', '/api/v2/materials/' + material['id'], json={'revision': 1})
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.detail(self.other, pub).status_code, 404)
        self.assertEqual(self.call(self.other, 'get', '/api/v2/materials/' + copy['id']).status_code, 200)

    def test_search_is_case_insensitive_and_filters_and_sort_use_real_ratings(self):
        math = demo_worksheet('math'); math['title'] = 'ДРОБИ 100%'; math['grade'] = '7А'
        _, first = self.publish(math, 'Николай')
        _, second = self.publish(demo_worksheet('physics'), 'Таисия')
        self.rate(self.other, first, 4); self.rate(self.other, second, 5)
        self.copy(self.other, first)
        for query in ('дроби', '100%25', 'николай', '7а'):
            rows = self.call(self.other, 'get', '/api/v2/library?q=' + query).json['publications']
            self.assertEqual([row['id'] for row in rows], [first['id']])
        self.assertEqual(self.call(self.other, 'get', '/api/v2/library?q=%27%20OR%201%3D1').json['total'], 0)
        rows = self.call(self.other, 'get', '/api/v2/library').json['publications']
        self.assertEqual([row['id'] for row in rows], [second['id'], first['id']])
        rows = self.call(self.other, 'get', '/api/v2/library?sort=copies').json['publications']
        self.assertEqual(rows[0]['id'], first['id'])
        self.assertEqual(self.call(self.other, 'get', '/api/v2/library?subject=physics').json['total'], 1)
        self.assertEqual(self.call(self.other, 'get', '/api/v2/library?sort=mine').json['total'], 0)
        self.assertEqual(self.call(self.client, 'get', '/api/v2/library?sort=mine').json['total'], 2)

    def test_invalid_filters_and_pagination_are_bounded(self):
        for query in ('page=0', 'page=-1', 'page=bad', 'page=10001', 'subject=chemistry', 'sort=owner_id', 'q=' + 'a' * 161):
            self.assertEqual(self.call(self.other, 'get', '/api/v2/library?' + query).status_code, 400)
        for _ in range(13):
            self.publish()
        first = self.call(self.other, 'get', '/api/v2/library?sort=new').json
        second = self.call(self.other, 'get', '/api/v2/library?sort=new&page=2').json
        self.assertEqual((first['total'], len(first['publications']), first['has_more']), (13, 12, True))
        self.assertEqual((len(second['publications']), second['has_more']), (1, False))
        self.assertNotIn(second['publications'][0]['id'], {x['id'] for x in first['publications']})

    def test_copy_of_saved_derivative_retains_origin_and_cannot_borrow_foreign_origin(self):
        _, pub = self.publish()
        original = self.copy(self.other, pub).json['material']
        body = {'worksheet': original['worksheet'], 'source': 'community', 'origin_material_id': original['id']}
        self.assertEqual(self.call(self.client, 'post', '/api/v2/materials', json=body).status_code, 404)
        copy = self.call(self.other, 'post', '/api/v2/materials', json=body)
        self.assertEqual(copy.status_code, 201)
        self.assertEqual(copy.json['material']['origin'], original['origin'])
        derivative = self.call(self.other, 'post', '/api/v2/materials/' + copy.json['material']['id'] + '/publish',
                               json={'revision': 1, 'author': 'Коллега', 'reviewed': True})
        self.assertEqual(derivative.status_code, 201)
        self.assertEqual(derivative.json['publication']['origin']['author'], pub['author'])


if __name__ == '__main__':
    unittest.main()
