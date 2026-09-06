"""Isolated synthetic browser-test server; never opens the working database."""
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent

@contextmanager
def synthetic_server():
    with tempfile.TemporaryDirectory(prefix='smartphrase-browser-') as directory:
        os.environ.update(DJANGO_SETTINGS_MODULE='config.settings',
                          DATABASE_PATH=str(Path(directory) / 'synthetic.sqlite3'),
                          AI_PROVIDER='mock', AI_API_KEY='', AI_MODEL='', AI_BASE_URL='',
                          PRODUCTION='0', ALLOWED_HOSTS='127.0.0.1,localhost,testserver',
                          DJANGO_ALLOW_ASYNC_UNSAFE='true')
        sys.path.insert(0, str(ROOT))
        import django
        django.setup()
        from django.core.management import call_command
        from django.db import connections
        call_command('migrate', verbosity=0)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        server = subprocess.Popen([sys.executable, 'manage.py', 'runserver',
                                   f'127.0.0.1:{port}', '--noreload'], cwd=ROOT,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Synthetic browser server exited.')
                try:
                    with urlopen(url + '/login/', timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError('Synthetic browser server did not start.')
            yield url
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait()
            connections.close_all()
