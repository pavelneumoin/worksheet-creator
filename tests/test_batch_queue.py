import copy
import json
import time
from unittest.mock import patch
import unittest

import test_batch_review as batches
from utils import batch_queue,batch_review,review_store,workspace_store


class QueueTests(unittest.TestCase):
    setUp=batches.BatchReviewTests.setUp
    call=batches.BatchReviewTests.call
    signed=batches.BatchReviewTests.signed
    login=batches.BatchReviewTests.login
    create=batches.BatchReviewTests.create
    compiled=batches.BatchReviewTests.compiled
    classroom=batches.BatchReviewTests.classroom
    assignment=batches.BatchReviewTests.assignment
    ready_batch=batches.BatchReviewTests.ready_batch

    def fixture(self):
        a,b,_=self.ready_batch()
        with workspace_store.connection() as c:
            pages=json.loads(c.execute('SELECT pages FROM review_batches WHERE id=?',(b['id'],)).fetchone()[0])
            for p in pages:p['assignment_code']=a['id']
            pages[0]['answers'][0].update(text='999',state='readable')
            pages[1]['answers'][1].update(text='',state='blank')
            c.execute('UPDATE review_batches SET pages=? WHERE id=?',(json.dumps(pages),b['id']))
        return a,b

    def prepare(self,b):
        r=self.call(self.client,'post',f"/api/v2/batches/{b['id']}/queue/prepare",json={'revision':b['revision'],'mapping_reviewed':True})
        self.assertEqual(r.status_code,200,r.json)
        return r.json['queue']

    def test_whole_batch_drafts_progress_and_confirmed_only_statistics(self):
        a,b=self.fixture();q=batch_queue.get('max:11',b['id'])
        self.assertEqual(len(q['proposals']),2);self.assertEqual(q['remaining'],0)
        q=self.prepare(b);self.assertEqual(q['remaining'],2)
        self.assertEqual({i['reason'] for i in q['items']},{'compare','empty'})
        self.assertEqual(len(q['reviews']),2)
        review=review_store.get_review('max:11',q['items'][0]['review_id'])
        answers=copy.deepcopy(review['answers']);answers[0].update(score=.5,checked=True)
        body={'revision':review['revision'],'answers':answers,'comment':'РџСЂРѕРІРµСЂРєР° РѕС‡РµСЂРµРґРё','draft_revision':None}
        draft=review_store.save_draft('max:11',review['id'],body)
        q=batch_queue.get('max:11',b['id']);self.assertEqual(q['remaining'],1);self.assertEqual(q['ready'],1)
        self.assertEqual(review_store.report('max:11',a['id'])['summary']['confirmed'],0)
        self.assertEqual(q['resolved'],1)
        # A saved checkbox without a score never hides an answer.
        answers[0].update(score=None,checked=True)
        body.update(answers=answers,draft_revision=draft['revision'])
        draft=review_store.save_draft('max:11',review['id'],body)
        self.assertEqual(batch_queue.get('max:11',b['id'])['remaining'],2)
        answers[0].update(score=.5,checked=True)
        body.update(draft_revision=draft['revision'],reviewed=True,action='confirm')
        review_store.update('max:11',review['id'],body)
        q=batch_queue.get('max:11',b['id']);self.assertEqual(q['confirmed'],1);self.assertEqual(q['remaining'],1)
        report=review_store.report('max:11',a['id']);self.assertEqual(report['summary']['confirmed'],1)
        self.assertEqual(report['summary']['average'],len(answers)-.5)

    def test_access_csrf_mapping_consent_and_stale_retry(self):
        _,b=self.fixture();base=f"/api/v2/batches/{b['id']}/queue"
        self.assertEqual(self.call(self.other,'get',base).status_code,404)
        self.assertEqual(self.call(self.anon,'get',base).status_code,401)
        self.assertEqual(self.call(self.other,'post',base+'/prepare',json={'revision':b['revision'],'mapping_reviewed':True}).status_code,404)
        self.assertEqual(self.call(self.client,'post',base+'/prepare',json={'revision':b['revision']}).status_code,400)
        self.assertEqual(self.call(self.client,'post',base+'/prepare',headers={'X-CSRF-Token':'bad'},json={}).status_code,403)
        q=self.prepare(b)
        self.assertEqual(self.call(self.client,'post',base+'/prepare',json={'revision':b['revision'],'mapping_reviewed':True}).status_code,409)
        repeated=self.prepare(q);self.assertEqual(len(repeated['reviews']),2)

    def test_ambiguous_or_missing_qr_not_automatically_mapped(self):
        _,b,_=self.ready_batch()
        q=batch_queue.get('max:11',b['id']);self.assertEqual(len(q['blocked']),2);self.assertFalse(q['proposals'])
        self.assertFalse(self.prepare(b)['reviews'])

    def test_repeated_code_foreign_marker_or_existing_work_is_blocked(self):
        a,b=self.fixture()
        with workspace_store.connection() as c:
            pages=json.loads(c.execute('SELECT pages FROM review_batches WHERE id=?',(b['id'],)).fetchone()[0])
            pages[1]['suggested_student_id']=pages[0]['suggested_student_id']
            c.execute('UPDATE review_batches SET pages=? WHERE id=?',(json.dumps(pages),b['id']))
        self.assertFalse(batch_queue.get('max:11',b['id'])['proposals'])
        self.assertFalse(self.prepare(b)['reviews'])

    def test_partial_prepare_failure_rolls_back_rows_and_new_files(self):
        _,b=self.fixture();original=batch_review.attach_pages;calls=[]
        def fail_second(*args,**kwargs):
            result=original(*args,**kwargs);calls.append(result)
            if len(calls)==2:raise RuntimeError('simulated failure after copying scan')
            return result
        with patch.object(batch_review,'attach_pages',side_effect=fail_second):
            with self.assertRaises(RuntimeError):batch_queue.prepare('max:11',b['id'],{'revision':b['revision'],'mapping_reviewed':True})
        with workspace_store.connection() as c:self.assertEqual(c.execute('SELECT count(*) FROM reviews').fetchone()[0],0)
        self.assertFalse(list(review_store.photo_root().glob('*/*.jpg')))
        self.assertEqual(len(batch_queue.get('max:11',b['id'])['proposals']),2)

    def test_delete_draft_releases_page_and_expired_scans_are_not_attached(self):
        _,b=self.fixture();q=self.prepare(b)
        r=review_store.get_review('max:11',q['reviews'][0]['id'])
        review_store.remove('max:11',r['id'],r['revision'])
        q=batch_queue.get('max:11',b['id']);self.assertEqual(len(q['proposals']),1)
        with workspace_store.connection() as c:c.execute('UPDATE review_batches SET expires_at=? WHERE id=?',(time.time()-1,b['id']))
        q=batch_queue.get('max:11',b['id']);self.assertTrue(q['expired']);self.assertFalse(q['proposals'])
        self.assertEqual(self.call(self.client,'post',f"/api/v2/batches/{b['id']}/queue/prepare",json={'revision':q['revision'],'mapping_reviewed':True}).status_code,410)

    def test_confirmed_corrections_and_stale_draft_are_not_silently_skipped(self):
        _,b=self.fixture();q=self.prepare(b);r=review_store.get_review('max:11',q['reviews'][0]['id'])
        body={'revision':r['revision'],'answers':[dict(a,score=1) for a in r['answers']],'reviewed':True,'action':'confirm'}
        r=review_store.update('max:11',r['id'],body)
        body={'revision':r['revision'],'answers':[dict(a,checked=False) for a in r['answers']]}
        review_store.save_draft('max:11',r['id'],body)
        q=batch_queue.get('max:11',b['id']);self.assertEqual(q['confirmed'],0)
        self.assertTrue(any(i['review_id']==r['id'] for i in q['items']))
        with workspace_store.connection() as c:c.execute('UPDATE review_drafts SET base_revision=0 WHERE review_id=?',(r['id'],))
        q=batch_queue.get('max:11',b['id']);self.assertFalse(next(v for v in q['reviews'] if v['id']==r['id'])['usable'])


if __name__=='__main__':unittest.main()
