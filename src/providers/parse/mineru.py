import glob
import os
import shutil
import subprocess
from pathlib import Path

from ..base import ParseProvider, ProviderMeta, ProviderRegistry


def md_to_pdf(md_path: str) -> str:
    pdf = os.path.splitext(md_path)[0] + '.pdf'
    if not shutil.which('pandoc'):
        return ''
    r = subprocess.run(
        ['pandoc', md_path, '-o', pdf, '--pdf-engine=xelatex',
         '-V', 'CJKmainfont=Microsoft YaHei', '--standalone'],
        capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not os.path.exists(pdf):
        return ''
    return pdf


class MinerUParseProvider(ParseProvider):
    meta = ProviderMeta(
        provider_id='mineru',
        name='MinerU',
        category='parse',
        description='PDF/图片/DOCX → Markdown',
        max_chunk_chars=0,
        max_chunks_per_sec=0,
        requires_auth=True,
        required_keys=['MINERU_TOKEN'],
        supported_formats=['.pdf', '.png', '.jpg', '.jpeg', '.docx', '.pptx'],
    )

    def validate_auth(self) -> tuple[bool, str]:
        try:
            r = subprocess.run(['mineru-open-api', '--version'],
                               capture_output=True, text=True)
            if r.returncode == 0:
                return True, 'mineru-open-api 可用'
            return False, 'mineru-open-api 未安装'
        except FileNotFoundError:
            return False, 'mineru-open-api 未安装（pip install mineru-open-api）'

    def process_file(self, input_path: str, output_dir: str) -> str:
        os.makedirs(output_dir, exist_ok=True)

        backup = os.path.join(output_dir, os.path.basename(input_path))
        if os.path.abspath(backup) != os.path.abspath(input_path):
            shutil.copy2(input_path, backup)

        before = set(glob.glob(os.path.join(output_dir, '*.md')))
        token = self.config.get('MINERU_TOKEN')
        if token:
            cmd = ['mineru-open-api', 'extract', input_path, '-o', output_dir]
        else:
            cmd = ['mineru-open-api', 'flash-extract',
                   input_path, '-o', output_dir]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if r.returncode != 0:
            raise RuntimeError(f'MinerU 解析失败: {(r.stderr or r.stdout)[-300:]}')

        after = set(glob.glob(os.path.join(output_dir, '*.md')))
        new_mds = after - before
        if not new_mds:
            raise RuntimeError('MinerU 未生成 Markdown 文件')
        md = max(new_mds, key=os.path.getmtime)

        pdf = md_to_pdf(md)
        return md + (f' + {pdf}' if pdf else '')


ProviderRegistry.register(MinerUParseProvider)
