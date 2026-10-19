import copy
import json
import os
import unittest
from unittest.mock import MagicMock, patch
from backend import management, lambda_issue
from backend.verification import public_result

ID = 'CERT-12345678-1234-4234-8234-123456789abc'
RECORD = dict(certificate_id=ID, recipient_name='Example', course_name='Cloud', organization='Organization 1', organization_id='org-1',
              issue_date='2020-01-01', expiry_date='2099-01-01', status='ACTIVE', pdf_sha256='original-hash', s3_key='private.pdf')

class ManagementTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {"ADMIN_ORGANIZATIONS": json.dumps({"admin": "org-1"})})
        env.start()
        self.addCleanup(env.stop)

    def test_listing_filters_tracking_rows_and_private_fields_and_keeps_cursor(self):
        table = MagicMock()
        table.scan.return_value = {'Items': [RECORD, {'certificate_id': 'ISSUE#request'}, {'certificate_id': 'NOTIFY#event'}], 'LastEvaluatedKey': {'certificate_id': 'NOTIFY#event'}}
        result = management.list_certificates(table, {}, "org-1")
        self.assertEqual(len(result['certificates']), 1)
        self.assertNotIn('pdf_sha256', result['certificates'][0])
        self.assertNotIn('s3_key', result['certificates'][0])
        self.assertEqual(result['next_cursor'], 'NOTIFY#event')
        table.scan.return_value = {'Items': [], 'LastEvaluatedKey': {'certificate_id': 'ISSUE#next'}}
        result = management.list_certificates(table, {'cursor': 'NOTIFY#event'}, 'org-1')
        self.assertEqual(result['certificates'], [])
        self.assertEqual(result['next_cursor'], 'ISSUE#next')
        self.assertEqual(table.scan.call_args.kwargs['ExclusiveStartKey'], {'certificate_id': 'NOTIFY#event'})
        self.assertEqual(table.scan.call_args.kwargs['Limit'], 25)
        for cursor in ['', 'x'*201, 1]:
            with self.assertRaises(ValueError): management.list_certificates(table, {'cursor': cursor}, 'org-1')

    def test_revoke_preserves_pdf_and_first_audit_and_changes_verification(self):
        table = MagicMock()
        stored = copy.deepcopy(RECORD)
        table.get_item.side_effect = lambda **kw: {'Item': copy.deepcopy(stored)}
        def update(**kw):
            self.assertEqual(kw['ConditionExpression'], 'attribute_exists(certificate_id) AND #s = :active AND attribute_not_exists(retired_at) AND organization_id = :organization')
            self.assertEqual(kw['UpdateExpression'], 'SET #s = :revoked, revoked_at = :at, revoked_by = :by')
            values = kw['ExpressionAttributeValues']
            stored.update(status='REVOKED', revoked_at=values[':at'], revoked_by=values[':by'])
            return {'Attributes': copy.deepcopy(stored)}
        table.update_item.side_effect = update
        first = management.revoke(table, ID, 'admin1', "org-1")
        second = management.revoke(table, ID, 'admin2', "org-1")
        self.assertEqual(first, second)
        self.assertEqual(table.update_item.call_count, 1)
        self.assertEqual(first['pdf_sha256'], RECORD['pdf_sha256'])
        self.assertEqual(first['s3_key'], RECORD['s3_key'])
        self.assertEqual(public_result(first, ID)['status'], 'REVOKED')

    def test_missing_invalid_and_corrupt_records_do_not_write(self):
        table = MagicMock()
        table.get_item.return_value = {}
        self.assertIsNone(management.revoke(table, ID, 'admin', "org-1"))
        for identifier in ['ISSUE#request', 'NOTIFY#event', None, 'CERT-invalid']:
            with self.assertRaises(ValueError): management.revoke(table, identifier, 'admin', "org-1")
        table.get_item.return_value = {'Item': {**RECORD, 'status': 'UNKNOWN'}}
        with self.assertRaises(RuntimeError): management.revoke(table, ID, 'admin', "org-1")
        table.update_item.assert_not_called()

    def test_lost_update_or_concurrent_revoke_recovers_without_overwriting(self):
        table = MagicMock()
        revoked = {**RECORD, 'status': 'REVOKED', 'revoked_by': 'first-admin'}
        table.get_item.side_effect = [{'Item': RECORD}, {'Item': revoked}]
        table.update_item.side_effect = RuntimeError('lost response')
        self.assertEqual(management.revoke(table, ID, 'second-admin', "org-1"), revoked)
        table.get_item.side_effect = [{'Item': RECORD}, {'Item': RECORD}]
        with self.assertRaises(RuntimeError): management.revoke(table, ID, 'admin', "org-1")

    def test_notification_failure_does_not_undo_revocation(self):
        table = MagicMock()
        table.get_item.return_value = {'Item': {**RECORD, 'status': 'REVOKED'}}
        event = {'resource': '/admin/certificates/{id}/revoke', 'httpMethod': 'POST',
                 'pathParameters': {'id': ID}, 'requestContext': {'authorizer': {'claims': {'sub': 'admin'}}}}
        with patch('backend.management.publish_event', side_effect=RuntimeError('private failure')):
            result = management.handle(event, table, MagicMock(), 'topic', 'http://localhost:8000/verify.html')
        self.assertEqual(result['statusCode'], 200)
        self.assertEqual(json.loads(result['body'])['notification_status'], 'pending')
        self.assertNotIn('private', result['body'])
        table.update_item.assert_not_called()

    def test_both_routes_reject_unauthenticated_and_non_admin_before_storage(self):
        with patch.dict(os.environ, {'ADMIN_ISSUER': 'issuer', 'ADMIN_CLIENT_ID': 'client'}), patch('backend.lambda_issue.boto3') as sdk:
            for resource, method in [('/admin/certificates', 'GET'), ('/admin/certificates/{id}/revoke', 'POST')]:
                event = dict(resource=resource, httpMethod=method)
                self.assertEqual(lambda_issue.lambda_handler(event, None)['statusCode'], 401)
                event['requestContext'] = {'authorizer': {'claims': {'sub': 'user', 'iss': 'issuer', 'aud': 'client', 'token_use': 'id', 'exp': '9999999999', 'cognito:groups': '[users]'}}}
                self.assertEqual(lambda_issue.lambda_handler(event, None)['statusCode'], 403)
            sdk.resource.assert_not_called()
            sdk.client.assert_not_called()
