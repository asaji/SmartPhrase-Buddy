#!/usr/bin/env python3
import os, sys
from pathlib import Path

# Local convenience: load KEY=VALUE lines from an ignored .env next to this file.
# Real environment variables always win; production uses the systemd EnvironmentFile.
# Skipped for `test` so a local .env never changes test behaviour.
_envfile = Path(__file__).resolve().parent / '.env'
if _envfile.exists() and 'test' not in sys.argv:
    for _line in _envfile.read_text().splitlines():
        _line = _line.split('#', 1)[0].strip()
        if '=' not in _line:
            continue
        _key, _val = _line.split('=', 1)
        _key, _val = _key.strip(), _val.strip().strip('"').strip("'")
        if _key and _key not in os.environ:
            os.environ[_key] = _val

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
from django.core.management import execute_from_command_line
execute_from_command_line(sys.argv)
