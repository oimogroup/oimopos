"""Small responses for owner catalog edits; unchanged photos stay in the browser."""

CATALOG_ACTIONS = {"recipe.upsert", "recipe.group.upsert", "preparation.upsert"}
CATALOG_LISTS = {"recipes", "preparations", "modifierSets"}


def state_patch(before: dict, after: dict) -> dict:
    replaced, collections = {}, {}
    for key, value in after.items():
        if key in before and before[key] == value:
            continue
        previous = before.get(key)
        if key in CATALOG_LISTS and isinstance(previous, list) and isinstance(value, list):
            old = {str(row["id"]): row for row in previous}
            new = {str(row["id"]): row for row in value}
            collections[key] = {
                "upsert": [row for identifier, row in new.items() if old.get(identifier) != row],
                "order": list(new),
            }
        else:
            replaced[key] = value
    return {"replace": replaced, "collections": collections,
            "remove": [key for key in before if key not in after]}
