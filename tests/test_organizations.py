import copy
import json
import os
import unittest
from unittest.mock import MagicMock, patch
from backend import organizations, management, lambda_issue, admin_auth

ID = 'CERT-11111111-1111-4111-8111-111111111111'
RECORD = dict(certificate_id=ID, recipient_name='Student 1', course_name='Cloud', organization='Organization 1',
              organization_id='org-1', issue_date='2026-01-01', expiry_date='2027-01-01', status='ACTIVE')

def event(subject='admin-a', resource='/admin/certificates', method='GET'):
    return {'resource': resource, 'httpMethod': method, 'pathParameters': {'id': ID},
            'requestContext': {'authorizer': {'claims': {'sub': subject, 'iss': 'issuer', 'aud': 'client',
                'exp': '9999999999', 'token_use': 'id', 'cognito:groups': 'admins'}}}}

class OrganizationTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'ADMIN_ISSUER': 'issuer', 'ADMIN_CLIENT_ID': 'client',
            'ADMIN_ORGANIZATIONS': json.dumps({'admin-a': 'org-1', 'admin-b': 'org-1', 'admin-c': 'org-2'})})
        env.start()
        self.addCleanup(env.stop)

    def test_shared_membership_and_browser_claims_cannot_grant_access(self):
        for subject in ['admin-a', 'admin-b']:
            self.assertEqual(organizations.assigned_organization(event(subject)), 'org-1')
        forged = event('unknown')
        forged['requestContext']['authorizer']['claims']['custom:organization'] = 'org-1'
        forged['headers'] = {'Organization': 'org-1'}
        self.assertIsNone(organizations.assigned_organization(forged))
        for config in ['not json', '[]', '{"admin-a": "admin"}']:
            with patch.dict(os.environ, {'ADMIN_ORGANIZATIONS': config}):
                self.assertIsNone(organizations.assigned_organization(event()))

    def test_other_organization_is_visible_but_not_manageable(self):
        table = MagicMock()
        table.scan.return_value = {'Items': [RECORD, {**RECORD, 'certificate_id': ID.replace('11111111', '22222222', 1), 'organization_id': 'org-2', 'organization': 'Organization 2'}]}
        records = management.list_certificates(table, {}, 'org-1')['certificates']
        self.assertEqual([r['can_manage'] for r in records], [True, False])
        table.get_item.return_value = {'Item': RECORD}
        with patch('backend.management.publish_event') as publish:
            response = management.handle(event('admin-c', '/admin/certificates/{id}/revoke', 'POST'), table, MagicMock(), 'topic', 'http://localhost:8000/verify.html')
        self.assertEqual(response['statusCode'], 403)
        publish.assert_not_called()
        table.update_item.assert_not_called()
        # An already-revoked record cannot be used for cross-organization email retries.
        table.get_item.return_value = {'Item': {**RECORD, 'status': 'REVOKED'}}
        with self.assertRaises(PermissionError): management.revoke(table, ID, 'admin-c', 'org-2')

    def test_same_organization_admin_can_revoke_another_issuers_certificate(self):
        table = MagicMock()
        table.get_item.return_value = {'Item': {**RECORD, 'issued_by': 'admin-a'}}
        table.update_item.return_value = {'Attributes': {**RECORD, 'status': 'REVOKED', 'revoked_by': 'admin-b'}}
        self.assertEqual(management.revoke(table, ID, 'admin-b', 'org-1')['revoked_by'], 'admin-b')
        self.assertEqual(table.update_item.call_args.kwargs['ExpressionAttributeValues'][':organization'], 'org-1')

    def test_reassignment_race_does_not_recover_other_org_success(self):
        table = MagicMock()
        table.get_item.side_effect = [{'Item': RECORD}, {'Item': {**RECORD, 'organization_id': 'org-2', 'status': 'REVOKED'}}]
        table.update_item.side_effect = RuntimeError('conditional failure')
        with self.assertRaises(RuntimeError): management.revoke(table, ID, 'admin-a', 'org-1')

    def test_missing_ownership_and_retired_records_are_read_only(self):
        unknown = {**RECORD}; unknown.pop('organization_id')
        self.assertFalse(organizations.can_manage(unknown, 'org-1'))
        self.assertFalse(organizations.can_manage({**RECORD, 'retired_at': 'date'}, 'org-1'))
        self.assertFalse(organizations.can_manage(RECORD, None))
        table = MagicMock(); table.scan.return_value = {'Items': [{**RECORD, 'retired_at': 'date'}]}
        self.assertEqual(management.list_certificates(table, {}, 'org-1')['certificates'], [])

    def test_issuance_cannot_spoof_organization_and_unassigned_denied(self):
        table, s3 = MagicMock(), MagicMock()
        fields = {key: RECORD[key] for key in lambda_issue.FIELDS}
        fields['organization'] = 'Organization 2'
        with self.assertRaises(PermissionError):
            lambda_issue.issue(fields, '11111111-1111-4111-8111-111111111111', 'admin-a', table, s3, 'bucket', 'http://localhost:8000/verify.html', 'org-1')
        table.put_item.assert_not_called(); s3.put_object.assert_not_called()
        self.assertEqual(lambda_issue.lambda_handler(event('unknown', method='POST'), None)['statusCode'], 403)
        response = admin_auth.session(event('admin-b', '/admin/session'))
        self.assertEqual(json.loads(response['body'])['organization'], 'Organization 1')
