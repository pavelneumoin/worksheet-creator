import importlib.util
from pathlib import Path
import unittest
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
spec = importlib.util.spec_from_file_location('deployment_check', ROOT / 'scripts/check_deployment.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class DeploymentTests(unittest.TestCase):
    def test_public_origin_rejects_paths_credentials_and_local_addresses(self):
        for value in ('http://school.ru', 'https://127.0.0.1', 'https://localhost',
                      'https://school.ru/app', 'https://user:secret@school.ru',
                      'https://school.ru?key=secret', 'https://school.ru#fragment',
                      'https://school.ru:3005', 'https://school.ru:bad',
                      'https://school.ru\nheader', 'https://example.test'):
            with self.subTest(value=value):
                self.assertFalse(check.valid_origin(value))
        self.assertTrue(check.valid_origin('https://listok.school.ru/'))

    def test_configuration_failure_does_not_print_secrets(self):
        with patch.object(check.ssl, 'create_default_context', side_effect=OSError):
            errors = check.check_config({'MAX_BOT_TOKEN': 'secret-marker', 'LISTOK_AUTH_MODE': 'local'}, ROOT)
        self.assertNotIn('secret-marker', str(errors))
        self.assertTrue(any('PEM' in message for message in errors))
        self.assertTrue(any('AUTH_MODE' in message for message in errors))

    def test_readiness_requires_both_workers_and_compiler(self):
        from app import app
        client = app.test_client()
        with patch('utils.job_store.workers_ready', return_value=True), patch('app._compiler', return_value='xelatex'):
            self.assertEqual(client.get('/api/health/ready').status_code, 200)
        with patch('utils.job_store.workers_ready', side_effect=lambda lane: lane == 'ai'), patch('app._compiler', return_value='xelatex'):
            response = client.get('/api/health/ready')
            self.assertEqual(response.status_code, 503)
            self.assertFalse(response.json['checks']['compile_worker'])
        with patch('utils.job_store.workers_ready', side_effect=OSError('secret path')):
            response = client.get('/api/health/ready')
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json, {'ready': False})
