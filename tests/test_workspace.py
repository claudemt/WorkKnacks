from pathlib import Path

from src.core.workspace import ProjectWorkspace


def test_workspace_scans_documents_and_excludes_private_outputs(tmp_path):
    (tmp_path / 'notes.md').write_text('# Notes', encoding='utf-8')
    nested = tmp_path / 'materials'
    nested.mkdir()
    (nested / 'paper.pdf').write_bytes(b'%PDF')
    translated = tmp_path / 'notes-翻译.md'
    translated.write_text(
        '译文',
        encoding='utf-8',
    )
    (tmp_path / '.workknacks').mkdir()
    (tmp_path / '.workknacks' / 'state.json').write_text(
        '{}',
        encoding='utf-8',
    )

    workspace = ProjectWorkspace(tmp_path).ensure()
    assert [path.name for path in workspace.iter_documents()] == [
        'notes-翻译.md',
        'notes.md',
        'paper.pdf',
    ]
    assert workspace.output_dir_for(tmp_path / 'notes.md') == tmp_path
    assert workspace.translated_path(tmp_path / 'notes.md') == translated
    workspace.record_action(
        tmp_path / 'notes.md',
        'translate',
        'done',
        outputs=[str(translated)],
    )
    assert [path.name for path in workspace.iter_documents()] == [
        'notes.md',
        'paper.pdf',
    ]


def test_list_dir_shows_folders_and_files_non_recursive(tmp_path):
    (tmp_path / 'notes.md').write_text('# Notes', encoding='utf-8')
    sub = tmp_path / 'materials'
    sub.mkdir()
    (sub / 'paper.pdf').write_bytes(b'%PDF')
    (tmp_path / '.workknacks').mkdir()

    workspace = ProjectWorkspace(tmp_path).ensure()
    folders, docs = workspace.list_dir('')
    assert [f.name for f in folders] == ['materials']
    assert [d.name for d in docs] == ['notes.md']

    folders, docs = workspace.list_dir('materials')
    assert folders == []
    assert [d.name for d in docs] == ['paper.pdf']


def test_list_dir_excludes_generated_outputs_and_hidden(tmp_path):
    src = tmp_path / 'a.md'
    src.write_text('x', encoding='utf-8')
    out = tmp_path / 'a-翻译.md'
    out.write_text('y', encoding='utf-8')
    (tmp_path / '.hidden.txt').write_text('h', encoding='utf-8')
    workspace = ProjectWorkspace(tmp_path).ensure()
    workspace.record_action(src, 'translate', 'done', outputs=[str(out)])

    _, docs = workspace.list_dir('')
    assert [d.name for d in docs] == ['a.md']


def test_workspace_persists_action_status_in_private_folder(tmp_path):
    source = tmp_path / 'source.md'
    output = tmp_path / '翻译' / 'source-翻译.md'
    source.write_text('source', encoding='utf-8')
    output.parent.mkdir()
    output.write_text('translated', encoding='utf-8')

    workspace = ProjectWorkspace(tmp_path).ensure()
    workspace.record_action(
        source,
        'translate',
        'done',
        outputs=[str(output)],
        message='处理完成',
    )

    reloaded = ProjectWorkspace(tmp_path).ensure()
    assert reloaded.category_status(source, 'translate') == '已完成'
    assert reloaded.file_state(source)['translate']['message'] == '处理完成'
    assert (tmp_path / '.workknacks' / 'state.json').exists()
    assert reloaded.progress_path == Path(tmp_path) / '.workknacks' / 'progress.json'
