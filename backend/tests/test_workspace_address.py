from app.workspace_address import request_subdomain, root_domain, slugify, validate_subdomain, workspace_url


def test_workspace_address_is_separate_human_readable_label():
    assert slugify("Buffet") == "buffet"
    assert slugify("Кафе Утро") == "kafe-utro"
    assert slugify("www") == "oimo-www"


def test_workspace_url_and_host_resolution():
    domain = root_domain("https://www.oimopos.com")
    assert domain == "oimopos.com"
    assert workspace_url("buffet", "https://oimopos.com") == "https://buffet.oimopos.com"
    assert request_subdomain("buffet.oimopos.com", domain) == "buffet"
    assert request_subdomain("www.oimopos.com", domain) is None
    assert request_subdomain("oimopos.com", domain) is None
    assert request_subdomain("buffet.onrender.com", domain) is None


def test_workspace_label_validation():
    assert validate_subdomain("Buffet-2") == "buffet-2"
    for value in ("www", "a", "-buffet", "buffet-", "two words", "ёда"):
        try:
            validate_subdomain(value)
        except ValueError:
            continue
        raise AssertionError(f"invalid workspace label accepted: {value}")
