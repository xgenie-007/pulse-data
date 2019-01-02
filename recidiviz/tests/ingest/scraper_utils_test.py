# Recidiviz - a platform for tracking granular recidivism metrics in real time
# Copyright (C) 2018 Recidiviz, Inc.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# =============================================================================

"""Tests for ingest/scraper_utils.py."""


from datetime import date
from lxml import html
from mock import patch
import pytest

from recidiviz.ingest import scraper_utils


def test_normalize_key_value_row():
    key_html = '<td headers="crime"> BURGLARY 2ND                   &nbsp;</td>'
    value_html = '<td headers="class">C  &nbsp;</td>'

    key = html.fromstring(key_html)
    value = html.fromstring(value_html)

    normalized = scraper_utils.normalize_key_value_row([key, value])
    assert normalized == ("BURGLARY 2ND", "C")


def test_normalize_key_value_row_with_nesting():
    key_html = '''
        <td scope="row" id="t3f">
            <a href="http://www.doccs.ny.gov/univinq/fpmsdoc.htm#pht" 
            title="Definition of Parole Hearing Type">
            Parole Hearing Type</a></td>
        '''
    value_html = '<td headers="t3f">' \
                 'APPROVED OPEN DATE/6 MO AFT INIT APPEAR   &nbsp;</td>'

    key = html.fromstring(key_html)
    value = html.fromstring(value_html)

    normalized = scraper_utils.normalize_key_value_row([key, value])
    assert normalized == ("Parole Hearing Type",
                          "APPROVED OPEN DATE/6 MO AFT INIT APPEAR")


def test_normalize_key_value_row_with_nesting_empty_value():
    key_html = '''
        <td scope="row" id="t3e">
             <a href="http://www.doccs.ny.gov/univinq/fpmsdoc.htm#phd" 
             title="Definition of Parole Hearing Date">
             Parole Hearing Date</a></td>
        '''
    value_html = '<td headers="t3e"> &nbsp;</td>'

    key = html.fromstring(key_html)
    value = html.fromstring(value_html)

    normalized = scraper_utils.normalize_key_value_row([key, value])
    assert normalized == ("Parole Hearing Date", "")


def test_calculate_age_earlier_month():
    birthdate = date(1989, 6, 17)
    check_date = date(2014, 4, 15)

    assert scraper_utils.calculate_age(birthdate, check_date) == 24


def test_calculate_age_same_month_earlier_date():
    birthdate = date(1989, 6, 17)
    check_date = date(2014, 6, 16)

    assert scraper_utils.calculate_age(birthdate, check_date) == 24


def test_calculate_age_same_month_same_date():
    birthdate = date(1989, 6, 17)
    check_date = date(2014, 6, 17)

    assert scraper_utils.calculate_age(birthdate, check_date) == 25


def test_calculate_age_same_month_later_date():
    birthdate = date(1989, 6, 17)
    check_date = date(2014, 6, 18)

    assert scraper_utils.calculate_age(birthdate, check_date) == 25


def test_calculate_age_later_month():
    birthdate = date(1989, 6, 17)
    check_date = date(2014, 7, 11)

    assert scraper_utils.calculate_age(birthdate, check_date) == 25


def test_calculate_age_birthdate_unknown():
    assert scraper_utils.calculate_age(None) is None


class TestGetProxies:
    """Tests for the get_proxies method in the module."""

    @patch('recidiviz.utils.secrets.get_secret')
    @patch('recidiviz.utils.environment.in_prod')
    def test_get_proxies_prod(self, mock_in_prod, mock_secret):
        mock_in_prod.return_value = True
        test_secrets = {
            'proxy_url': 'proxy.net/',
            'proxy_user': 'real_user',
            'proxy_password': 'real_password',
        }
        mock_secret.side_effect = test_secrets.get

        proxies = scraper_utils.get_proxies()
        assert proxies == {'http': 'http://real_user:real_password@proxy.net/'}

    @patch('recidiviz.utils.secrets.get_secret')
    @patch('recidiviz.utils.environment.in_prod')
    def test_get_proxies_local_no_user(self, mock_in_prod, mock_secret):
        mock_in_prod.return_value = True
        test_secrets = {
            'proxy_url': 'proxy.net/',
            'proxy_password': 'real_password',
        }
        mock_secret.side_effect = test_secrets.get

        with pytest.raises(Exception) as exception:
            scraper_utils.get_proxies()
        assert str(exception.value) == 'No proxy user/pass'

    @patch('recidiviz.utils.secrets.get_secret')
    @patch('recidiviz.utils.environment.in_prod')
    def test_get_proxies_local(self, mock_in_prod, mock_secret):
        mock_in_prod.return_value = False
        test_secrets = {
            'proxy_url': 'proxy.biz/',
            'test_proxy_user': 'user',
            'test_proxy_password': 'password',
        }
        mock_secret.side_effect = test_secrets.get

        proxies = scraper_utils.get_proxies()
        assert proxies is None

class TestGetHeaders:
    """Tests for the get_headers method in the module."""

    @patch('recidiviz.utils.secrets.get_secret')
    @patch('recidiviz.utils.environment.in_prod')
    def test_get_headers(self, mock_in_prod, mock_secret):
        # This is prod behaviour
        mock_in_prod.return_value = True
        user_agent = 'test_user_agent'

        test_secrets = {'user_agent': user_agent}
        mock_secret.side_effect = test_secrets.get

        headers = scraper_utils.get_headers()
        assert headers == {'User-Agent': user_agent}

    @patch('recidiviz.utils.secrets.get_secret')
    @patch('recidiviz.utils.environment.in_prod')
    def test_get_headers_missing_user_agent_in_prod(self, mock_in_prod,
                                                    mock_secret):
        mock_in_prod.return_value = True
        mock_secret.return_value = None
        with pytest.raises(Exception) as exception:
            scraper_utils.get_headers()
        assert str(exception.value) == 'No user agent string'

    @patch('recidiviz.utils.environment.in_prod')
    def test_get_headers_local(self, mock_in_prod):
        mock_in_prod.return_value = False
        headers = scraper_utils.get_headers()
        assert headers == {
            'User-Agent': ('For any issues, concerns, or rate constraints,'
                           'e-mail alerts@recidiviz.com')
        }
