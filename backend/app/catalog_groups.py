"""Recover imported variant groups whose original parent no longer exists."""


def repair_missing_parents(rows):
    identities = {str(row['id']) for row in rows}
    groups = {}
    for row in rows:
        parent = row.get('parentId')
        if parent is not None and str(parent) not in identities:
            groups.setdefault(str(parent), []).append(row)
    for members in groups.values():
        root = min(members, key=lambda row: (row.get('is_active') is False, str(row['id'])))
        for row in members:
            row['parentId'] = None if row is root else root['id']
