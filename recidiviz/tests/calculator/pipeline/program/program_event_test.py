# Recidiviz - a data platform for criminal justice reform
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
"""Tests for program/program_event.py."""
from recidiviz.calculator.pipeline.program.program_event import ProgramEvent, \
    ProgramReferralEvent
from recidiviz.common.constants.state.state_assessment import \
    StateAssessmentType
from recidiviz.common.constants.state.state_supervision import \
    StateSupervisionType


def test_program_event():
    state_code = 'CA'
    program_id = 'PROGRAMX'
    year = 2000
    month = 11

    program_event = ProgramEvent(
        state_code, program_id, year, month)

    assert program_event.state_code == state_code
    assert program_event.program_id == program_id
    assert program_event.year == year
    assert program_event.month == month


def test_program_referral_event():
    state_code = 'CA'
    program_id = 'PROGRAMX'
    year = 2000
    month = 11
    supervision_type = StateSupervisionType.PROBATION
    assessment_score = 5
    assessment_type = StateAssessmentType.ORAS
    supervising_officer_external_id = 'OFFICER211'
    supervising_district_external_id = 'DISTRICT 100'

    program_event = ProgramReferralEvent(
        state_code, program_id, year, month, supervision_type,
        assessment_score, assessment_type,
        supervising_officer_external_id, supervising_district_external_id)

    assert program_event.state_code == state_code
    assert program_event.year == year
    assert program_event.month == month
    assert program_event.program_id == program_id
    assert program_event.supervision_type == supervision_type
    assert program_event.assessment_score == assessment_score
    assert program_event.assessment_type == assessment_type
    assert program_event.supervising_officer_external_id == \
        supervising_officer_external_id
    assert program_event.supervising_district_external_id == \
        supervising_district_external_id


def test_eq_different_field():
    state_code = 'CA'
    program_id = 'PROGRAMX'
    year = 2000
    month = 11

    first = ProgramEvent(state_code, program_id, year, month)

    second = ProgramEvent(state_code, 'DIFFERENT', year, month)

    assert first != second


def test_eq_different_types():
    state_code = 'CA'
    program_id = 'PROGRAMX'
    year = 2000
    month = 11
    supervision_type = StateSupervisionType.PROBATION
    assessment_score_bucket = '1-10'
    assessment_type = StateAssessmentType.ORAS
    supervising_officer_external_id = 'OFFICER211'
    supervising_district_external_id = 'DISTRICT 100'

    program_event = ProgramReferralEvent(
        state_code, program_id, year, month, supervision_type,
        assessment_score_bucket, assessment_type,
        supervising_officer_external_id, supervising_district_external_id)

    different = "Everything you do is a banana"

    assert program_event != different
