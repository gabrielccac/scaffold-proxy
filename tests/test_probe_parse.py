from __future__ import annotations

from scaffold_proxy.validator import _extract_probe


def test_extract_probe_json_ipwho() -> None:
    body = '{"ip":"1.2.3.4","success":true,"country_code":"BR","country":"Brazil"}'
    ip, country = _extract_probe(body)
    assert ip == "1.2.3.4"
    assert country == "BR"


def test_extract_probe_plain_ipify() -> None:
    ip, country = _extract_probe("168.181.151.168\n")
    assert ip == "168.181.151.168"
    assert country is None


def test_extract_probe_json_ipify() -> None:
    ip, country = _extract_probe('{"ip":"8.8.8.8"}')
    assert ip == "8.8.8.8"
    assert country is None
