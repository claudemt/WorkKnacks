import glob
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import urllib.parse
from pathlib import Path

from ..base import ProviderRegistry, ProviderMeta, TranscriptionProvider
from ...core.runtime import runtime_dir

_WEMEET_HOSTS = ('meeting.tencent.com', 'wemeet.qq.com',
                 'meeting.tencent.com.cn', 'voovmeeting.com')

def _dpapi_decrypt(blob: bytes) -> bytes:

    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD),
                    ('pbData', ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    in_blob = DATA_BLOB(len(blob), ctypes.cast(
        ctypes.create_string_buffer(blob), ctypes.POINTER(ctypes.c_char)))
    out_blob = DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None,
                                      None, None, 0, ctypes.byref(out_blob)):
        return None
    result = ctypes.string_at(out_blob.pbData, out_blob.cbData)
    ctypes.windll.kernel32.LocalFree(out_blob.pbData)
    return result

def _decrypt_cookie_blob(blob: bytes):

    if blob.startswith((b'v10', b'v20')):
        return _dpapi_decrypt(blob[3:]).decode('utf-8', 'ignore')
    if blob.startswith(b'v11'):
        return None
    return blob.decode('utf-8', 'ignore')

def _single_md(title: str, summary: str, transcript: str) -> str:

    return (f'# {title} 总结\n\n{summary}\n\n'
            f'---\n\n## 附：逐字稿\n\n{transcript}\n')

