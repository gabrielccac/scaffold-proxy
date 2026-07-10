from __future__ import annotations

from scaffold_proxy.config import (
    IPIFY_PROBE_URL,
    MEUIP_PROBE_URL,
    apply_country,
    freeproxy_world_url,
    parse_countries,
)
from scaffold_proxy.config import Settings


def test_freeproxy_world_url_encodes_country() -> None:
    url = freeproxy_world_url("us")
    assert "country=US" in url
    assert url.startswith("https://www.freeproxy.world/?")


def test_apply_country_br_uses_meuip() -> None:
    settings = apply_country(Settings(), "BR")
    assert settings.country == "BR"
    assert settings.probe_url == MEUIP_PROBE_URL
    assert settings.expect_country == "BR"
    assert "country=BR" in settings.scrape_url


def test_apply_country_other_uses_ipify() -> None:
    settings = apply_country(Settings(), "US")
    assert settings.country == "US"
    assert settings.probe_url == IPIFY_PROBE_URL
    assert settings.expect_country == ""
    assert "country=US" in settings.scrape_url


def test_parse_countries_comma_and_space() -> None:
    assert parse_countries("BR,US,CA") == ["BR", "US", "CA"]
    assert parse_countries("br us ca") == ["BR", "US", "CA"]
    assert parse_countries("BR, US, BR") == ["BR", "US"]
