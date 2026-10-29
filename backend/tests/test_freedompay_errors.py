"""Provider error responses must stay diagnostic and never confirm payments."""
from types import SimpleNamespace
from urllib.parse import parse_qs

import pytest

from app import freedompay as fp


@pytest.mark.parametrize('body,expected',[
    (b'<response><pg_status>error</pg_status><pg_error_code>11068</pg_error_code></response>',
     'provider_error_response provider_code=11068'),
    (b'<response><pg_status>error</pg_status><pg_error_code>9998</pg_error_code></response>',
     'provider_error_response provider_code=9998'),
    (b'<response><pg_status>error</pg_status><pg_error_code>private-data</pg_error_code></response>',
     'provider_error_response'),
    (b'<response><pg_status>ok</pg_status><pg_payment_status>success</pg_payment_status></response>',
     'invalid_signature'),
])
def test_error_codes_are_bounded_and_unsigned_success_is_rejected(monkeypatch,body,expected):
    cfg=SimpleNamespace(freedompay_api_base='https://api.freedompay.kg',
                        freedompay_merchant_id='123',
                        freedompay_secret_key=SimpleNamespace(get_secret_value=lambda:'test-secret'))
    class Reply:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,limit): return body
    def open_request(request,timeout):
        fields={key:values[0] for key,values in parse_qs(request.data.decode()).items()}
        assert fp.verify('get_status3.php',fields,'test-secret')
        return Reply()
    monkeypatch.setattr(fp,'build_opener',lambda *args:SimpleNamespace(open=open_request))
    with pytest.raises(fp.ProviderError) as captured:
        fp.request_api(cfg,'/get_status3.php',{'pg_payment_id':'456'})
    assert fp.diagnostic(captured.value)==expected
