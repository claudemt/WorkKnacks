import uuid, time, sys, io
from ..base import TranslationProvider, ProviderMeta, ProviderRegistry

class DeepLTranslateProvider(TranslationProvider):
    meta = ProviderMeta(
        provider_id='deepl_oneshot',
        name='DeepL',
        category='translate',
        description='免密钥，走 iOS 端点直连',
        max_chunk_chars=1350,
        max_chunks_per_sec=1.0,
        requires_auth=False,
        required_keys=[],
        supported_formats=['.txt', '.md', '.tex', '.json', '.srt', '.vtt'],
    )

    def __init__(self):
        super().__init__()
        self._session = None

    def _get_session(self):
        if self._session is None:
            from curl_cffi import requests as creq
            self._session = creq.Session(impersonate='safari18_0')
            self._session.get('https://www.deepl.com/translator', timeout=20)
        return self._session

    def validate_auth(self) -> tuple[bool, str]:
        try:
            from curl_cffi import requests as creq
            return True, 'curl_cffi 可用'
        except ImportError:
            return False, '需要安装 curl_cffi: pip install curl_cffi'

    def check_connectivity(self) -> tuple[bool, str]:
        ok, msg = self.validate_auth()
        if not ok:
            return False, msg
        try:
            out = self._translate('connectivity test', 'zh-Hans', 'en')
            if out is None:
                return False, '触发限流（HTTP 429），请稍后重试'
            if not out or not out.strip():
                return False, 'API 返回为空'
            return True, f'连通正常（返回：{out[:40]}）'
        except Exception as exc:
            return False, f'连接失败：{exc}'

    def _translate(self, text: str, target_lang: str = 'zh-Hans',
                   source_lang: str = 'en') -> str:

        from curl_cffi import requests as creq
        session = self._get_session()

        body = {
            'text': [text],
            'target_lang': target_lang,
            'source_lang': source_lang,
            'usage_type': 'translate',
            'app_information': {
                'os': 'iOS',
                'os_version': '26.0',
                'app_version': '26.42',
                'app_build': self.config.get('DEEPL_IOS_APP_BUILD', '5443737'),
                'instance_id': str(uuid.uuid4()),
            },
        }
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'None',
            'x-app-os-version': '26.0',
            'x-app-instance-id': str(uuid.uuid4()),
            'x-app-session-id': str(uuid.uuid4()),
            'User-Agent': 'DeepL/26.42 CFNetwork/3826.600.41 Darwin/25.0.0',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        }

        t0 = time.time()
        resp = session.post(
            'https://oneshot-free.www.deepl.com/v1/translate',
            json=body, headers=headers, timeout=30
        )
        elapsed = time.time() - t0

        if resp.status_code == 429:
            return None

        if resp.status_code != 200:
            raise RuntimeError(f'DeepL HTTP {resp.status_code}: {resp.text[:200]}')

        data = resp.json()
        translations = data.get('translations') or []
        if not translations:
            raise RuntimeError(f'DeepL 无译文: {resp.text[:200]}')

        return translations[0].get('text', '')

ProviderRegistry.register(DeepLTranslateProvider)

