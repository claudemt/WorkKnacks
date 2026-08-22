import shutil
import subprocess
from datetime import datetime
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / 'skills'

SKILL_BY_CATEGORY = {
    'translate': 'translate-policy.md',
    'transcribe': 'transcribe-policy.md',
    'parse': 'parse-policy.md',
}


def skill_text(category: str = 'transcribe') -> str:
    name = SKILL_BY_CATEGORY.get(category, 'transcribe-policy.md')
    return (SKILLS_DIR / name).read_text(encoding='utf-8')


def _needs_shell(path: str) -> bool:
    return path.lower().endswith(('.cmd', '.bat'))


def detect_claude() -> tuple[bool, str]:
    path = shutil.which('claude')
    if not path:
        return False, '未检测到本机 Claude Code（需先安装 Claude Code CLI）'
    try:
        r = subprocess.run([path, '--version'], capture_output=True,
                           text=True, timeout=30, shell=_needs_shell(path))
        version = (r.stdout or r.stderr).strip().splitlines()
        return True, version[0] if version else '可用'
    except Exception as e:
        return False, f'claude 命令存在但调用失败: {e}'


def _run_claude(prompt: str) -> str:
    path = shutil.which('claude')
    if not path:
        raise RuntimeError('未检测到本机 Claude Code')
    shell = _needs_shell(path)
    if shell:
        r = subprocess.run(f'"{path}" -p', input=prompt, capture_output=True,
                           text=True, timeout=1800, shell=True)
    else:
        r = subprocess.run([path, '-p'], input=prompt, capture_output=True,
                           text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f'Claude 调用失败: {r.stderr[-300:]}')
    return r.stdout.strip()


def polish(file_path: str, feedback: str = None, history_path: str = None,
           category: str = 'transcribe') -> str:
    """让本机 Claude 直接读取文件润色，不把全文塞进 prompt。

    长文由 agent 自行处理（其上下文管理会自动分块/摘要），
    无需在本地做字符级分段。
    """

    parts = [skill_text(category), '---']
    parts.append(f'待润色文件：{file_path}')
    if history_path and Path(history_path).exists():
        parts.append(
            f'此前轮次的意见与输出见文件 {history_path}'
            f'（仅作上下文，本轮输出以最新意见为准，不要复述历史）'
        )
    if feedback:
        parts.append(f'用户本轮提示词：\n{feedback}')
    parts.append(
        '请先用 Read 工具完整阅读待润色文件，'
        '然后直接输出润色后的全文，不要输出任何解释或说明。'
    )
    return _run_claude('\n\n'.join(parts))


def log_dir_for(file_path: str, project_root: str | Path = None) -> Path:
    root = Path(project_root).expanduser().resolve() if project_root else (
        Path(file_path).resolve().parent
    )
    return root / '.workknacks' / 'ai-logs' / Path(file_path).stem


def log_path_for(file_path: str, project_root: str | Path = None) -> Path:
    return log_dir_for(file_path, project_root) / (
        Path(file_path).stem + '.log.md'
    )


def append_log(
    file_path: str,
    round_no: int,
    feedback: str,
    output: str,
    project_root: str | Path = None,
) -> Path:
    log = log_path_for(file_path, project_root)
    log.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y-%m-%d %H:%M')
    with open(log, 'a', encoding='utf-8') as f:
        if round_no == 1:
            f.write(f'# AI 润色记录: {Path(file_path).name}\n\n')
        f.write(f'## 第{round_no}轮 · {ts}\n提示词: {feedback or "（无）"}\n\n')
        f.write(output + '\n\n---\n\n')
    return log


def load_log(file_path: str, project_root: str | Path = None) -> str:
    log = log_path_for(file_path, project_root)
    if log.exists():
        return log.read_text(encoding='utf-8')
    return ''
