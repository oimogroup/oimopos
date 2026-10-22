from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.main import _validate_tenant_access
from app.self_registration import SignupInput


def data(**changes):
    return dict(request_id=str(uuid4()), name='Owner', company='Cafe', phone='+996 555 123456',
                email='owner@example.com', password='trial-password-123', plan='restaurant', consent=True, **changes)


@pytest.mark.parametrize('changes', [
    {'password':'short'}, {'email':'not-email'}, {'email':'name/test@example.com'},
    {'trial_days':365}, {'max_branches':100}, {'role':'platform_owner'},
    {'plan':'enterprise'}, {'consent':False}, {'phone':'abc'},
])
def test_public_signup_rejects_invalid_input_or_server_limit_override(changes):
    payload=data()
    payload.update(changes)
    with pytest.raises(ValidationError):
        SignupInput(**payload)


def test_signup_normalizes_contacts_without_changing_password():
    payload=data()
    payload.update(email='OWNER@EXAMPLE.COM',password='  a-long-password  ')
    value=SignupInput(**payload)
    assert value.email=='owner@example.com' and value.phone=='996555123456'
    assert value.password=='  a-long-password  '


def test_trial_access_expires_by_server_time():
    user=dict(role='owner',tenant_status='active',subscription_status='trialing',
              trial_ends_at=datetime.now(timezone.utc)+timedelta(days=14))
    _validate_tenant_access(user)
    user['trial_ends_at']=datetime.now(timezone.utc)-timedelta(seconds=1)
    with pytest.raises(HTTPException) as error:
        _validate_tenant_access(user)
    assert error.value.status_code==403