class WeMeetTranscribeProvider(TranscriptionProvider):
    meta = ProviderMeta(
        provider_id='wemeet',
        name='腾讯会议',
        category='transcribe',
        description='云录制总结 + 逐字稿',
        max_chunk_chars=0,
        max_chunks_per_sec=0.5,
        requires_auth=True,
        required_keys=['WEMEET_CORP_ID'],
        supported_formats=[],
    )

    C_PARAMS = {
        'c_app_id': '', 'c_os_model': 'web', 'c_os': 'web',
        'c_os_version': 'Mozilla/5.0', 'c_timestamp': '0', 'c_nonce': 'x',
        'c_app_version': '', 'c_instance_id': '5', 'rnds': 'x',
        'c_district': '0', 'platform': 'Web', 'c_app_uid': '',
        'c_account_corp_id': '210008052', 'c_lang': 'zh-CN',
    }

    def __init__(self):
        super().__init__()
        self.root = Path(__file__).resolve().parent.parent.parent.parent
        self.config_dir = self.root / 'config'
        self.cookies_path = self.config_dir / 'wemeet_cookies.json'
        self.records_path = self.config_dir / 'records_list.json'

        self.c_params = {**self.C_PARAMS,
                         'c_account_corp_id': self.config.get('WEMEET_CORP_ID',
                                                              '210008052')}

    def validate_auth(self) -> tuple[bool, str]:
        if self.cookies_path.exists():
            try:
                cookies = self._load_cookies()
            except Exception:
                return False, '登录态文件损坏，请到「⚙ 配置」重新导入/扫码'
            token = next((c for c in cookies
                          if c.get('name') == 'we_meet_token'), None)
            if token and len(token.get('value', '')) >= 50:
                return True, f'cookies 已存在 ({self.cookies_path.name})'
            return False, '登录态无效，请到「⚙ 配置」重新导入/扫码'
        return False, '需要先登录腾讯会议（桌面客户端导入 或 网页扫码）'

    def import_desktop_cookies(self, cookies_path=None) -> tuple[bool, str]:

        base = Path(os.environ.get(
            'APPDATA', str(Path.home() / 'AppData' / 'Roaming'))) \
            / 'Tencent' / 'WeMeet' / 'Global' / 'Data' / 'WebkitCacheData'
        candidates = []
        for d in glob.glob(str(base / '*')):
            ck = Path(d) / 'Default' / 'Network' / 'Cookies'
            if ck.exists():
                candidates.append(ck)
        if not candidates:
            return False, '未找到桌面客户端的 Cookie 库（先安装并登录腾讯会议客户端）'
        src = max(candidates, key=lambda p: p.stat().st_mtime)

        tmp = Path(tempfile.gettempdir()) / 'wemeet_cookies_import.db'
        tmp.unlink(missing_ok=True)
        try:

            try:
                shutil.copy2(src, tmp)
                con = sqlite3.connect(f'file:{tmp}?mode=ro', uri=True)
            except PermissionError:

                try:
                    uri = 'file:' + str(src).replace('\\', '/') + '?immutable=1'
                    con = sqlite3.connect(uri, uri=True)
                except Exception:
                    return (False,
                            'Cookie 库被腾讯会议客户端独占锁定——'
                            '请完全退出客户端（托盘图标右键 → 退出）后重试')
            con.text_factory = bytes
            rows = con.execute(
                "SELECT host_key, name, encrypted_value, path, is_secure, "
                "is_httponly, expires_utc FROM cookies "
                "WHERE host_key LIKE '%tencent.com%' OR host_key LIKE '%wemeet%' "
                "OR host_key LIKE '%voovmeeting%'").fetchall()
            con.close()
        finally:
            tmp.unlink(missing_ok=True)

        if not rows:
            return False, '客户端 Cookie 库里没有腾讯会议相关记录（先登录一次客户端）'

        cookies, ok_count, bad = [], 0, 0
        for host, name_b, blob, path, secure, httponly, expires in rows:
            try:
                host = host.decode('utf-8', 'ignore')
                name = name_b.decode('utf-8', 'ignore')
                value = _decrypt_cookie_blob(blob)
                if value is None:
                    bad += 1
                    continue

                if not any(h in host for h in _WEMEET_HOSTS):
                    continue
                cookies.append({
                    'name': name,
                    'value': value,
                    'domain': host,
                    'path': path,
                    'expires': expires / 1_000_000 if expires else -1,
                    'httpOnly': bool(httponly),
                    'secure': bool(secure),
                    'sameSite': 'Lax',
                })
                ok_count += 1
            except Exception:
                bad += 1

        if not cookies:
            return False, ('客户端 Cookie 加密格式无法自动解密——'
                           '请改用「网页扫码登录」或「手动粘贴 Cookie」')
        if not any(c['name'] in ('we_meet_token', 'wmuser_uid', 'app_uid')
                   for c in cookies):
            return False, 'Cookie 里没有登录凭据（客户端可能未登录）——请先登录客户端'

        self.config_dir.mkdir(exist_ok=True)
        out = Path(cookies_path) if cookies_path else self.cookies_path
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=1)
        return True, (f'已从桌面客户端导入 {ok_count} 条 cookie'
                      f'（{bad} 条无法解密，已跳过）→ {out.name}')

    def import_cookies_from_text(self, text: str, cookies_path=None) -> tuple[bool, str]:

        text = text.strip()
        if not text:
            return False, '内容为空'

        if text.startswith('['):
            try:
                data = json.loads(text)
                if not isinstance(data, list):
                    return False, 'JSON 不是数组格式'
                cookies = data
            except json.JSONDecodeError:
                return False, 'JSON 解析失败'
        else:
            cookies = []
            for part in re.split(r'[;\n]', text):
                part = part.strip()
                if '=' not in part:
                    continue
                name, value = part.split('=', 1)
                name = name.strip()
                if name.lower() in ('path', 'domain', 'expires', 'max-age',
                                    'samesite', 'secure', 'httponly'):
                    continue
                cookies.append({
                    'name': name,
                    'value': value.strip(),
                    'domain': 'meeting.tencent.com',
                    'path': '/',
                    'expires': -1,
                    'httpOnly': False,
                    'secure': True,
                    'sameSite': 'Lax',
                })
        if not cookies:
            return False, '未解析到任何 cookie'

        names = [c.get('name') for c in cookies]
        if not any(n in names for n in ('we_meet_token', 'wmuser_uid', 'app_uid')):
            return False, ('未找到登录凭据（需要 we_meet_token / wmuser_uid / '
                           'app_uid 之一）——请确认粘贴的是登录后的 cookie')

        self.config_dir.mkdir(exist_ok=True)
        out = Path(cookies_path) if cookies_path else self.cookies_path
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(cookies, f, ensure_ascii=False, indent=1)
        return True, f'已保存 {len(cookies)} 条 cookie → {out.name}'

    def login(self, qr_path: str = None) -> bool:

        from playwright.sync_api import sync_playwright
        if qr_path is None:
            qr_path = str(runtime_dir() / 'wemeet_qr.png')

        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            ctx = browser.new_context(viewport={'width': 1280, 'height': 900})
            page = ctx.new_page()
            page.goto('https://meeting.tencent.com/user-center/login',
                      wait_until='domcontentloaded', timeout=60000)

            qr = None
            for _ in range(15):
                time.sleep(2)
                qr = page.query_selector('canvas')
                if qr:
                    break
            if qr:
                qr.screenshot(path=qr_path)
                print(f'二维码已保存到: {qr_path}')
            else:
                print('!! 未找到二维码 canvas')

            print('请用手机腾讯会议/微信 APP 扫码登录(5分钟内)')
            for _ in range(150):
                time.sleep(2)
                cnames = [c['name'] for c in ctx.cookies()]
                if any(k in n for n in cnames for k in
                       ['access_token', 'skey', 'uin', 'token', 'SID', 'p_skey']):
                    print('登录成功!')
                    break
                if 'login' not in page.url and page.url != 'about:blank':
                    print('页面跳转:', page.url)
                    break
            else:
                print('超时未检测到登录')
                browser.close()
                return False
            json.dump(ctx.cookies(), open(self.cookies_path, 'w', encoding='utf-8'))
            print('cookies 已保存到', self.cookies_path)
            browser.close()
        return True

    def list_records(self) -> list[dict]:

        ok, msg = self.validate_auth()
        if not ok:
            raise RuntimeError(msg)
        from playwright.sync_api import sync_playwright
        cookies = self._load_cookies()

        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            ctx, page = self._open_page(browser, cookies)
            r = json.loads(self._api_fetch(
                page, '/v2/meetlog/main/query-all-record',
                {'page': 1, 'page_size': 100}))
            code = r.get('code')
            if code not in (0, None):
                browser.close()
                raise RuntimeError(
                    f'接口返回 {code}: {r.get("message", "未知错误")}'
                    '（登录态可能已失效，请到「⚙ 配置」重新导入/扫码）')
            data = r.get('data') or {}
            recs = data.get('record_list') or []
            seen = {}
            for rec in recs:
                seen.setdefault(rec['record_id'], rec)
            uni = list(seen.values())
            json.dump(uni, open(self.records_path, 'w', encoding='utf-8'),
                      ensure_ascii=False, indent=1)
            browser.close()
            return uni

    def export_records(self, records: list[dict], output_dir: str,
                       overwrite: bool = False) -> list[dict]:

        from playwright.sync_api import sync_playwright
        cookies = self._load_cookies()
        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='chrome', headless=True)
            ctx, page = self._open_page(browser, cookies)
            for rec in records:
                title = rec.get('title', '')
                seg = title.replace('.mp4', '')
                if not seg:
                    continue
                os.makedirs(output_dir, exist_ok=True)
                out_path = os.path.join(output_dir, f'{seg}-总结.md')
                if not overwrite and os.path.exists(out_path) \
                        and os.path.getsize(out_path) > 1000:
                    results.append({'seg': seg, 'skipped': True})
                    continue
                try:
                    sid = rec['share_id']
                    rid = rec['record_id']
                    mid = (rec.get('meeting_info') or {}).get('meeting_id', '')
                    transcript = self._fetch_transcript(page, rid, sid, mid)
                    summary = self._fetch_summary(page, rid, sid)
                    with open(out_path, 'w', encoding='utf-8') as f:
                        f.write(_single_md(title, summary, transcript))
                    print(f'    OK -> {out_path} ({len(transcript)} chars)')
                    results.append({'seg': seg, 'chars': len(transcript)})
                except Exception as e:
                    print(f'    FAIL {seg}: {e}')
                    results.append({'seg': seg, 'error': str(e)})
                time.sleep(0.5)
            browser.close()
        return results

    def _load_cookies(self) -> list[dict]:
        return json.load(open(self.cookies_path, encoding='utf-8'))

    def _open_page(self, browser, cookies):
        ctx = browser.new_context(viewport={'width': 1280, 'height': 900})
        ctx.add_cookies([{k: c[k] for k in ('name', 'value', 'domain', 'path')}
                         for c in cookies])
        page = ctx.new_page()
        page.goto('https://meeting.tencent.com/user-center',
                  wait_until='domcontentloaded', timeout=60000)
        return ctx, page

    def _api_fetch(self, page, path, body, qs=None):

        q = '?' + urllib.parse.urlencode({**self.c_params, **(qs or {})})
        return page.evaluate("""async ({path, body, q}) => {
            const r = await fetch('/wemeet-tapi' + path + q, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            });
            return await r.text();
        }""", {'path': path, 'body': body, 'q': q})

    def _fetch_transcript(self, page, rid, sid, mid):

        base = {'id': sid, 'pwd': '', 'activity_uid': '', 'page_source': 'record',
                'meeting_id': mid, 'recording_id': rid, 'share_id': '',
                'short_url_code': '', 'lang': 'zh', 'minutes_version': '0', 'limit': 20,
                'return_ori': 1, 'start_pid': 0, 'return_ori_minutes_translating': 1, 'fview': 1}
        all_paras, more, guard, last_pid = [], True, 0, 0
        while more and guard < 80:
            qs = {**self.c_params, 'mock': '1', **base}
            if guard > 0:
                qs['pid'] = last_pid
                qs['fview'] = '0'
            q = '?' + urllib.parse.urlencode(qs)
            r = page.evaluate("""async (q) => {
                const r = await fetch('/wemeet-cloudrecording-webapi/v1/minutes/detail' + q);
                return await r.text();
            }""", q)
            try:
                j = json.loads(r)
            except Exception:
                break
            if j.get('code') != 0:
                print(f'    [minutes/detail] code={j.get("code")} {j.get("message", "")}')
                break
            paras = (j.get('minutes') or {}).get('paragraphs') or []
            all_paras.extend(paras)
            more = bool(j.get('more'))
            if paras:
                last_pid = int(paras[-1]['pid'])
            guard += 1
            time.sleep(0.2)
        lines = []
        for p in sorted(all_paras, key=lambda x: int(x.get('pid', 0))):
            for s in p.get('sentences') or []:
                text = ''.join(w.get('text', '') for w in s.get('words') or []).strip()
                if text:
                    lines.append(text)
        return '\n'.join(lines)

    def _fetch_summary(self, page, rid, sid):
        r = json.loads(self._api_fetch(
            page, '/v2/meetlog/public/record-detail/get-full-summary',
            {'record_id': rid, 'share_id': sid, 'lang': 'zh', 'pwd': '',
             'activity_uid': ''}))
        return (r.get('data') or {}).get('full_summary', '')

    def _export_one(self, page, seg, sid, rid, mid, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        transcript = self._fetch_transcript(page, rid, sid, mid)
        summary = self._fetch_summary(page, rid, sid)
        out_path = os.path.join(output_dir, f'{seg}-总结.md')
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(_single_md(f'{seg}.mp4', summary, transcript))
        print(f'    OK -> {out_path} ({len(transcript)} chars)')

ProviderRegistry.register(WeMeetTranscribeProvider)

