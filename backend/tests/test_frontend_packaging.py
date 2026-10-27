"""Every local script and stylesheet referenced by a shipped page must ship too."""
from html.parser import HTMLParser
from pathlib import Path
import shlex
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        source = values.get('src') if tag == 'script' else values.get('href') if tag == 'link' and values.get('rel') == 'stylesheet' else None
        if source:
            url = urlsplit(source)
            if not url.scheme and not url.netloc:
                self.paths.add(url.path.lstrip('/'))


@pytest.mark.parametrize('dockerfile', ['render.Dockerfile', 'frontend.Dockerfile'])
def test_shipped_html_assets_are_in_docker_image(dockerfile):
    copied = set()
    for line in (ROOT / dockerfile).read_text().splitlines():
        parts = shlex.split(line)
        if parts and parts[0] == 'COPY':
            for source in parts[1:-1]:
                path = ROOT / source
                if path.is_dir():
                    copied.update(p.relative_to(ROOT).as_posix() for p in path.rglob('*') if p.is_file())
                else:
                    copied.add(source)
    for page in sorted(p for p in copied if p.endswith('.html') and '/' not in p):
        assets = Assets()
        assets.feed((ROOT / page).read_text())
        missing = assets.paths - copied
        assert not missing, f'{dockerfile}: {page} references unpackaged files: {sorted(missing)}'
