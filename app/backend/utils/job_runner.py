"""One bounded subprocess per job; one active job per lane across all workers."""
import json
import logging
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from utils import db, job_store, latex
from utils.gigachat_client import AIServiceError

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[3]


def process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}


def stop_process(process):
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


def remove_outputs(job_id):
    base = 'job_' + job_id
    for suffix in ('.pdf', '.tex', '.log', '_keys.pdf', '_keys.tex', '_keys.log', '_marp.zip'):
        (Path(latex.OUTPUT_DIR) / (base + suffix)).unlink(missing_ok=True)


def execute(job_id):
    """Child process: only material work, no database completion side effects."""
    from utils import ai_batch, source_pages
    from utils.marp_export import export_bundle
    from utils.worksheet import compile_worksheet
    from utils.workspace_store import connection
    directory = job_store.job_directory(job_id)
    with connection() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=? AND status='running'", (job_id,)).fetchone()
        if row is None:
            return 1
        job = dict(row)
    payload = json.loads(job['payload'])
    try:
        if job['kind'] == 'compile':
            base = 'job_' + job_id
            compile_worksheet(payload['worksheet'], base)
            export_bundle(payload['worksheet'], Path(latex.OUTPUT_DIR) / (base + '_marp.zip'), payload.get('origin'))
            result = {'ok': True}
        elif job['kind'] == 'grade':
            from utils import grading_ai
            paths = source_pages.prepare([directory / name for name in payload['images']], directory / 'pages')
            result = grading_ai.recognize(payload['tasks'], paths)
            result['photos'] = [Path(path).name for path in paths]
        else:
            paths = source_pages.prepare([directory / name for name in payload['images']], directory / 'pages') if job['kind'] == 'recognize' else []
            result = ai_batch.generate(job['kind'], payload, paths, directory)
    except AIServiceError as exc:
        result = {'error': str(exc), 'code': exc.code}
    except Exception as exc:
        result = {'error': 'Не удалось завершить обработку. Исходный материал сохранён. Повторите действие.', 'code': 'job_failed'}
        logger.error('Job failed (%s)', type(exc).__name__)
    # Keep a usable checkpoint if a later call unexpectedly failed.
    if result.get('error') and (directory / 'result.json').is_file():
        previous = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
        if previous.get('worksheets'):
            result = previous
    ai_batch.write_result(directory, result)
    return 0


def run_one(lane, worker_id, stop=None, timeout_override=None):
    job_store.heartbeat(worker_id, lane)
    job = job_store.claim_next(lane)
    if job is None:
        return False
    directory = job_store.job_directory(job['id'])
    directory.mkdir(exist_ok=True)
    environment = dict(os.environ, LISTOK_DB_PATH=str(Path(db.DB_PATH).resolve()),
                       LISTOK_JOBS_DIR=str(job_store.root()), LISTOK_GENERATED_DIR=str(Path(latex.OUTPUT_DIR).resolve()))
    # The compiler receives no provider or bot credentials, including in local development.
    for key in list(environment):
        if key.startswith(('MAX_', 'OPENAI_', 'ANTHROPIC_', 'SESSION_')) or (lane == 'compile' and key.startswith('GIGACHAT_')):
            del environment[key]
    environment['LISTOK_SKIP_DOTENV'] = '1'
    command = [sys.executable, str(ROOT / 'scripts/run_worker.py'), '--execute', job['id']]
    count = json.loads(job['payload']).get('variant_count', 1)
    payload = json.loads(job['payload'])
    timeout = timeout_override if timeout_override is not None else {'recognize': 1500 + 300 * (count - 1), 'variant': 300 * count, 'compile': 180, 'grade': 30 + 300 * len(payload.get('images', []))}[job['kind']]
    process = None
    succeeded = False
    try:
        process = subprocess.Popen(command, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **process_options())
        started, last_beat = time.monotonic(), 0
        while process.poll() is None:
            if stop and stop():
                raise InterruptedError()
            if time.monotonic() - started > timeout:
                raise TimeoutError()
            if time.monotonic() - last_beat >= 2:
                job_store.heartbeat(worker_id, lane, job['id'], job['claim'])
                last_beat = time.monotonic()
            time.sleep(0.2)
        result_path = directory / 'result.json'
        if not result_path.is_file() or result_path.stat().st_size > 2 * 1024 * 1024:
            raise RuntimeError('Child failed')
        output = json.loads(result_path.read_text(encoding='utf-8'))
        if output.get('error'):
            job_store.fail(job['id'], job['claim'], output['error'], output['code'])
        else:
            succeeded = job_store.complete(job, output)
    except TimeoutError:
        if process is not None:
            stop_process(process)
        succeeded = complete_checkpoint(job, directory)
        job_store.fail(job['id'], job['claim'], 'Обработка заняла слишком много времени. Попробуйте меньше фотографий или более короткий лист.', 'job_timeout')
    except (InterruptedError, KeyboardInterrupt):
        if process is not None:
            stop_process(process)
        succeeded = complete_checkpoint(job, directory)
        job_store.fail(job['id'], job['claim'], 'Сервер перезапустился во время обработки. Повторите действие вручную; автоматического повторного запроса к ИИ не было.', 'worker_interrupted')
    except Exception as exc:
        logger.error('Worker failure (%s)', type(exc).__name__)
        if process is not None:
            stop_process(process)
        succeeded = complete_checkpoint(job, directory)
        job_store.fail(job['id'], job['claim'], 'Не удалось завершить задачу. Исходный материал сохранён. Повторите действие.', 'job_failed')
    finally:
        if process is not None:
            stop_process(process)
        if not succeeded:
            succeeded = complete_checkpoint(job, directory)
        if not succeeded:
            remove_outputs(job['id'])
        job_store.remove_inputs(job['id'])
    return True


def complete_checkpoint(job, directory):
    """Only a still-running claim can commit. Failed/cancelled jobs stay fenced."""
    path = directory / 'result.json'
    if job['kind'] == 'compile' or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        return False
    try:
        result = json.loads(path.read_text(encoding='utf-8'))
        usable = bool(result.get('worksheets')) or (job['kind'] == 'grade' and isinstance(result.get('answers'), list) and bool(result.get('photos')))
        return usable and job_store.complete(job, result)
    except (ValueError, AIServiceError):
        return False


def serve(lane):
    worker = uuid.uuid4().hex
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    print('ListOK worker ready: ' + lane, flush=True)
    try:
        while not stopping:
            job_store.maintain()
            if not run_one(lane, worker, stop=lambda: stopping):
                time.sleep(0.5)
    finally:
        from utils.workspace_store import connection
        with connection() as conn:
            conn.execute('DELETE FROM workers WHERE id=?', (worker,))
