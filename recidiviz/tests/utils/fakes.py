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
"""Initialize our database schema for in-memory testing via sqlite3."""

import sqlalchemy

from recidiviz import Session
from recidiviz.persistence.database.schema import Base


def use_in_memory_sqlite_database():
    """
    Creates a new SqlDatabase object used to communicate to a fake in-memory
    sqlite database. This includes:
    1. Creates a new in memory sqlite database engine
    2. Create all tables in the newly created sqlite database
    3. Bind the global SessionMaker to the new fake database engine
    """
    engine = sqlalchemy.create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session.configure(bind=engine)