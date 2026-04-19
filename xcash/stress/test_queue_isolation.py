from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class StressQueueIsolationTests(SimpleTestCase):
    def test_stress_tasks_are_routed_to_stress_queue(self):
        expected_tasks = (
            "stress.tasks.prepare_stress",
            "stress.tasks.execute_stress_case",
            "stress.tasks.execute_withdrawal_case",
            "stress.tasks.execute_deposit_case",
            "stress.tasks.check_webhook_timeout",
            "stress.tasks.check_withdrawal_webhook_timeout",
            "stress.tasks.check_deposit_webhook_timeout",
            "stress.tasks.finalize_stress_timeout",
            "stress.tasks.verify_deposit_collection",
        )

        for task_name in expected_tasks:
            with self.subTest(task=task_name):
                self.assertEqual(
                    settings.CELERY_TASK_ROUTES.get(task_name),
                    {"queue": "stress"},
                )

    def test_dev_worker_only_consumes_business_queue(self):
        repo_root = Path(__file__).resolve().parents[2]
        script = (repo_root / "scripts" / "dev-worker.sh").read_text()

        self.assertIn("-Q celery", script)
        self.assertNotIn("-Q celery,scan", script)

    def test_dev_scan_worker_script_exists_and_only_consumes_scan_queue(self):
        repo_root = Path(__file__).resolve().parents[2]
        scan_script = repo_root / "scripts" / "dev-worker-scan.sh"

        self.assertTrue(scan_script.exists())

        content = scan_script.read_text()
        self.assertIn("-Q scan", content)
        self.assertNotIn("-Q celery,scan", content)

    def test_dev_stress_worker_script_exists_and_only_consumes_stress_queue(self):
        repo_root = Path(__file__).resolve().parents[2]
        stress_script = repo_root / "scripts" / "dev-worker-stress.sh"

        self.assertTrue(stress_script.exists())

        content = stress_script.read_text()
        self.assertIn("-Q stress", content)
        self.assertNotIn("-Q celery,scan", content)

    def test_dev_up_starts_scan_worker(self):
        repo_root = Path(__file__).resolve().parents[2]
        script = (repo_root / "scripts" / "dev-up.sh").read_text()

        self.assertIn('"${SCRIPT_DIR}/dev-worker.sh"', script)
        self.assertIn('"${SCRIPT_DIR}/dev-worker-scan.sh"', script)
        self.assertIn('"${SCRIPT_DIR}/dev-worker-stress.sh"', script)
