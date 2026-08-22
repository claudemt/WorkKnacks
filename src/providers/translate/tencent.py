import hashlib
import hmac
import json
import time
import urllib.request
from datetime import datetime

from ..base import ProviderMeta, ProviderRegistry, TranslationProvider

class TencentTranslateProvider(TranslationProvider):
    meta = ProviderMeta(
        provider_id='tencent_tmt',
        name='腾讯 TMT',
        category='translate',
        description='500 万字符/月免费',
        max_chunk_chars=2000,
        max_chunks_per_sec=5.0,
        requires_auth=True,
        required_keys=['TENCENT_SECRET_ID', 'TENCENT_SECRET_KEY'],
        supported_formats=['.txt', '.md', '.tex', '.json'],
    )

    ENDPOINT = 'https://tmt.tencentcloudapi.com'
    SERVICE = 'tmt'
    REGION = 'ap-guangzhou'
    VERSION = '2018-03-21'
    ACTION = 'TextTranslate'

    @staticmethod
    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

    def validate_auth(self) -> tuple[bool, str]:
        sid = self.config.get('TENCENT_SECRET_ID')
        skey = self.config.get('TENCENT_SECRET_KEY')
        if not sid or not skey:
            return False, '请在 .env.local 中设置 TENCENT_SECRET_ID 和 TENCENT_SECRET_KEY'
        return True, '密钥已配置'

    def _translate(self, text: str, target_lang: str = 'zh',
                   source_lang: str = 'en') -> str:
        secret_id = self.config.get('TENCENT_SECRET_ID')
        secret_key = self.config.get('TENCENT_SECRET_KEY')
        if not secret_id or not secret_key:
            raise RuntimeError('缺少 TENCENT_SECRET_ID / TENCENT_SECRET_KEY')

        if target_lang == 'zh-Hans':
            target_lang = 'zh'
        payload = json.dumps({
            'SourceText': text,
            'Source': source_lang,
            'Target': target_lang,
            'ProjectId': 0,
        })

        timestamp = int(time.time())
        date = datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d')
        ct = 'application/json; charset=utf-8'

        canonical_headers = 'content-type:{0}\nhost:tmt.tencentcloudapi.com\n'.format(ct)
        signed_headers = 'content-type;host'
        hashed_payload = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        canonical_request = ('POST\n/\n\n' + canonical_headers + '\n'
                             + signed_headers + '\n' + hashed_payload)
        credential_scope = '{0}/{1}/tc3_request'.format(date, self.SERVICE)
        hashed_canonical = hashlib.sha256(
            canonical_request.encode('utf-8')).hexdigest()
        string_to_sign = ('TC3-HMAC-SHA256\n' + str(timestamp) + '\n'
                          + credential_scope + '\n' + hashed_canonical)

        kd = self._hmac(('TC3' + secret_key).encode('utf-8'), date)
        ks = self._hmac(kd, self.SERVICE)
        k = self._hmac(ks, 'tc3_request')
        signature = hmac.new(k, string_to_sign.encode('utf-8'),
                             hashlib.sha256).hexdigest()
        authorization = (
            'TC3-HMAC-SHA256 Credential={0}/{1}, '
            'SignedHeaders={2}, Signature={3}'.format(
                secret_id, credential_scope, signed_headers, signature))

        req = urllib.request.Request(
            self.ENDPOINT, data=payload.encode('utf-8'),
            headers={
                'Authorization': authorization,
                'Content-Type': ct,
                'Host': 'tmt.tencentcloudapi.com',
                'X-TC-Action': self.ACTION,
                'X-TC-Version': self.VERSION,
                'X-TC-Timestamp': str(timestamp),
                'X-TC-Region': self.REGION,
            })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if 'Response' in data and 'TargetText' in data['Response']:
            return data['Response']['TargetText']
        err = data.get('Response', {}).get('Error', {})
        raise RuntimeError(
            'Tencent TMT error: {0} - {1}'.format(
                err.get('Code'), err.get('Message')))

ProviderRegistry.register(TencentTranslateProvider)

