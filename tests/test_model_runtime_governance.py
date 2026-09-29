"""Model Runtime Governance: runtime identity vs approved artifact."""
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from daytrade_learning.model_runtime import (
    DaytradeModel,
    write_runtime_model_status,
    refresh_runtime_model_status,
    resolve_runtime_status_path,
    resolve_approved_model_path,
    model_runtime_consistency,
    _effective_stale_ttl,
    RUNTIME_STATUS_FILE,
)
from daytrade_learning.features import FEATURES, SCHEMA_VERSION

TPE = timezone(timedelta(hours=8))


def artifact(**overrides):
    base = dict(
        approved=True,
        deployment_allowed=True,
        schema_version=SCHEMA_VERSION,
        features=list(FEATURES),
        mean=[0] * 5,
        scale=[1] * 5,
        coef=[0] * 5,
        intercept=0,
        threshold=0.6,
        version='fixture',
        trained_through=datetime.now(TPE).date().isoformat(),
        profile='profile-a',
    )
    base.update(overrides)
    return base


class RuntimeGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name)
        self.models = self.data / 'models'
        self.models.mkdir(parents=True)
        self.approved_path = self.models / 'latest-approved.json'
        self.status_path = self.models / 'runtime-model-status.json'
        os.environ['AI_PAPER_MODEL_PATH'] = str(self.approved_path)

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop('AI_PAPER_MODEL_PATH', None)

    def _write_approved(self, **overrides):
        self.approved_path.write_text(json.dumps(artifact(**overrides)), encoding='utf-8')
        return self.approved_path.read_bytes()

    def _sha(self, raw):
        import hashlib
        return hashlib.sha256(raw).hexdigest()

    def _runtime_identity(self, sha, **overrides):
        identity = dict(
            version='fixture',
            trained_through=datetime.now(TPE).date().isoformat(),
            profile='profile-a',
            schema_version=SCHEMA_VERSION,
            loaded_at=datetime.now(TPE).isoformat(),
            artifact_path=str(self.approved_path),
            artifact_sha256=sha,
        )
        identity.update(overrides)
        return identity

    def _write_status(self, identity=None, sha=None, instance_id='instance-a', started_at=None, reported_at='__now__'):
        if identity is None:
            identity = self._runtime_identity(sha or self._sha(self._write_approved()))
        if reported_at == '__now__':
            reported_at = datetime.now(TPE).isoformat()
        payload = {
            'reported_at': reported_at,
            'loaded_at': identity.get('loaded_at'),
            'pid': 1,
            'instance_id': instance_id,
            'process_started_at': started_at or datetime.now(TPE).isoformat(),
            'entry_mode': 'model',
            'runtime': identity,
        }
        self.status_path.write_text(json.dumps(payload), encoding='utf-8')
        return identity

    def test_ok_when_runtime_matches_approved(self):
        raw = self._write_approved()
        sha = self._sha(raw)
        write_runtime_model_status(self._runtime_identity(sha), entry_mode='model', pid=1, path=self.status_path)
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'OK')
        self.assertTrue(result['match'])
        self.assertEqual(result['reason'], 'runtime_artifact_hash_matches')
        self.assertEqual(result['runtime']['artifact_sha256'], sha)
        self.assertEqual(result['approved']['artifact_sha256'], sha)
        self.assertNotIn('artifact_path', result['runtime'])

    def test_mismatch_when_runtime_sha_differs(self):
        self._write_approved(version='fixture', profile='profile-a')
        write_runtime_model_status(
            self._runtime_identity('old-sha', version='fixture', profile='profile-a'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'MISMATCH')
        self.assertFalse(result['match'])
        self.assertEqual(result['reason'], 'runtime_artifact_hash_differs')

    def test_mismatch_takes_precedence_over_profile_mismatch(self):
        self._write_approved(profile='profile-a')
        write_runtime_model_status(
            self._runtime_identity('other-sha', profile='profile-b'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'MISMATCH')
        self.assertFalse(result['details']['sha_match'])
        self.assertFalse(result['details']['profile_match'])

    def test_mismatch_takes_precedence_over_version_mismatch(self):
        self._write_approved(version='v2')
        write_runtime_model_status(
            self._runtime_identity('other-sha', version='v1'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'MISMATCH')
        self.assertFalse(result['details']['sha_match'])
        self.assertFalse(result['details']['version_match'])

    def test_runtime_unknown_when_status_missing(self):
        self._write_approved()
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'RUNTIME_UNKNOWN')
        self.assertEqual(result['reason'], 'runtime_status_missing')

    def test_runtime_unknown_when_reported_at_missing(self):
        self._write_approved()
        identity = self._runtime_identity('any-sha')
        self._write_status(identity=identity)
        data = json.loads(self.status_path.read_text(encoding='utf-8'))
        data.pop('reported_at', None)
        self.status_path.write_text(json.dumps(data), encoding='utf-8')
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'RUNTIME_UNKNOWN')
        self.assertEqual(result['reason'], 'runtime_reported_at_missing')

    def test_runtime_unknown_when_reported_at_null(self):
        self._write_approved()
        identity = self._runtime_identity('any-sha')
        self._write_status(identity=identity, reported_at=None)
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'RUNTIME_UNKNOWN')

    def test_runtime_unknown_when_reported_at_invalid(self):
        self._write_approved()
        identity = self._runtime_identity('any-sha')
        self._write_status(identity=identity, reported_at='not-a-timestamp')
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'RUNTIME_UNKNOWN')
        self.assertEqual(result['reason'], 'runtime_reported_at_invalid')

    def test_runtime_unknown_when_reported_at_in_future(self):
        self._write_approved()
        identity = self._runtime_identity('any-sha')
        future = (datetime.now(TPE) + timedelta(seconds=120)).isoformat()
        self._write_status(identity=identity, reported_at=future)
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'RUNTIME_UNKNOWN')
        self.assertEqual(result['reason'], 'runtime_reported_at_in_future')

    def test_slight_future_clock_skew_is_accepted(self):
        raw = self._write_approved()
        sha = self._sha(raw)
        future = (datetime.now(TPE) + timedelta(seconds=5)).isoformat()
        self._write_status(identity=self._runtime_identity(sha), instance_id='skew', reported_at=future)
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'OK')

    def test_runtime_stale_when_report_old(self):
        raw = self._write_approved()
        sha = self._sha(raw)
        now = datetime.now(TPE)
        old = (now - timedelta(seconds=200)).isoformat()
        write_runtime_model_status(
            self._runtime_identity(sha),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(
            learning_data_dir=str(self.data),
            max_stale_seconds=90,
            now=now,
        )
        # default reported_at is recent, so it should not be stale
        self.assertEqual(result['status'], 'OK')
        # force old reported_at by rewriting
        data = json.loads(self.status_path.read_text(encoding='utf-8'))
        data['reported_at'] = old
        self.status_path.write_text(json.dumps(data), encoding='utf-8')
        result = model_runtime_consistency(
            learning_data_dir=str(self.data),
            max_stale_seconds=90,
            now=now,
        )
        self.assertEqual(result['status'], 'RUNTIME_STALE')
        self.assertEqual(result['reason'], 'runtime_status_stale')

    def test_approved_missing(self):
        write_runtime_model_status(
            self._runtime_identity('any-sha'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'APPROVED_MISSING')
        self.assertEqual(result['reason'], 'approved_artifact_missing')

    def test_approved_invalid_json(self):
        self.approved_path.write_text('not json', encoding='utf-8')
        raw = b'not json'
        write_runtime_model_status(
            self._runtime_identity(self._sha(raw)),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'APPROVED_INVALID')

    def test_approved_missing_metadata(self):
        self.approved_path.write_text(json.dumps({'approved': True, 'deployment_allowed': True}), encoding='utf-8')
        write_runtime_model_status(
            self._runtime_identity('any-sha'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'APPROVED_INVALID')

    def test_missing_required_approved_fields_are_diagnostic(self):
        required = ('intercept', 'threshold', 'version', 'trained_through',
                    'profile', 'schema_version', 'features', 'mean', 'scale', 'coef')
        for key in required:
            with self.subTest(key=key):
                payload = artifact()
                payload.pop(key)
                self.approved_path.write_text(json.dumps(payload), encoding='utf-8')
                write_runtime_model_status(
                    self._runtime_identity('any-sha'),
                    entry_mode='model',
                    pid=1,
                    path=self.status_path,
                )
                result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
                self.assertEqual(result['status'], 'APPROVED_INVALID')
                self.assertIn(key, result['reason'])

    def test_approved_invalid_schema_version(self):
        self._write_approved(schema_version='wrong')
        write_runtime_model_status(
            self._runtime_identity('any-sha'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'APPROVED_INVALID')
        self.assertIn('schema', result['reason'])

    def test_approved_invalid_feature_order(self):
        self._write_approved(features=list(reversed(FEATURES)))
        write_runtime_model_status(
            self._runtime_identity('any-sha'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'APPROVED_INVALID')
        self.assertIn('features', result['reason'])

    def test_approved_invalid_dimensions(self):
        self._write_approved(mean=[0]*3)
        write_runtime_model_status(
            self._runtime_identity('any-sha'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'APPROVED_INVALID')
        self.assertIn('dimensions', result['reason'])

    def test_approved_invalid_numeric(self):
        self._write_approved(scale=[float('nan')]*5)
        write_runtime_model_status(
            self._runtime_identity('any-sha'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'APPROVED_INVALID')

    def test_approved_invalid_profile(self):
        self._write_approved(profile='   ')
        write_runtime_model_status(
            self._runtime_identity('any-sha'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'APPROVED_INVALID')

    def test_reload_updates_runtime_identity(self):
        raw1 = self._write_approved(version='v1')
        sha1 = self._sha(raw1)
        write_runtime_model_status(
            self._runtime_identity(sha1, version='v1'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        first = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(first['runtime']['version'], 'v1')

        raw2 = self._write_approved(version='v2')
        sha2 = self._sha(raw2)
        model = DaytradeModel(path=self.approved_path)
        write_runtime_model_status(model.identity(), entry_mode='model', pid=1, path=self.status_path)
        second = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(second['status'], 'OK')
        self.assertEqual(second['runtime']['version'], 'v2')
        self.assertEqual(second['runtime']['artifact_sha256'], sha2)

    def test_process_old_model_approved_new_detected(self):
        raw_old = self._write_approved(version='new')
        sha_old = self._sha(raw_old)
        write_runtime_model_status(
            self._runtime_identity(sha_old, version='new'),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        self._write_approved(version='new', profile='profile-a', coef=[0.1] * 5)
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'MISMATCH')
        self.assertEqual(result['runtime']['artifact_sha256'], sha_old)
        self.assertNotEqual(result['approved']['artifact_sha256'], sha_old)

    def test_loaded_model_a_survives_approved_model_b_and_heartbeat(self):
        raw_a = self._write_approved(version='model-a')
        model_a = DaytradeModel(path=self.approved_path)
        sha_a = self._sha(raw_a)
        self.assertEqual(model_a.identity()['artifact_sha256'], sha_a)
        started_a = (datetime.now(TPE) - timedelta(minutes=1)).isoformat()
        instance_a = write_runtime_model_status(
            model_a.identity(), entry_mode='model', pid=101, path=self.status_path,
            process_started_at=started_a,
        )
        raw_b = self._write_approved(version='model-b', coef=[0.1] * 5)
        sha_b = self._sha(raw_b)
        self.assertTrue(refresh_runtime_model_status(
            path=self.status_path, instance_id=instance_a, process_started_at=started_a,
        ))
        result = model_runtime_consistency(learning_data_dir=str(self.data), max_stale_seconds=90)
        self.assertEqual(result['status'], 'MISMATCH')
        self.assertEqual(result['runtime']['artifact_sha256'], sha_a)
        self.assertEqual(result['approved']['artifact_sha256'], sha_b)

    def test_initial_write_cannot_overwrite_newer_instance(self):
        raw = self._write_approved()
        identity = self._runtime_identity(self._sha(raw))
        old_started = (datetime.now(TPE) - timedelta(minutes=5)).isoformat()
        new_started = datetime.now(TPE).isoformat()
        new_id = write_runtime_model_status(
            identity, entry_mode='model', pid=202, path=self.status_path,
            instance_id='instance-new', process_started_at=new_started,
        )
        old_id = write_runtime_model_status(
            identity, entry_mode='model', pid=101, path=self.status_path,
            instance_id='instance-old', process_started_at=old_started,
        )
        self.assertEqual(new_id, 'instance-new')
        self.assertIsNone(old_id)
        current = json.loads(self.status_path.read_text(encoding='utf-8'))
        self.assertEqual(current['instance_id'], 'instance-new')
        self.assertEqual(current['pid'], 202)

    def test_equal_process_start_uses_instance_id_tie_break(self):
        raw = self._write_approved()
        identity = self._runtime_identity(self._sha(raw))
        started = datetime.now(TPE).isoformat()
        self.assertEqual(write_runtime_model_status(
            identity, instance_id='instance-a', process_started_at=started, path=self.status_path,
        ), 'instance-a')
        self.assertEqual(write_runtime_model_status(
            identity, instance_id='instance-z', process_started_at=started, path=self.status_path,
        ), 'instance-z')
        self.assertIsNone(write_runtime_model_status(
            identity, instance_id='instance-a', process_started_at=started, path=self.status_path,
        ))
        self.assertEqual(json.loads(self.status_path.read_text(encoding='utf-8'))['instance_id'], 'instance-z')

    def test_invalid_existing_started_at_does_not_block_new_initial_write(self):
        raw = self._write_approved()
        identity = self._runtime_identity(self._sha(raw))
        self.status_path.write_text(json.dumps({
            'instance_id': 'old', 'process_started_at': 'invalid', 'runtime': identity,
        }), encoding='utf-8')
        result = write_runtime_model_status(
            identity, instance_id='new', process_started_at=datetime.now(TPE).isoformat(),
            path=self.status_path,
        )
        self.assertEqual(result, 'new')
        self.assertEqual(json.loads(self.status_path.read_text(encoding='utf-8'))['instance_id'], 'new')

    def test_concurrent_initial_writes_keep_newest_owner(self):
        raw = self._write_approved()
        identity = self._runtime_identity(self._sha(raw))
        base = datetime.now(TPE)
        entries = [
            ('instance-1', (base + timedelta(seconds=1)).isoformat(), 1),
            ('instance-2', (base + timedelta(seconds=2)).isoformat(), 2),
            ('instance-3', (base + timedelta(seconds=3)).isoformat(), 3),
        ]
        def write(entry):
            instance_id, started, pid = entry
            return write_runtime_model_status(
                identity, instance_id=instance_id, process_started_at=started,
                pid=pid, path=self.status_path,
            )
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(write, entries))
        current = json.loads(self.status_path.read_text(encoding='utf-8'))
        self.assertEqual(current['instance_id'], 'instance-3')
        self.assertEqual(current['pid'], 3)

    def test_refresh_keeps_identity_alive(self):
        raw = self._write_approved()
        sha = self._sha(raw)
        write_runtime_model_status(
            self._runtime_identity(sha),
            entry_mode='model',
            pid=1,
            path=self.status_path,
        )
        data = json.loads(self.status_path.read_text(encoding='utf-8'))
        instance_id = data['instance_id']
        loaded_at = data['loaded_at']
        self.assertTrue(refresh_runtime_model_status(path=self.status_path, instance_id=instance_id))
        data = json.loads(self.status_path.read_text(encoding='utf-8'))
        self.assertIsNotNone(data['reported_at'])
        self.assertEqual(data['runtime']['artifact_sha256'], sha)
        self.assertEqual(data['loaded_at'], loaded_at)
        self.assertEqual(data['instance_id'], instance_id)

    def test_old_instance_yields_to_newer_instance(self):
        raw = self._write_approved()
        sha = self._sha(raw)
        old_started = (datetime.now(TPE) - timedelta(minutes=5)).isoformat()
        old_id = write_runtime_model_status(
            self._runtime_identity(sha),
            entry_mode='model',
            pid=1,
            path=self.status_path,
            process_started_at=old_started,
        )
        new_id = write_runtime_model_status(
            self._runtime_identity(sha),
            entry_mode='model',
            pid=2,
            path=self.status_path,
            process_started_at=datetime.now(TPE).isoformat(),
        )
        self.assertNotEqual(old_id, new_id)
        self.assertFalse(refresh_runtime_model_status(
            path=self.status_path,
            instance_id=old_id,
            process_started_at=old_started,
        ))
        data = json.loads(self.status_path.read_text(encoding='utf-8'))
        self.assertEqual(data['instance_id'], new_id)
        self.assertEqual(data['pid'], 2)

    def test_unique_temp_files_during_writes(self):
        raw = self._write_approved()
        sha = self._sha(raw)
        write_runtime_model_status(self._runtime_identity(sha), entry_mode='model', pid=1, path=self.status_path)
        temps_before = set(self.models.glob('*.tmp'))
        for _ in range(5):
            refresh_runtime_model_status(path=self.status_path, instance_id='i1')
        temps_after = set(self.models.glob('*.tmp'))
        self.assertEqual(temps_before, temps_after)

    def test_path_resolution_with_custom_ai_paper_model_path(self):
        custom = self.data / 'custom-models' / 'latest-approved.json'
        custom.parent.mkdir(parents=True)
        custom.write_text(json.dumps(artifact()), encoding='utf-8')
        os.environ['AI_PAPER_MODEL_PATH'] = str(custom)
        self.assertEqual(resolve_approved_model_path(), custom)
        self.assertEqual(resolve_runtime_status_path(), custom.parent / RUNTIME_STATUS_FILE)

    def test_path_resolution_precedence_includes_learning_environment(self):
        data_a = self.data / 'learning-a'
        data_b = self.data / 'learning-b'
        with patch.dict(os.environ, {
            'AI_PAPER_MODEL_PATH': '',
            'LEARNING_DATA_DIR': str(data_a),
            'EASYSTOCK_LEARNING_DATA': str(data_b),
        }, clear=False):
            self.assertEqual(resolve_approved_model_path(), data_a / 'models' / 'latest-approved.json')
        with patch.dict(os.environ, {
            'AI_PAPER_MODEL_PATH': '',
            'LEARNING_DATA_DIR': '',
            'EASYSTOCK_LEARNING_DATA': str(data_b),
        }, clear=False):
            self.assertEqual(resolve_approved_model_path(), data_b / 'models' / 'latest-approved.json')

    def test_stale_ttl_clamped_against_heartbeat(self):
        with patch.dict(os.environ, {'LIVE_HEARTBEAT_SECONDS': '100'}):
            self.assertGreaterEqual(_effective_stale_ttl(90), 160)
        with patch.dict(os.environ, {'LIVE_HEARTBEAT_SECONDS': '15'}):
            self.assertEqual(_effective_stale_ttl(90), 90)
            self.assertEqual(_effective_stale_ttl(30), 75)
            self.assertEqual(_effective_stale_ttl('invalid'), 90)
            self.assertEqual(_effective_stale_ttl(0), 90)
            self.assertEqual(_effective_stale_ttl(-10), 90)
            self.assertLessEqual(_effective_stale_ttl(999999999), 900)


class DaytradeModelIdentityTests(unittest.TestCase):
    def test_identity_reflects_loaded_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'model.json'
            payload = artifact(version='v-test', trained_through='2026-09-28', profile='p1')
            path.write_text(json.dumps(payload), encoding='utf-8')
            model = DaytradeModel(path=path)
            identity = model.identity()
            self.assertEqual(identity['version'], 'v-test')
            self.assertEqual(identity['trained_through'], '2026-09-28')
            self.assertEqual(identity['profile'], 'p1')
            self.assertEqual(identity['schema_version'], SCHEMA_VERSION)
            self.assertIsNotNone(identity['artifact_sha256'])
            self.assertEqual(identity['artifact_path'], str(path.resolve()))
            self.assertIsNotNone(identity['loaded_at'])

    def test_identity_for_invalid_model_is_explicit(self):
        model = DaytradeModel(path='')
        identity = model.identity()
        self.assertEqual(identity['version'], 'approved-model-gate-v3')
        self.assertIsNone(identity['artifact_sha256'])
        self.assertIsNone(identity['loaded_at'])


if __name__ == '__main__':
    unittest.main()
