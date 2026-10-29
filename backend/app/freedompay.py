"""Freedom Pay KG hosted checkout: bounded requests and signed flat/form/XML messages."""
import hashlib
import hmac
import re
import secrets
from email import policy
from email.parser import BytesParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET


class ProviderError(Exception):
    pass


def diagnostic(error):
    """Bounded diagnostics: never include response bodies, URLs or exception text."""
    reasons={
        'Unsafe provider response':'unsafe_response',
        'Invalid provider XML':'invalid_xml',
        'Invalid provider signature':'invalid_signature',
        'Unsupported KG API endpoint':'unsupported_endpoint',
        'Unsupported API method':'unsupported_method',
        'Provider confirmation unavailable':'transport_failure',
    }
    reason=reasons.get(str(error),'payment_validation_failed') if isinstance(error,ProviderError) else 'payment_validation_failed'
    cause=error.__cause__
    if isinstance(cause,HTTPError):
        return f'{reason} http_status={int(cause.code)}'
    if isinstance(cause,URLError):
        cause=cause.reason
    if isinstance(cause,TimeoutError):
        return f'{reason} cause=timeout'
    if isinstance(cause,OSError):
        return f'{reason} cause=network_error'
    return reason


def sign(script, values, secret):
    def flat(value):
        if isinstance(value,dict):
            return [part for key in sorted(value) if key!='pg_sig' for part in flat(value[key])]
        if isinstance(value,list):
            return [part for entry in value for part in flat(entry)]
        return [str(value) if value is not None else '']
    return hashlib.md5(';'.join([script,*flat(values),secret]).encode()).hexdigest()


def verify(script, values, secret):
    signature=values.get('pg_sig','')
    return isinstance(signature,str) and bool(secret) and bool(values.get('pg_salt')) and bool(re.fullmatch('[a-f0-9]{32}',signature)) and hmac.compare_digest(signature,sign(script,values,secret))


def parse_xml(raw):
    if len(raw)>131072 or b'\x00' in raw or re.search(br'<!\s*(DOCTYPE|ENTITY)',raw,re.I):
        raise ProviderError('Unsafe provider response')
    try:
        root=ET.fromstring(raw)
        if root.tag!='response' or root.attrib or not len(root):
            raise ValueError()
        def decode(node,depth=0):
            if depth>8 or node.attrib or (node.tail or '').strip():
                raise ValueError()
            children=list(node)
            if not children:
                return node.text or ''
            if (node.text or '').strip():
                raise ValueError()
            result={}
            for child in children:
                value=decode(child,depth+1)
                if child.tag in result:
                    if node.tag!='pg_refund_payments' or child.tag!='pg_refund_payment':
                        raise ValueError('Duplicate XML field')
                    if not isinstance(result[child.tag],list): result[child.tag]=[result[child.tag]]
                    result[child.tag].append(value)
                else:
                    result[child.tag]=value
            return result
        return decode(root)
    except (ET.ParseError,ValueError,RecursionError) as exc:
        raise ProviderError('Invalid provider XML') from exc


def form_values(raw,content_type):
    if len(raw)>65536:
        raise ValueError('Request too large')
    if content_type.split(';',1)[0].strip().lower()=='application/x-www-form-urlencoded':
        pairs=parse_qsl(raw.decode('utf-8'),keep_blank_values=True,strict_parsing=True,max_num_fields=100,errors='strict')
    elif content_type.split(';',1)[0].strip().lower()=='multipart/form-data':
        if '\r' in content_type or '\n' in content_type:
            raise ValueError('Invalid content type')
        message=BytesParser(policy=policy.default).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+raw)
        if not message.is_multipart() or message.defects:
            raise ValueError('Invalid form')
        pairs=[]
        for part in message.iter_parts():
            name=part.get_param('name',header='content-disposition')
            if part.is_multipart() or part.get_filename() is not None or not name or part.defects:
                raise ValueError('Files or invalid fields are not accepted')
            pairs.append((name,(part.get_payload(decode=True) or b'').decode('utf-8')))
    else:
        raise ValueError('Unsupported content type')
    result={}
    if not pairs or len(pairs)>100:
        raise ValueError('Invalid fields')
    for key,value in pairs:
        if key in result or not re.fullmatch('[A-Za-z0-9_]{1,100}',key) or len(value)>8192:
            raise ValueError('Duplicate or invalid fields')
        result[key]=value
    return result


def response_xml(script,status,secret,description=''):
    values={'pg_status':status,'pg_description':description,'pg_salt':secrets.token_hex(16)}
    values['pg_sig']=sign(script,values,secret)
    root=ET.Element('response')
    for key,value in values.items():
        ET.SubElement(root,key).text=value
    return ET.tostring(root,encoding='utf-8',xml_declaration=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


def api_base(settings):
    value=settings.freedompay_api_base.rstrip('/')
    if value not in {'https://api.freedompay.kg','https://test-api.freedompay.kg'}:
        raise ProviderError('Unsupported KG API endpoint')
    return value


def request_api(settings,path,values):
    if path not in {'/init_payment','/init_payment.php','/get_status3.php'}:
        raise ProviderError('Unsupported API method')
    data={**values,'pg_merchant_id':settings.freedompay_merchant_id,'pg_salt':secrets.token_hex(16)}
    secret=settings.freedompay_secret_key.get_secret_value()
    data['pg_sig']=sign(path.rsplit('/',1)[-1],data,secret)
    request=Request(api_base(settings)+path,data=urlencode(data).encode(),headers={'Content-Type':'application/x-www-form-urlencoded','Accept':'application/xml'},method='POST')
    try:
        with build_opener(NoRedirect).open(request,timeout=12) as result:
            raw=result.read(131073)
        parsed=parse_xml(raw)
        if not verify(path.rsplit('/',1)[-1],parsed,secret):
            raise ProviderError('Invalid provider signature')
        return parsed
    except (HTTPError,URLError,TimeoutError,OSError,ValueError) as exc:
        raise ProviderError('Provider confirmation unavailable') from exc


def safe_checkout_url(value):
    if not isinstance(value,str) or len(value)>4096:
        return False
    try:
        parsed=urlsplit(value)
        hostname=parsed.hostname or ''
        return parsed.scheme=='https' and not parsed.username and not parsed.password and parsed.port in (None,443) and hostname.endswith('.freedompay.kg') and not re.search(r'[\s\\]',value)
    except ValueError:
        return False
