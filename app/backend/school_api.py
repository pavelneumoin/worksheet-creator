from flask import Blueprint,g,jsonify,request,Response
from class_api import body
from utils import school_store,analytics,class_store,job_store
from utils.workspace_store import connection
from utils.gigachat_client import AIServiceError,get_ai_status

api=Blueprint('schools',__name__,url_prefix='/api/v2')

@api.get('/school')
def current():return jsonify(school=school_store.current(g.identity['owner_id']))
@api.post('/school')
def create():return jsonify(school=school_store.create(g.identity['owner_id'],body())),201
@api.post('/school/invites')
def invite():return jsonify(school_store.invite(g.identity['owner_id'])),201
@api.post('/school/join')
def join():return jsonify(school=school_store.join(g.identity['owner_id'],body()))
@api.post('/school/leave')
def leave():school_store.leave(g.identity['owner_id']);return jsonify(left=True)
@api.delete('/school/members/<user_id>')
def remove(user_id):school_store.leave(g.identity['owner_id'],user_id);return jsonify(removed=True)

@api.get('/analytics')
def overview():return jsonify(report=analytics.overview(g.identity['owner_id'],request.args))
@api.get('/analytics.csv')
def csv_export():
    report=analytics.overview(g.identity['owner_id'],request.args)
    return Response(analytics.csv_export(report),content_type='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="listok-analytics.csv"'})

@api.put('/assignments/<assignment_id>/topic')
def topic(assignment_id):
    value=body();name=class_store.label(value.get('topic'),'Тема',160)
    with connection() as conn:
        conn.execute('BEGIN IMMEDIATE');a=class_store.assignment_detail(conn,g.identity['owner_id'],assignment_id);class_store.revision(a,value.get('revision'))
        conn.execute('UPDATE assignments SET topic=?,revision=revision+1 WHERE id=?',(name,assignment_id))
    return jsonify(updated=True)

@api.post('/jobs/analytics_pdf')
@api.post('/jobs/analytics_insight')
def analytics_job():
    value=body();kind=request.path.rsplit('/',1)[-1]
    filters=value.get('filters',{})
    if not isinstance(filters,dict):raise AIServiceError('Проверьте фильтры отчёта.','invalid_filters',400)
    if kind=='analytics_insight':
        status=get_ai_status()
        if not status['ai_ready']:raise AIServiceError(status['ai_message'],'ai_not_configured',503)
    job,created=job_store.submit(g.identity['owner_id'],kind,request.headers.get('Idempotency-Key'),{'filters':filters,'insight_id':value.get('insight_id')})
    return jsonify(job=job,reused=not created),202 if job['status'] in job_store.ACTIVE else 200
