from __future__ import annotations

from scaffold_proxy.parse import parse_proxy_table


def test_parse_proxy_table_extracts_rows() -> None:
    html = """
    <table class="table"><tbody>
      <tr>
        <td style="font-weight: 500;">189.126.66.189</td>
        <td><a href="/?port=8080">8080</a></td>
        <td><a href="/?country=BR" class="country-cell"><span class="flag flag-br"></span></a></td>
        <td><span class="text-truncate" title="Paraipaba">Paraipaba</span></td>
        <td><span>4639 ms</span></td>
        <td><a href="/?type=http" class="badge badge-warning">http</a></td>
        <td><a href="/?anonymity=1">No</a></td>
      </tr>
      <tr>
        <td style="font-weight: 500;">129.151.38.112</td>
        <td><a href="/?port=443">443</a></td>
        <td><a href="/?country=BR" class="country-cell"></a></td>
        <td><span class="text-truncate" title="Sao Paulo">Sao Paulo</span></td>
        <td><span>2390 ms</span></td>
        <td><a href="/?type=https" class="badge badge-success">https</a></td>
        <td><a href="/?anonymity=4">High</a></td>
      </tr>
    </tbody></table>
    """
    rows = parse_proxy_table(html)
    assert len(rows) == 2
    assert rows[0].host == "189.126.66.189"
    assert rows[0].port == 8080
    assert rows[0].protocol == "http"
    assert rows[0].country == "BR"
    assert rows[0].city == "Paraipaba"
    assert rows[0].listed_speed_ms == 4639
    assert rows[1].protocol == "https"
    assert rows[1].anonymity == "High"
