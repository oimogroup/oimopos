"""Installation metadata for the authenticated POS location."""

def build_manifest(branch: dict) -> dict:
    name = str(branch.get('name') or 'Касса').strip()
    address = str(branch.get('address') or '').strip()
    label = ' · '.join(part for part in (name, address) if part)
    return {
        'id': '/pos', 'name': f'Oimo POS · {label}', 'short_name': label,
        'description': f'Касса Oimo: {label}', 'lang': 'ru',
        'start_url': '/pos', 'scope': '/pos', 'display': 'standalone',
        'background_color': '#ffffff', 'theme_color': '#202123',
        'icons': [{'src': f'/vendor/pwa/pos-{size}.png', 'sizes': f'{size}x{size}',
                   'type': 'image/png', 'purpose': 'any maskable'} for size in (192, 512)],
    }
