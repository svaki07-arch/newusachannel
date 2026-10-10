"""Update the four application files, preserving keys, venvs and a timestamped backup.

Run from the app checkout: python update_local.py [--start].
"""
import argparse
import io
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile

import httpx

FILES = ('app/main.py', 'app/static/index.html', 'app/static/app.js', 'app/static/style.css')


def apply_update(root, content):
    root = Path(root).resolve()
    if not (root / 'app/main.py').is_file():
        raise ValueError('Run from the application folder containing app/main.py')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        prefixes = {name[:-len('app/main.py')] for name in archive.namelist() if name.endswith('/app/main.py')}
        if len(prefixes) != 1:
            raise ValueError('Unexpected archive structure')
        prefix = prefixes.pop()
        downloads = {}
        for name in FILES:
            entry = archive.getinfo(prefix + name)
            if entry.file_size > 2 * 1024 * 1024:
                raise ValueError('Unexpected application file size')
            downloads[name] = archive.read(entry)
    compile(downloads['app/main.py'], 'app/main.py', 'exec')
    backup = root / 'backups' / str(time.time_ns())
    for name in FILES:
        saved = backup / name
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, saved)
    for name, data in downloads.items():
        target = root / name
        temporary = target.with_name(target.name + '.update-tmp')
        temporary.write_bytes(data)
        temporary.replace(target)
    return backup


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', action='store_true')
    args = parser.parse_args()
    root = Path.cwd()
    if not (root / 'app/main.py').is_file():
        raise SystemExit('Открой терминал в папке приложения.')
    print('Скачиваю обновление…', flush=True)
    try:
        data = bytearray()
        with httpx.stream('GET', 'https://codeload.github.com/svaki07-arch/newusachannel/zip/refs/heads/main',
                          timeout=60, follow_redirects=True) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 20 * 1024 * 1024:
                    raise ValueError('Archive exceeds 20 MB')
        backup = apply_update(root, bytes(data))
    except Exception as exc:
        raise SystemExit(f'Обновление не завершено: {type(exc).__name__}: {exc}')
    print(f'ГОТОВО. API-ключи сохранены. Резервная копия: {backup}', flush=True)
    if args.start:
        print('Запускаю приложение. Открой браузер; терминал останется занят сервером.', flush=True)
        os.execv(sys.executable, [sys.executable, '-m', 'uvicorn', 'app.main:app',
                                 '--host', '127.0.0.1', '--port', '8000'])


if __name__ == '__main__':
    main()
