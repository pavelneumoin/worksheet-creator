"""Ownership, immutable editions and disaster recovery with real SQLite/files."""
import json
import os
from pathlib import Path
import sqlite3
import time
import unittest
from unittest.mock import Mock
import uuid
import zipfile
from contextlib import closing

import test_personal as personal
from utils import backup, db, job_store, workspace_store, provider_files
from utils.worksheet import demo_worksheet, validate_worksheet, edition_code
from utils.gigachat_client import AIServiceError


class CabinetTests(unittest.TestCase):
    setUp = personal.PersonalTests.setUp
    call = personal.PersonalTests.call
    signed = personal.PersonalTests.signed
    login = personal.PersonalTests.login
    create = personal.PersonalTests.create

    def compiled(self, material=None):
        material = material or self.create()
        job, _ = job_store.submit('max:11', 'compile', uuid.uuid4().hex,
            {'worksheet': material['worksheet'], 'material_id': material['id'], 'revision': material['revision']}, require_worker=False)
        claim = job_store.claim_next('compile')
        for suffix in ('.pdf', '_keys.pdf', '.tex', '_marp.zip'):
            Path(self.temp.name, 'job_' + job['id'] + suffix).write_bytes(b'fixture-file')
        job_store.complete(claim, {})
        return material, job['id']

    def test_folder_archive_is_private_persistent_and_does_not_change_revision(self):
        m = self.create(); url = '/api/v2/materials/' + m['id'] + '/organization'
        body = {'folder':'8А · Физика', 'archived':True}
        self.assertEqual(self.call(self.other, 'put', url, json=body).status_code, 404)
        response = self.call(self.client, 'put', url, json=body)
        self.assertEqual(response.json['material']['folder'], body['folder'])
        self.login(self.client, 11)
        material = self.call(self.client, 'get', '/api/v2/materials/' + m['id']).json['material']
        self.assertTrue(material['archived']); self.assertEqual(material['revision'], 1)
        for invalid in ({'folder':'x'*61,'archived':False}, {'folder':'a','archived':'false'}):
            self.assertEqual(self.call(self.client,'put',url,json=invalid).status_code,400)

    def test_editions_survive_changes_and_are_never_exposed_to_other_owner(self):
        m, artifact = self.compiled()
        changed = dict(m['worksheet'], title='Изменённая тема')
        self.call(self.client, 'put', '/api/v2/materials/' + m['id'], json={'worksheet':changed, 'revision':1})
        url = '/api/v2/materials/' + m['id'] + '/editions'
        self.assertEqual(self.call(self.other, 'get', url).status_code,404)
        version = self.call(self.client, 'get', url).json['editions'][0]
        self.assertEqual(version['worksheet'], m['worksheet'])
        self.assertEqual(version['code'], edition_code(m['worksheet']))
        self.assertNotEqual(version['code'], edition_code(changed))
        self.assertTrue(workspace_store.owns_file('max:11', 'job_' + artifact + '.pdf'))
        self.assertIsNone(workspace_store.get_material('max:11', m['id'])['result'])
        bad = self.call(self.client,'put','/api/v2/materials/'+m['id'],json={'worksheet':changed,'revision':2,'artifact_id':artifact})
        self.assertEqual(bad.status_code,409)

    def test_deleting_material_deletes_all_edition_files(self):
        m, first = self.compiled()
        m, second = self.compiled(m)
        response = self.call(self.client,'delete','/api/v2/materials/'+m['id'],json={'revision':1})
        self.assertEqual(response.status_code,200)
        for artifact in (first,second):
            self.assertFalse(Path(self.temp.name,'job_'+artifact+'.pdf').exists())
            self.assertFalse(workspace_store.owns_file('max:11','job_'+artifact+'.pdf'))

    def test_detached_edition_cannot_be_moved_out_of_original_history(self):
        m, artifact = self.compiled()
        workspace_store.put_material('max:11',m['worksheet'],'manual',m['id'],revision=1)
        with self.assertRaises(AIServiceError):
            workspace_store.put_material('max:11',m['worksheet'],'manual',artifact_id=artifact)
        self.assertEqual(workspace_store.list_editions('max:11',m['id'])[0]['id'],artifact)

    def test_legacy_settings_remain_queue_compatible(self):
        m = self.create()
        old = m['worksheet']; old['settings'] = {'columns':1,'tasks_per_page':3,'field':'grid'}
        with workspace_store.connection() as conn:
            conn.execute('UPDATE materials SET worksheet=? WHERE id=?',(json.dumps(old),m['id']))
        job, _ = job_store.submit('max:11','compile',uuid.uuid4().hex,{'material_id':m['id'],'revision':1,'worksheet':validate_worksheet(old)},require_worker=False)
        self.assertEqual(job['status'],'queued')

    def test_backup_restore_preserves_files_editions_and_revokes_sessions(self):
        m, artifact = self.compiled()
        job_store.submit('max:22','recognize',uuid.uuid4().hex,{'subject':'math','text':'a'},require_worker=False)
        archive = Path(self.temp.name,'snapshot.zip')
        backup.create_backup(archive)
        restored = Path(self.temp.name,'restore')
        backup.restore_backup(archive,restored)
        with closing(sqlite3.connect(restored/'worksheets.db')) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM editions').fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT status FROM jobs WHERE kind='recognize'").fetchone()[0],'failed')
        self.assertEqual((restored/'generated'/('job_'+artifact+'.pdf')).read_bytes(),b'fixture-file')
        with self.assertRaises(ValueError): backup.restore_backup(archive,restored)
        with self.assertRaises(ValueError): backup.create_backup(archive)
        # Live sessions and queue have not been altered by backup.
        self.assertEqual(self.call(self.client,'get','/api/v2/materials').status_code,200)
        self.assertEqual(job_store.list_jobs('max:22')[0]['status'],'queued')

    def test_restore_rejects_path_traversal_and_corruption_without_partial_directory(self):
        m, _ = self.compiled()
        archive = Path(self.temp.name,'backup.zip'); backup.create_backup(archive)
        corrupt = Path(self.temp.name,'corrupt.zip')
        with zipfile.ZipFile(archive) as original, zipfile.ZipFile(corrupt,'w') as altered:
            for name in original.namelist():
                altered.writestr(name, b'corrupt' if name.endswith('.pdf') else original.read(name))
        restored = Path(self.temp.name,'untrusted')
        with self.assertRaises(ValueError): backup.restore_backup(corrupt,restored)
        self.assertFalse(restored.exists())
        with zipfile.ZipFile(corrupt,'w') as altered: altered.writestr('../outside.txt',b'bad')
        with self.assertRaises(ValueError): backup.restore_backup(corrupt,restored)
        self.assertFalse(Path(self.temp.name,'outside.txt').exists())

    def test_cleanup_retains_editions_and_dry_run_never_deletes(self):
        m, artifact = self.compiled()
        old = time.time() - 40*86400
        for name in Path(self.temp.name).glob('job_*'): os.utime(name,(old,old))
        orphan = Path(self.temp.name,'orphan.pdf'); orphan.write_bytes(b'old'); os.utime(orphan,(old,old))
        self.assertEqual(backup.cleanup_generated()['files'],1)
        self.assertTrue(orphan.exists())
        backup.cleanup_generated(apply=True)
        self.assertFalse(orphan.exists())
        self.assertTrue(Path(self.temp.name,'job_'+artifact+'.pdf').exists())

    def test_provider_cleanup_only_tracked_old_ids_and_retries_failure(self):
        provider_files.uploaded('old'); provider_files.uploaded('recent')
        with workspace_store.connection() as conn: conn.execute('UPDATE provider_uploads SET created_at=0 WHERE file_id=?',('old',))
        client=Mock()
        self.assertEqual(provider_files.cleanup(client)['pending'],1); client.delete_file.assert_not_called()
        client.delete_file.side_effect=TimeoutError()
        self.assertEqual(provider_files.cleanup(client,True)['failed'],1)
        client.delete_file.side_effect=None
        self.assertEqual(provider_files.cleanup(client,True)['deleted'],1)
        self.assertEqual(provider_files.cleanup(client)['pending'],0)
        client.delete_file.assert_called_with('old')

    def test_invalid_layouts_and_dates_rejected(self):
        for settings in ({'template':'injected'}, {'lesson_date':'2026-02-30'}, {'print_sides':'arbitrary'}, {'variant':'x'*13}):
            sheet=demo_worksheet('math'); sheet['settings'].update(settings)
            with self.assertRaises(AIServiceError): validate_worksheet(sheet)
