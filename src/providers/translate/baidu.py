import hashlib, json, random, urllib.request, urllib.parse
from ..base import TranslationProvider, ProviderMeta, ProviderRegistry

class BaiduTranslateProvider(TranslationProvider):
    meta = ProviderMeta(
        provider_id='baidu',
        name='百度翻译',
        category='translate',
        description='100 万字符/月免费',
        max_chunk_chars=6000,
        max_chunks_per_sec=10.0,
        requires_auth=True,
        required_keys=['BAIDU_APP_ID', 'BAIDU_KEY'],
        supported_formats=['.txt', '.md', '.tex', '.json'],
    )

    ENDPOINT = 'https://fanyi-api.baidu.com/api/trans/vip/translate'

    def validate_auth(self) -> tuple[bool, str]:
        appid = self.config.get('BAIDU_APP_ID')
        key = self.config.get('BAIDU_KEY')
        if not appid or not key:
            return False, '请在 .env.local 中设置 BAIDU_APP_ID 和 BAIDU_KEY'
        return True, '密钥已配置'

    def _translate(self, text: str, target_lang: str = 'zh',
                   source_lang: str = 'en') -> str:
        appid = self.config.get('BAIDU_APP_ID')
        key = self.config.get('BAIDU_KEY')
        salt = str(random.randint(10000, 99999))
        sign_str = appid + text + salt + key
        sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest()

        if target_lang == 'zh-Hans':
            target_lang = 'zh'
        params = {
            'q': text,
            'from': source_lang,
            'to': target_lang,
            'appid': appid,
            'salt': salt,
            'sign': sign,
        }
        url = self.ENDPOINT + '?' + urllib.parse.urlencode(params)
        resp = urllib.request.urlopen(url, timeout=30)
        data = json.loads(resp.read().decode('utf-8'))

        if 'trans_result' in data:
            return data['trans_result'][0]['dst']

        err_code = data.get('error_code', '')
        err_msg = data.get('error_msg', str(data))
        raise RuntimeError(f'Baidu translate error {err_code}: {err_msg}')

ProviderRegistry.register(BaiduTranslateProvider)

