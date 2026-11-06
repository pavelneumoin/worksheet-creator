import json
from pathlib import Path
import unittest
import uuid
from PIL import Image
from pypdf import PdfWriter
import test_classes as classes
from utils import batch_review,job_store,review_store,workspace_store,backup,source_pages,class_store
from utils.gigachat_client import AIServiceError
from utils.worksheet import demo_worksheet,validate_worksheet,worksheet_tex,edition_code

class BatchReviewTests(unittest.TestCase):
    setUp=classes.ClassTests.setUp
    call=classes.ClassTests.call
    signed=classes.ClassTests.signed
    login=classes.ClassTests.login
    create=classes.ClassTests.create
    compiled=classes.ClassTests.compiled
    classroom=classes.ClassTests.classroom
    assignment=classes.ClassTests.assignment

    def ready_batch(self,wrong_version=False,partial=False,wrong_assignment=False):
        _,_,a,_=self.assignment()
        path=Path(self.temp.name)/'scan.pdf';path.write_bytes(b'%PDF-synthetic queue fixture')
        job,_=job_store.submit('max:11','batch_grade',uuid.uuid4().hex,{'assignment_id':a['id']},[path],require_worker=False)
        claim=job_store.claim_next('ai');directory=job_store.job_directory(job['id'])/'pages';directory.mkdir()
        pages=[]
        for i,color in enumerate(('white','blue')):
            Image.new('RGB',(80,100),color).save(directory/f'page_{i+1}.jpg')
            pages.append({'student_code':a['students'][i]['code'],'edition_code':'WRONG' if wrong_version else a['code'],
                          'assignment_code':'0'*32 if wrong_assignment else '',
                          'answers':[{'task_id':t['id'],'text':t['answer'],'state':'readable'} for t in a['worksheet']['tasks']]})
        self.assertTrue(job_store.complete(claim,{'batch_pages':pages[:1] if partial else pages,'photo_count':2}))
        return a,batch_review.get('max:11',job['id']),path

    def test_codes_suggest_mapping_but_scores_wait_for_teacher(self):
        a,b,_=self.ready_batch()
        self.assertEqual(b['pages'][0]['suggested_student_id'],a['students'][0]['id'])
        result=batch_review.attach('max:11',b['id'],{'revision':b['revision'],'student_id':a['students'][0]['id'],'pages':[0]})
        r=review_store.get_review('max:11',result['review_id'])
        self.assertEqual(r['status'],'needs_review')
        self.assertEqual(review_store.report('max:11',a['id'])['summary']['confirmed'],0)
        self.assertEqual(len(r['photos']),1)

    def test_qr_of_another_assignment_requires_manual_mapping_and_review(self):
        a,b,_=self.ready_batch(wrong_assignment=True)
        self.assertIsNone(b['pages'][0]['suggested_student_id'])
        self.assertIn('другой назначенной',b['pages'][0]['warning'])
        result=batch_review.attach('max:11',b['id'],{'revision':b['revision'],'student_id':a['students'][0]['id'],'pages':[0]})
        review=review_store.get_review('max:11',result['review_id'])
        self.assertTrue(any('назначенной работы' in warning for warning in review['warnings']))
        self.assertEqual(review['status'],'needs_review')

    def test_ocr_separator_is_normalized_without_guessing_code_characters(self):
        for text in ('YAD211957BE','Y-AD211957BE','У—AD211957BE','У - AD211957BE'):
            self.assertEqual(class_store.normalize_student_code(text),'У-AD211957BE')
        self.assertNotEqual(class_store.normalize_student_code('Y-AD2119578E'),'У-AD211957BE')

    def test_foreign_batch_photos_mapping_and_roster_are_closed(self):
        a,b,_=self.ready_batch();base='/api/v2/batches/'+b['id']
        for path in (base,base+'/photos/0','/api/v2/assignments/'+a['id']+'/batches'):
            self.assertEqual(self.call(self.other,'get',path).status_code,404)
            self.assertEqual(self.call(self.anon,'get',path).status_code,401)
        self.assertEqual(self.call(self.other,'post',base+'/attach',json={'revision':b['revision'],'student_id':a['students'][0]['id'],'pages':[0]}).status_code,404)
        self.assertEqual(self.call(self.client,'post',base+'/attach',json={'revision':b['revision'],'student_id':'foreign','pages':[0]}).status_code,404)

    def test_wrong_edition_does_not_assign_and_partial_pages_remain_unknown(self):
        a,b,_=self.ready_batch(wrong_version=True,partial=True)
        self.assertIsNone(b['pages'][0]['suggested_student_id']);self.assertTrue(b['pages'][0]['warning'])
        self.assertIsNone(b['pages'][1]['suggested_student_id']);self.assertTrue(b['pages'][1]['error'])
        result=batch_review.attach('max:11',b['id'],{'revision':b['revision'],'student_id':a['students'][1]['id'],'pages':[1]})
        r=review_store.get_review('max:11',result['review_id'])
        self.assertTrue(all(answer['state']=='unclear' and answer['score'] is None for answer in r['answers']))

    def test_duplicates_used_pages_and_stale_mapping_are_rejected(self):
        a,b,path=self.ready_batch()
        with self.assertRaises(AIServiceError) as exc:
            job_store.submit('max:11','batch_grade',uuid.uuid4().hex,{'assignment_id':a['id']},[path],require_worker=False)
        self.assertEqual(exc.exception.code,'batch_exists')
        payload={'revision':b['revision'],'student_id':a['students'][0]['id'],'pages':[0]}
        batch_review.attach('max:11',b['id'],payload)
        with self.assertRaises(AIServiceError):batch_review.attach('max:11',b['id'],payload)
        payload['revision']+=1
        with self.assertRaises(AIServiceError) as exc:batch_review.attach('max:11',b['id'],payload)
        self.assertEqual(exc.exception.code,'pages_used')

    def test_backup_preserves_unmatched_scans_and_restores_all_files(self):
        _,b,_=self.ready_batch()
        archive=Path(self.temp.name)/'backup.zip'
        backup.create_backup(archive)
        target=Path(self.temp.name)/'restored';backup.restore_backup(archive,target)
        self.assertTrue((target/'batch_photos'/b['id']/'1.jpg').is_file())

    def test_batch_page_limit_is_separate_from_worksheet_limit(self):
        pdf=Path(self.temp.name)/'eleven.pdf';writer=PdfWriter()
        for _ in range(11):writer.add_blank_page(width=100,height=100)
        writer.write(pdf)
        with self.assertRaises(AIServiceError):source_pages.prepare([pdf],Path(self.temp.name)/'small')
        pages=source_pages.prepare([pdf],Path(self.temp.name)/'batch',max_pages=40)
        self.assertEqual(len(pages),11)

    def test_field_height_is_bounded_optional_and_controls_typesetting(self):
        sheet=demo_worksheet('math');old=edition_code(sheet)
        sheet['settings']['field_height_mm']=0
        self.assertEqual(edition_code(sheet),old)
        sheet['settings']['field_height_mm']=40
        clean=validate_worksheet(sheet)
        self.assertIn(r'\WriteField{40mm}',worksheet_tex(clean));self.assertNotEqual(edition_code(clean),old)
        for value in (-1,4,101,True,'30'):
            sheet['settings']['field_height_mm']=value
            with self.assertRaises(AIServiceError):validate_worksheet(sheet)

if __name__=='__main__':unittest.main()
