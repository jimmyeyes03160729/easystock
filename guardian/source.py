"""Bounded Git/source reads; never imports inspected modules or executes their code."""
import re
import os
import subprocess
from pathlib import Path

TEXT = {'.py', '.js', '.cjs', '.mjs', '.ts', '.tsx', '.html', '.css', '.sh', '.json', '.yaml', '.yml', '.toml', '.service', '.timer', '.txt', '.example', '.md', '.ini', '.conf', '.cfg'}
MAX_FILE = 1024 * 1024
MAX_TOTAL = 24 * MAX_FILE


def git(root, *args):
    if not args or args[0] not in ('ls-files', 'rev-parse', 'show', 'diff', 'log', 'ls-tree'):
        raise ValueError('read_only_git_operation_required')
    result = subprocess.run(['git', '--no-pager', '-c', 'core.fsmonitor=false', '-C', str(root), *args], capture_output=True, timeout=20, check=True, env={**os.environ,'GIT_OPTIONAL_LOCKS':'0'})
    if len(result.stdout) > MAX_TOTAL:
        raise ValueError('git_output_limit')
    return result.stdout


def revision(root, value):
    if not re.fullmatch(r'[A-Za-z0-9_./~^+-]{1,160}', value) or value.startswith('-'):
        raise ValueError('invalid_revision')
    result = git(root, 'rev-parse', '--verify', '--end-of-options', value + '^{commit}').decode().strip()
    if not re.fullmatch(r'[a-f0-9]{40,64}', result):
        raise ValueError('invalid_commit')
    return result


def read_sources(root, commit=None):
    root = Path(root).resolve()
    if commit:
        # ls-files cannot describe historical trees; walk Git tree listings, never the filesystem.
        names = tree_files(root, commit)
    else:
        names = git(root, 'ls-files', '-z').decode().split('\0')
    files, total = {}, 0
    for name in sorted(filter(None, names)):
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('unsafe_tracked_path')
        path = root / rel
        textual = path.suffix.lower() in TEXT or path.name.startswith('Dockerfile') or path.name.startswith('.env')
        # Sensitive binary files are classified by name without reading their contents.
        if not textual:
            files[name] = None
            continue
        if commit:
            raw = git(root, 'show', commit + ':' + name)
        else:
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('tracked_symlink_not_read')
            if path.stat().st_size > MAX_FILE:
                raise ValueError('tracked_source_limit')
            raw = path.read_bytes()
        total += len(raw)
        if len(raw) > MAX_FILE or total > MAX_TOTAL:
            raise ValueError('source_size_limit')
        files[name] = raw
    return files


def tree_files(root, commit):
    # git ls-tree is read-only, with a resolved immutable revision.
    return git(root,'ls-tree','-rz','--name-only',commit).decode().split('\0')
