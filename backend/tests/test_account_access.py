from pydantic import ValidationError
import pytest

from app.account_access import EmailInput, ResetInput, TokenInput


def test_email_normalizes_without_accepting_extra_fields():
    assert EmailInput(email=' OWNER@EXAMPLE.COM ').email=='owner@example.com'
    with pytest.raises(ValidationError): EmailInput(email='a@example.com',user_id=1)


@pytest.mark.parametrize('token',['short','x'*129,'x'*42+'<','x'*42+' '])
def test_recovery_rejects_unbounded_or_malformed_token(token):
    with pytest.raises(ValidationError): TokenInput(token=token)


def test_password_policy_and_token_purpose_payload_are_bounded():
    with pytest.raises(ValidationError): ResetInput(token='x'*43,password='short')
    with pytest.raises(ValidationError): ResetInput(token='x'*43,password='x'*201)
    with pytest.raises(ValidationError): ResetInput(token='x'*43,password='x'*12,user_id=1)
