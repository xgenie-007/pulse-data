# Recidiviz - a platform for tracking granular recidivism metrics in real time
# Copyright (C) 2019 Recidiviz, Inc.
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

"""Scrapes the kentucky aggregate site and finds pdfs to download."""
from typing import Set
from lxml import html
import requests

STATE_AGGREGATE_URL = ('https://corrections.ky.gov/About/researchandstats/'
                       'Pages/WeeklyJail.aspx')
BASE_URL = 'https://corrections.ky.gov{}'


def get_urls_to_download() -> Set[str]:
    page = requests.get(STATE_AGGREGATE_URL).text
    html_tree = html.fromstring(page)
    links = html_tree.xpath('//a/@href')

    aggregate_report_urls = set()
    for link in links:
        if ('weekly jail' in link.lower() or 'weekly%20jail' in link.lower())\
                and 'pdf' in link.lower():
            url = BASE_URL.format(link)
            aggregate_report_urls.add(url)
    return aggregate_report_urls