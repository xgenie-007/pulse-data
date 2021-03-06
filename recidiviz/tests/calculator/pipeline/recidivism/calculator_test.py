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

# pylint: disable=unused-import,wrong-import-order

"""Tests for recidivism/calculator.py."""
import unittest
from datetime import date
from typing import Dict, List

from dateutil.relativedelta import relativedelta
from freezegun import freeze_time
from more_itertools import one

from recidiviz.calculator.pipeline.recidivism import calculator
from recidiviz.calculator.pipeline.recidivism.calculator \
    import FOLLOW_UP_PERIODS
from recidiviz.calculator.pipeline.recidivism.release_event import \
    ReleaseEvent, RecidivismReleaseEvent, NonRecidivismReleaseEvent
from recidiviz.calculator.pipeline.utils.metric_utils import \
    MetricMethodologyType
from recidiviz.calculator.pipeline.recidivism.release_event import \
    ReincarcerationReturnType, ReincarcerationReturnFromSupervisionType
from recidiviz.common.constants.state.state_supervision_violation import \
    StateSupervisionViolationType
from recidiviz.persistence.entity.state.entities import StatePerson, Gender,\
    StatePersonRace, Race, StatePersonEthnicity, Ethnicity
from recidiviz.calculator.pipeline.recidivism.metrics import \
    ReincarcerationRecidivismMetricType as MetricType
from recidiviz.tests.calculator.calculator_test_utils import \
    demographic_metric_combos_count_for_person


_COUNTY_OF_RESIDENCE = 'county'


def test_reincarcerations():
    release_date = date.today()
    original_admission_date = release_date - relativedelta(years=4)
    reincarceration_date = release_date + relativedelta(years=3)
    second_release_date = reincarceration_date + relativedelta(years=1)

    first_event = RecidivismReleaseEvent(
        'CA', original_admission_date, release_date, 'Sing Sing',
        _COUNTY_OF_RESIDENCE, reincarceration_date, 'Sing Sing',
        ReincarcerationReturnType.NEW_ADMISSION)
    second_event = NonRecidivismReleaseEvent(
        'CA', reincarceration_date, second_release_date, 'Sing Sing',
        _COUNTY_OF_RESIDENCE)
    release_events = {2018: [first_event], 2022: [second_event]}

    expected_reincarcerations = {reincarceration_date:
                                 {'release_date': first_event.release_date,
                                  'return_type': first_event.return_type,
                                  'from_supervision_type':
                                  first_event.from_supervision_type,
                                  'source_violation_type': None}}

    reincarcerations = calculator.reincarcerations(release_events)
    assert reincarcerations == expected_reincarcerations


def test_reincarcerations_empty():
    reincarcerations = calculator.reincarcerations({})
    assert reincarcerations == {}


def test_releases_in_window():
    # Too early
    release_2012 = date(2012, 4, 30)
    # Just right
    release_2016 = date(2016, 5, 13)
    release_2020 = date(2020, 11, 20)
    release_2021 = date(2021, 5, 13)
    # Too late
    release_2022 = date(2022, 5, 13)

    reincarceration = {'return_type': ReincarcerationReturnType.NEW_ADMISSION,
                       'from_supervision_type': None}

    all_reincarcerations = {release_2012: reincarceration,
                            release_2016: reincarceration,
                            release_2020: reincarceration,
                            release_2021: reincarceration,
                            release_2022: reincarceration}

    start_date = date(2016, 5, 13)

    reincarcerations = calculator.reincarcerations_in_window(
        start_date, start_date +
        relativedelta(years=6), all_reincarcerations)
    assert len(reincarcerations) == 3


def test_releases_in_window_all_early():
    # Too early
    release_2012 = date(2012, 4, 30)
    release_2016 = date(2016, 5, 13)
    release_2020 = date(2020, 11, 20)
    release_2021 = date(2021, 5, 13)
    release_2022 = date(2022, 5, 13)

    reincarceration = {'return_type': ReincarcerationReturnType.NEW_ADMISSION,
                       'from_supervision_type': None}

    all_reincarcerations = {release_2012: reincarceration,
                            release_2016: reincarceration,
                            release_2020: reincarceration,
                            release_2021: reincarceration,
                            release_2022: reincarceration}

    start_date = date(2026, 5, 13)

    reincarcerations = calculator.reincarcerations_in_window(
        start_date, start_date +
        relativedelta(years=6), all_reincarcerations)

    assert reincarcerations == []


def test_releases_in_window_all_late():
    # Too late
    release_2012 = date(2012, 4, 30)
    release_2016 = date(2016, 5, 13)
    release_2020 = date(2020, 11, 20)
    release_2021 = date(2021, 5, 13)
    release_2022 = date(2022, 5, 13)

    reincarceration = {'return_type': ReincarcerationReturnType.NEW_ADMISSION,
                       'from_supervision_type': None}

    all_reincarcerations = {release_2012: reincarceration,
                            release_2016: reincarceration,
                            release_2020: reincarceration,
                            release_2021: reincarceration,
                            release_2022: reincarceration}

    start_date = date(2006, 5, 13)

    reincarcerations = calculator.reincarcerations_in_window(
        start_date, start_date +
        relativedelta(years=5), all_reincarcerations)

    assert reincarcerations == []


def test_releases_in_window_with_revocation_returns():
    # Too early
    release_2012 = date(2012, 4, 30)
    # Just right
    release_2016 = date(2016, 5, 13)
    release_2020 = date(2020, 11, 20)
    release_2021 = date(2021, 5, 13)
    # Too late
    release_2022 = date(2022, 5, 13)

    revocation_reincarceration = {
        'return_type':
            ReincarcerationReturnType.REVOCATION,
        'from_supervision_type':
            ReincarcerationReturnFromSupervisionType.PAROLE}

    new_admission_reincarceration = {
        'return_type': ReincarcerationReturnType.NEW_ADMISSION,
        'from_supervision_type': None}

    all_reincarcerations = {release_2012: new_admission_reincarceration,
                            release_2016: revocation_reincarceration,
                            release_2020: revocation_reincarceration,
                            release_2021: new_admission_reincarceration,
                            release_2022: new_admission_reincarceration}

    start_date = date(2016, 5, 13)

    reincarcerations = calculator.reincarcerations_in_window(
        start_date, start_date +
        relativedelta(years=6), all_reincarcerations)
    assert len(reincarcerations) == 3

    assert reincarcerations[0].get('return_type') == \
        ReincarcerationReturnType.REVOCATION
    assert reincarcerations[0].get('from_supervision_type') == \
        ReincarcerationReturnFromSupervisionType.PAROLE
    assert reincarcerations[1].get('return_type') == \
        ReincarcerationReturnType.REVOCATION
    assert reincarcerations[1].get('from_supervision_type') == \
        ReincarcerationReturnFromSupervisionType.PAROLE
    assert reincarcerations[2].get('return_type') == \
        ReincarcerationReturnType.NEW_ADMISSION
    assert reincarcerations[2].get('from_supervision_type') is None


def test_earliest_recidivated_follow_up_period_later_month_in_year():
    release_date = date(2012, 4, 20)
    reincarceration_date = date(2016, 5, 13)

    earliest_period = calculator.earliest_recidivated_follow_up_period(
        release_date, reincarceration_date)
    assert earliest_period == 5


def test_earliest_recidivated_follow_up_period_same_month_in_year_later_day():
    release_date = date(2012, 4, 20)
    reincarceration_date = date(2016, 4, 21)

    earliest_period = calculator.earliest_recidivated_follow_up_period(
        release_date, reincarceration_date)
    assert earliest_period == 5


def test_earliest_recidivated_follow_up_period_same_month_in_year_earlier_day():
    release_date = date(2012, 4, 20)
    reincarceration_date = date(2016, 4, 19)

    earliest_period = calculator.earliest_recidivated_follow_up_period(
        release_date, reincarceration_date)
    assert earliest_period == 4


def test_earliest_recidivated_follow_up_period_same_month_in_year_same_day():
    release_date = date(2012, 4, 20)
    reincarceration_date = date(2016, 4, 20)

    earliest_period = calculator.earliest_recidivated_follow_up_period(
        release_date, reincarceration_date)
    assert earliest_period == 4


def test_earliest_recidivated_follow_up_period_earlier_month_in_year():
    release_date = date(2012, 4, 20)
    reincarceration_date = date(2016, 3, 31)

    earliest_period = calculator.earliest_recidivated_follow_up_period(
        release_date, reincarceration_date)
    assert earliest_period == 4


def test_earliest_recidivated_follow_up_period_same_year():
    release_date = date(2012, 4, 20)
    reincarceration_date = date(2012, 5, 13)

    earliest_period = calculator.earliest_recidivated_follow_up_period(
        release_date, reincarceration_date)
    assert earliest_period == 1


def test_earliest_recidivated_follow_up_period_no_reincarceration():
    release_date = date(2012, 4, 30)

    earliest_period = calculator.earliest_recidivated_follow_up_period(
        release_date, None)
    assert earliest_period is None


def test_relevant_follow_up_periods():
    today = date(2018, 1, 26)

    assert calculator.relevant_follow_up_periods(
        date(2015, 1, 5), today, calculator.FOLLOW_UP_PERIODS) == [1, 2, 3, 4]
    assert calculator.relevant_follow_up_periods(
        date(2015, 1, 26), today, calculator.FOLLOW_UP_PERIODS) == [1, 2, 3, 4]
    assert calculator.relevant_follow_up_periods(
        date(2015, 1, 27), today, calculator.FOLLOW_UP_PERIODS) == [1, 2, 3]
    assert calculator.relevant_follow_up_periods(
        date(2016, 1, 5), today, calculator.FOLLOW_UP_PERIODS) == [1, 2, 3]
    assert calculator.relevant_follow_up_periods(
        date(2017, 4, 10), today, calculator.FOLLOW_UP_PERIODS) == [1]
    assert calculator.relevant_follow_up_periods(
        date(2018, 1, 5), today, calculator.FOLLOW_UP_PERIODS) == [1]
    assert calculator.relevant_follow_up_periods(
        date(2018, 2, 5), today, calculator.FOLLOW_UP_PERIODS) == []


def test_stay_length_from_event_earlier_month_and_date():
    original_admission_date = date(2013, 6, 17)
    release_date = date(2014, 4, 15)
    event = ReleaseEvent('CA', original_admission_date, release_date,
                         'Sing Sing')

    assert calculator.stay_length_from_event(event) == 9


def test_stay_length_from_event_same_month_earlier_date():
    original_admission_date = date(2013, 6, 17)
    release_date = date(2014, 6, 16)
    event = ReleaseEvent('NH', original_admission_date, release_date,
                         'Sing Sing')

    assert calculator.stay_length_from_event(event) == 11


def test_stay_length_from_event_same_month_same_date():
    original_admission_date = date(2013, 6, 17)
    release_date = date(2014, 6, 17)
    event = ReleaseEvent('TX', original_admission_date, release_date,
                         'Sing Sing')

    assert calculator.stay_length_from_event(event) == 12


def test_stay_length_from_event_same_month_later_date():
    original_admission_date = date(2013, 6, 17)
    release_date = date(2014, 6, 18)
    event = ReleaseEvent('UT', original_admission_date, release_date,
                         'Sing Sing')

    assert calculator.stay_length_from_event(event) == 12


def test_stay_length_from_event_later_month():
    original_admission_date = date(2013, 6, 17)
    release_date = date(2014, 8, 11)
    event = ReleaseEvent('HI', original_admission_date, release_date,
                         'Sing Sing')

    assert calculator.stay_length_from_event(event) == 13


def test_stay_length_from_event_original_admission_date_unknown():
    release_date = date(2014, 7, 11)
    event = ReleaseEvent('MT', None, release_date, 'Sing Sing')
    assert calculator.stay_length_from_event(event) is None


def test_stay_length_from_event_release_date_unknown():
    original_admission_date = date(2014, 7, 11)
    event = ReleaseEvent('UT', original_admission_date, None, 'Sing Sing')
    assert calculator.stay_length_from_event(event) is None


def test_stay_length_from_event_both_dates_unknown():
    event = ReleaseEvent('NH', None, None, 'Sing Sing')
    assert calculator.stay_length_from_event(event) is None


def test_stay_length_bucket():
    assert calculator.stay_length_bucket(None) is None
    assert calculator.stay_length_bucket(11) == '<12'
    assert calculator.stay_length_bucket(12) == '12-24'
    assert calculator.stay_length_bucket(20) == '12-24'
    assert calculator.stay_length_bucket(24) == '24-36'
    assert calculator.stay_length_bucket(30) == '24-36'
    assert calculator.stay_length_bucket(36) == '36-48'
    assert calculator.stay_length_bucket(40) == '36-48'
    assert calculator.stay_length_bucket(48) == '48-60'
    assert calculator.stay_length_bucket(50) == '48-60'
    assert calculator.stay_length_bucket(60) == '60-72'
    assert calculator.stay_length_bucket(70) == '60-72'
    assert calculator.stay_length_bucket(72) == '72-84'
    assert calculator.stay_length_bucket(80) == '72-84'
    assert calculator.stay_length_bucket(84) == '84-96'
    assert calculator.stay_length_bucket(96) == '96-108'
    assert calculator.stay_length_bucket(100) == '96-108'
    assert calculator.stay_length_bucket(108) == '108-120'
    assert calculator.stay_length_bucket(110) == '108-120'
    assert calculator.stay_length_bucket(120) == '120<'
    assert calculator.stay_length_bucket(130) == '120<'


def test_augmented_combo_list_methodologies():
    base_combo = {'age': '<25', 'race': 'black', 'gender': 'female'}

    event = ReleaseEvent(
        state_code='CA',
        original_admission_date=date.today(),
        release_date=date.today(),
        release_facility=None,
        county_of_residence=None
    )

    person_combo_list = calculator.augmented_combo_list(base_combo, event, MetricMethodologyType.PERSON, 8)

    for combo in person_combo_list:
        assert combo['methodology'] == MetricMethodologyType.PERSON
        assert combo['follow_up_period'] == 8

    event_combo_list = calculator.augmented_combo_list(base_combo, event, MetricMethodologyType.EVENT, 8)

    for combo in event_combo_list:
        assert combo['methodology'] == MetricMethodologyType.EVENT
        assert combo['follow_up_period'] == 8


def test_augmented_combo_list_return_info():
    """Tests that all return_type and from_supervision_type values are being covered."""
    base_combo = {'age': '<25', 'race': 'black', 'gender': 'female'}

    event = ReleaseEvent(
        state_code='CA',
        original_admission_date=date.today(),
        release_date=date.today(),
        release_facility=None,
        county_of_residence=None
    )

    combo_list = calculator.augmented_combo_list(
        base_combo, event, MetricMethodologyType.PERSON, 8)

    parameter_list = {}

    for return_type in ReincarcerationReturnType:
        parameter_list[return_type] = False

    for from_supervision_type in ReincarcerationReturnFromSupervisionType:
        parameter_list[from_supervision_type] = False

    for combo in combo_list:
        assert combo['methodology'] == MetricMethodologyType.PERSON
        assert combo['follow_up_period'] == 8

        return_type = combo.get('return_type')

        if return_type:
            parameter_list[return_type] = True

        from_supervision_type = combo.get('from_supervision_type')

        if from_supervision_type:
            parameter_list[from_supervision_type] = True

    for value in parameter_list.values():
        assert value


def test_augmented_combo_list_person_level():
    """Tests that only one dictionary with the relevant return_type and from_supervision_type values are being
    returned."""
    base_combo = {'age': '<25', 'race': 'black', 'gender': 'female', 'person_id': 12345}

    event = RecidivismReleaseEvent(
        state_code='CA',
        original_admission_date=date.today(),
        release_date=date.today(),
        release_facility=None,
        county_of_residence=None,
        return_type=ReincarcerationReturnType.REVOCATION,
        from_supervision_type=ReincarcerationReturnFromSupervisionType.PAROLE,
        source_violation_type=StateSupervisionViolationType.MISDEMEANOR
    )

    combo_list = calculator.augmented_combo_list(base_combo, event, MetricMethodologyType.PERSON, None)

    parameter_list = {
        'state_code': 'CA',
        'methodology': MetricMethodologyType.PERSON,
        'return_type': ReincarcerationReturnType.REVOCATION,
        'from_supervision_type': ReincarcerationReturnFromSupervisionType.PAROLE,
        'source_violation_type': StateSupervisionViolationType.MISDEMEANOR
    }

    assert len(combo_list) == 1

    for combo in combo_list:
        for parameter, value in parameter_list.items():
            assert value == combo.get(parameter)


def test_recidivism_value_for_metric():
    combo = {'age': '<25', 'race': 'black', 'gender': 'female'}

    value = calculator.recidivism_value_for_metric(combo, None, None, None)

    assert value == 1


def test_recidivism_value_for_metric_new_admission():
    combo = {'age': '<25', 'race': 'black', 'gender': 'female',
             'return_type': ReincarcerationReturnType.NEW_ADMISSION}

    value = calculator.recidivism_value_for_metric(
        combo, ReincarcerationReturnType.NEW_ADMISSION, None, None)

    assert value == 1


def test_recidivism_value_for_metric_not_new_admission():
    combo = {'age': '<25', 'race': 'black', 'gender': 'female',
             'return_type': ReincarcerationReturnType.NEW_ADMISSION}

    value = calculator.recidivism_value_for_metric(
        combo, ReincarcerationReturnType.REVOCATION, None, None)

    assert value == 0


def test_recidivism_value_for_metric_parole_revocation():
    combo = {'age': '<25', 'race': 'black', 'gender': 'female',
             'return_type': ReincarcerationReturnType.REVOCATION,
             'from_supervision_type':
                 ReincarcerationReturnFromSupervisionType.PAROLE}

    value = calculator.recidivism_value_for_metric(
        combo, ReincarcerationReturnType.REVOCATION,
        ReincarcerationReturnFromSupervisionType.PAROLE, None)

    assert value == 1


def test_recidivism_value_for_metric_probation_revocation():
    combo = {'age': '<25', 'race': 'black', 'gender': 'female',
             'return_type': ReincarcerationReturnType.REVOCATION,
             'from_supervision_type':
                 ReincarcerationReturnFromSupervisionType.PROBATION}

    value = calculator.recidivism_value_for_metric(
        combo, ReincarcerationReturnType.REVOCATION,
        ReincarcerationReturnFromSupervisionType.PROBATION, None)

    assert value == 1


def test_recidivism_value_for_metric_parole_revocation_source_violation():
    combo = {'age': '<25', 'race': 'black', 'gender': 'female',
             'return_type': ReincarcerationReturnType.REVOCATION,
             'from_supervision_type':
                 ReincarcerationReturnFromSupervisionType.PAROLE,
             'source_violation_type': StateSupervisionViolationType.TECHNICAL}

    value = calculator.recidivism_value_for_metric(
        combo, ReincarcerationReturnType.REVOCATION,
        ReincarcerationReturnFromSupervisionType.PAROLE,
        StateSupervisionViolationType.TECHNICAL)

    assert value == 1


def test_recidivism_value_for_metric_probation_revocation_source_violation():
    combo = {'age': '<25', 'race': 'black', 'gender': 'female',
             'return_type': ReincarcerationReturnType.REVOCATION,
             'from_supervision_type':
                 ReincarcerationReturnFromSupervisionType.PROBATION,
             'source_violation_type': StateSupervisionViolationType.FELONY}

    value = calculator.recidivism_value_for_metric(
        combo, ReincarcerationReturnType.REVOCATION,
        ReincarcerationReturnFromSupervisionType.PROBATION,
        StateSupervisionViolationType.FELONY)

    assert value == 1


def test_recidivism_value_for_metric_not_revocation():
    combo = {'age': '<25', 'race': 'black', 'gender': 'female',
             'return_type': ReincarcerationReturnType.REVOCATION,
             'from_supervision_type':
                 ReincarcerationReturnFromSupervisionType.PROBATION}

    value = calculator.recidivism_value_for_metric(
        combo, ReincarcerationReturnType.NEW_ADMISSION,
        ReincarcerationReturnFromSupervisionType.PROBATION, None)

    assert value == 0


def test_recidivism_value_for_metric_not_supervision_type():
    combo = {'age': '<25', 'race': 'black', 'gender': 'female',
             'return_type': ReincarcerationReturnType.REVOCATION,
             'from_supervision_type':
                 ReincarcerationReturnFromSupervisionType.PROBATION}

    value = calculator.recidivism_value_for_metric(
        combo, ReincarcerationReturnType.REVOCATION,
        ReincarcerationReturnFromSupervisionType.PAROLE, None)

    assert value == 0


def test_recidivism_value_for_metric_not_source_violation_type():
    combo = {'age': '<25', 'race': 'black', 'gender': 'female',
             'return_type': ReincarcerationReturnType.REVOCATION,
             'from_supervision_type':
                 ReincarcerationReturnFromSupervisionType.PROBATION,
             'source_violation_type': StateSupervisionViolationType.FELONY}

    value = calculator.recidivism_value_for_metric(
        combo, ReincarcerationReturnType.REVOCATION,
        ReincarcerationReturnFromSupervisionType.PAROLE,
        StateSupervisionViolationType.TECHNICAL)

    assert value == 0


ALL_INCLUSIONS_DICT = {
        'age_bucket': True,
        'gender': True,
        'race': True,
        'ethnicity': True,
        'release_facility': True,
        'stay_length_bucket': True
    }


class TestMapRecidivismCombinations(unittest.TestCase):
    """Tests the map_recidivism_combinations function."""

    RECIDIVISM_METHODOLOGIES = len(MetricMethodologyType)

    RETURN_TYPE_COMBOS_INCLUDING_NEW_ADMISSION = (
        0 +  # NEW_ADMISSSION - sub-explosions
        1    # NEW_ADMISSSION - all
    )

    RETURN_TYPE_COMBOS_INCLUDING_REVOCATION = (
        (
            (
                len(ReincarcerationReturnFromSupervisionType) *
                len(StateSupervisionViolationType)
            ) +  # VIOLATION TYPE and RETURN FROM TYPE crossproduct
            len(ReincarcerationReturnFromSupervisionType) +  # VIOLATION TYPE - all
            len(StateSupervisionViolationType)  # RETURN FROM TYPE - all
        ) +  # REVOCATION - sub-explosions
        1  # REVOCATION - all
    )

    RETURN_TYPE_METRIC_COMBOS = (
        RETURN_TYPE_COMBOS_INCLUDING_NEW_ADMISSION +
        RETURN_TYPE_COMBOS_INCLUDING_REVOCATION +
        1  # RETURNS - all
    )

    RECIDIVISM_COUNT_WINDOWS = 2  # Month, Year
    LIBERTY_TIME_WINDOWS = 2  # Month, Year

    def relevant_combos_count_for_recidivism_release_event(
            self, release_event: RecidivismReleaseEvent):
        """For the given release_event, determines the number of metric key
        combinations that match the details of the given event."""
        current_possible_metrics = 1  # All Returns metric

        if release_event.return_type is None and \
                release_event.from_supervision_type is None \
                and release_event.source_violation_type is None:
            return current_possible_metrics

        self.assertIsNotNone(release_event.return_type)

        current_possible_metrics += 1  # Add metric that has just return type
        if release_event.from_supervision_type is None \
                and release_event.source_violation_type is None:
            return current_possible_metrics

        # Only REVOCATION can have a from_supervision_type or
        # source_violation_type.
        self.assertEqual(release_event.return_type,
                         ReincarcerationReturnType.REVOCATION)

        if release_event.from_supervision_type is None:
            self.assertIsNotNone(release_event.source_violation_type)
            # Add metric with just source violation type
            return current_possible_metrics + 1

        if release_event.source_violation_type is None:
            self.assertIsNotNone(release_event.from_supervision_type)
            # Add metric with just from supervision type
            return current_possible_metrics + 1

        # Metrics include cross-product of including violation, from type,
        # and both.
        return current_possible_metrics + 3

    def expected_metric_combos_count(self, person: StatePerson, release_events_by_cohort: Dict[int, List[ReleaseEvent]],
                                     inclusions: Dict[str, bool]) -> int:
        """Calculates the expected number of characteristic combinations given the person, the release events, and the
        dimensions that should be included in the explosion of feature combinations."""
        demographic_metric_combos = expected_metric_count_for_person_recidivism(person, inclusions)

        all_release_events = [
            re
            for re_list in release_events_by_cohort.values()
            for re in re_list
        ]

        recidivism_release_events = [
            re for re in all_release_events if
            isinstance(re, RecidivismReleaseEvent)
        ]

        num_events_with_multiple_releases_in_year = 0
        for _, events in release_events_by_cohort.items():
            if len(events) > 1:
                num_events_with_multiple_releases_in_year += (len(events) - 1)

        recidivism_rate_metrics = (self.RETURN_TYPE_METRIC_COMBOS * len(FOLLOW_UP_PERIODS) * len(all_release_events))

        recidivism_count_metrics = (self.RETURN_TYPE_METRIC_COMBOS * len(recidivism_release_events))

        release_event_relevant_combo_counts = sum(self.relevant_combos_count_for_recidivism_release_event(re)
                                                  for re in recidivism_release_events)
        at_liberty_metrics = release_event_relevant_combo_counts * self.LIBERTY_TIME_WINDOWS

        expected_combos_count = \
            demographic_metric_combos * self.RECIDIVISM_METHODOLOGIES * (
                recidivism_rate_metrics +
                recidivism_count_metrics +
                at_liberty_metrics
            )

        # Duplicated person-based combos for duplicate releases in the same year
        expected_combos_count -= (
            self.RETURN_TYPE_METRIC_COMBOS * len(FOLLOW_UP_PERIODS) * num_events_with_multiple_releases_in_year *
            demographic_metric_combos
        )

        # Person-level count metrics
        expected_combos_count += (len(recidivism_release_events) * self.RECIDIVISM_METHODOLOGIES)

        # Person-level liberty metrics
        expected_combos_count += (len(recidivism_release_events) *
                                  self.LIBERTY_TIME_WINDOWS *
                                  self.RECIDIVISM_METHODOLOGIES)

        return expected_combos_count

    @freeze_time('2100-01-01')
    def test_map_recidivism_combinations(self):
        """Tests the map_recidivism_combinations function where there is
        recidivism."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            2008: [RecidivismReleaseEvent(
                'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(2014, 5, 12), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)]
        }

        days_at_liberty = (date(2014, 5, 12) - date(2008, 9, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        expected_combos_count = self.expected_metric_combos_count(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combos_count, len(recidivism_combinations))

        for combination, value in recidivism_combinations:
            if combination.get('metric_type') == MetricType.RATE and \
                    combination.get('follow_up_period') <= 5 or \
                    combination.get('return_type') == \
                    ReincarcerationReturnType.REVOCATION:
                assert value == 0
            elif combination.get('metric_type') == MetricType.LIBERTY:
                assert value == days_at_liberty
            else:
                assert value == 1

    def test_map_recidivism_combinations_multiple_in_period(self):
        """Tests the map_recidivism_combinations function where there are multiple instances of recidivism within a
        follow-up period."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.BLACK)
        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            1908: [RecidivismReleaseEvent(
                'CA', date(1905, 7, 19), date(1908, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(1910, 8, 12), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)],
            1912: [RecidivismReleaseEvent(
                'CA', date(1910, 8, 12), date(1912, 8, 19), 'Upstate',
                _COUNTY_OF_RESIDENCE,
                date(1914, 7, 12), 'Sing Sing',
                ReincarcerationReturnType.NEW_ADMISSION)]
        }

        days_at_liberty_1 = (date(1910, 8, 12) - date(1908, 9, 19)).days
        days_at_liberty_2 = (date(1914, 7, 12) - date(1912, 8, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        # For the first event:
        #   For the first 5 periods:
        #       128 combinations of characteristics
        #       * 46 combinations of methodology/return type/supervision type
        #       * 5 periods
        #       * + 64 * 1 count window * 46 combos of methodology etc.
        #       * + 64 * 2 liberty windows * 4 relevant combos
        #           = 18176 metrics
        #   For the second 5 periods, there is an additional event-based count:
        #       64 combinations of characteristics
        #       * (46 combinations of methodology/return type/supervision type
        #           + 23 more instances) * 5 periods = 44160 metrics
        #
        #   Person-level metrics: (1 count window + 2 liberty windows) * 2 methodologies = 6
        #
        # For the second event:
        #   64 combinations * 46 combos * 10 periods +
        #   64 combos * 1 count window * 46 combos of methodology etc. +
        #   64 * 2 liberty windows * 4 combos of methodology etc.
        #   = 32896 metrics
        #
        # Person-level metrics: (1 count window + 2 liberty windows) * 2 methodologies = 6

        # Multiplied by 2 to include the county of residence field
        expected_count = (18176 + 22080 + 32896) * 2

        expected_count += (6 + 6)

        # Multiplied by 2 to include the county of residence field
        assert len(recidivism_combinations) == expected_count

        for combination, value in recidivism_combinations:
            if combination.get('metric_type') == MetricType.RATE and \
                    combination.get('follow_up_period') < 2 or \
                    combination.get('return_type') == \
                    ReincarcerationReturnType.REVOCATION:
                self.assertEqual(0, value)
            elif combination.get('metric_type') == MetricType.LIBERTY:
                if combination.get('start_date') < date(1909, 1, 1):
                    self.assertEqual(days_at_liberty_1, value)
                else:
                    self.assertEqual(days_at_liberty_2, value)
            else:
                self.assertEqual(1, value)

    def test_map_recidivism_combinations_multiple_releases_in_year(self):
        """Tests the map_recidivism_combinations function where there are multiple releases in the same year."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.BLACK)
        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            1908: [
                RecidivismReleaseEvent(
                    'CA', date(1905, 7, 19), date(1908, 1, 19), 'Hudson',
                    _COUNTY_OF_RESIDENCE,
                    date(1908, 5, 12), 'Upstate',
                    ReincarcerationReturnType.NEW_ADMISSION),
                NonRecidivismReleaseEvent(
                    'CA', date(1908, 5, 12), date(1908, 8, 19), 'Upstate',
                    _COUNTY_OF_RESIDENCE)
            ],
        }

        days_at_liberty_1 = (date(1908, 5, 12) - date(1908, 1, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        expected_count = self.expected_metric_combos_count(person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_count, len(recidivism_combinations))

        for combination, value in recidivism_combinations:
            if combination.get('return_type') == ReincarcerationReturnType.REVOCATION:
                self.assertEqual(0, value)
            elif combination.get('metric_type') == MetricType.LIBERTY:
                if combination.get('start_date') < date(1909, 1, 1):
                    self.assertEqual(days_at_liberty_1, value)
            elif combination.get('metric_type') != MetricType.RATE \
                    or combination.get('methodology') == MetricMethodologyType.PERSON:
                if value == 0:
                    print(combination)
                self.assertEqual(1, value)

    def test_map_recidivism_combinations_no_recidivism(self):
        """Tests the map_recidivism_combinations function where there is no
        recidivism."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.BLACK)
        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            2008: [NonRecidivismReleaseEvent('CA', date(2005, 7, 19),
                                             date(2008, 9, 19), 'Hudson',
                                             _COUNTY_OF_RESIDENCE)]
        }

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        expected_combos_count = self.expected_metric_combos_count(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combos_count, len(recidivism_combinations))
        self.assertTrue(all(value == 0 for _combination, value
                            in recidivism_combinations))

    def test_map_recidivism_combinations_recidivated_after_last_period(self):
        """Tests the map_recidivism_combinations function where there is
        recidivism but it occurred after the last follow-up period we track."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.BLACK)
        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            1998: [RecidivismReleaseEvent(
                'CA', date(1995, 7, 19), date(1998, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(2008, 10, 12), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)]
        }

        days_at_liberty = (date(2008, 10, 12) - date(1998, 9, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        expected_combos_count = self.expected_metric_combos_count(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combos_count, len(recidivism_combinations))

        assert all(value == 0 for _combination, value
                   in recidivism_combinations if
                   _combination['metric_type'] == MetricType.RATE)
        assert all(value == days_at_liberty for _combination, value
                   in recidivism_combinations if
                   _combination['metric_type'] == MetricType.LIBERTY)
        assert all(value == 1 for _combination, value
                   in recidivism_combinations if
                   _combination['metric_type'] == MetricType.COUNT and
                   _combination.get('return_type') !=
                   ReincarcerationReturnType.REVOCATION)

    def test_map_recidivism_combinations_multiple_races(self):
        """Tests the map_recidivism_combinations function where there is
        recidivism, and the person has more than one race."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race_white = StatePersonRace.new_with_defaults(state_code='CA',
                                                       race=Race.WHITE)

        race_black = StatePersonRace.new_with_defaults(state_code='MT',
                                                       race=Race.BLACK)

        person.races = [race_white, race_black]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            2008: [RecidivismReleaseEvent(
                'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(2014, 5, 12), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)]
        }

        days_at_liberty = (date(2014, 5, 12) - date(2008, 9, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        expected_combos_count = self.expected_metric_combos_count(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combos_count, len(recidivism_combinations))

        for combination, value in recidivism_combinations:
            if combination.get('metric_type') == MetricType.RATE and \
                    combination.get('follow_up_period') <= 5 or \
                    combination.get('return_type') == \
                    ReincarcerationReturnType.REVOCATION:
                assert value == 0
            elif combination.get('metric_type') == MetricType.LIBERTY:
                assert value == days_at_liberty
            else:
                assert value == 1

    def test_map_recidivism_combinations_multiple_ethnicities(self):
        """Tests the map_recidivism_combinations function where there is
        recidivism, and the person has more than one ethnicity."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.BLACK)
        person.races = [race]

        ethnicity_hispanic = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.HISPANIC)

        ethnicity_not_hispanic = StatePersonEthnicity.new_with_defaults(
            state_code='MT',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity_hispanic, ethnicity_not_hispanic]

        release_events_by_cohort = {
            2008: [RecidivismReleaseEvent(
                'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(2014, 5, 12), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)]
        }

        days_at_liberty = (date(2014, 5, 12) - date(2008, 9, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        expected_combos_count = self.expected_metric_combos_count(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combos_count, len(recidivism_combinations))

        for combination, value in recidivism_combinations:
            if combination.get('metric_type') == MetricType.RATE and \
                    combination.get('follow_up_period') <= 5 or \
                    combination.get('return_type') == \
                    ReincarcerationReturnType.REVOCATION:
                assert value == 0
            elif combination.get('metric_type') == MetricType.LIBERTY:
                assert value == days_at_liberty
            else:
                assert value == 1

    def test_map_recidivism_combinations_multiple_races_ethnicities(self):
        """Tests the map_recidivism_combinations function where there is
        recidivism, and the person has multiple races and multiple
        ethnicities."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race_white = StatePersonRace.new_with_defaults(state_code='CA',
                                                       race=Race.WHITE)

        race_black = StatePersonRace.new_with_defaults(state_code='MT',
                                                       race=Race.BLACK)

        person.races = [race_white, race_black]

        ethnicity_hispanic = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.HISPANIC)

        ethnicity_not_hispanic = StatePersonEthnicity.new_with_defaults(
            state_code='MT',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity_hispanic, ethnicity_not_hispanic]

        release_events_by_cohort = {
            2008: [RecidivismReleaseEvent(
                'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(2014, 5, 12), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)]
        }

        days_at_liberty = (date(2014, 5, 12) - date(2008, 9, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        expected_combos_count = self.expected_metric_combos_count(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combos_count, len(recidivism_combinations))

        for combination, value in recidivism_combinations:
            if combination.get('metric_type') == MetricType.RATE and \
                    combination.get('follow_up_period') <= 5 or \
                    combination.get('return_type') == \
                    ReincarcerationReturnType.REVOCATION:
                assert value == 0
            elif combination.get('metric_type') == MetricType.LIBERTY:
                assert value == days_at_liberty
            else:
                assert value == 1

    def test_map_recidivism_combinations_revocation_parole(self):
        """Tests the map_recidivism_combinations function where there is
        recidivism, and they returned from a revocation of parole."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            2008: [RecidivismReleaseEvent(
                'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(2014, 5, 12), 'Upstate',
                ReincarcerationReturnType.REVOCATION,
                from_supervision_type=
                ReincarcerationReturnFromSupervisionType.PAROLE)]
        }

        days_at_liberty = (date(2014, 5, 12) - date(2008, 9, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)
        expected_combos_count = self.expected_metric_combos_count(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combos_count, len(recidivism_combinations))

        for combination, value in recidivism_combinations:
            if combination.get('metric_type') == MetricType.RATE and \
                    combination.get('follow_up_period') <= 5 or \
                    combination.get('return_type') == \
                    ReincarcerationReturnType.NEW_ADMISSION or \
                    combination.get('from_supervision_type') == \
                    ReincarcerationReturnFromSupervisionType.PROBATION or \
                    combination.get('source_violation_type') is not None:
                assert value == 0
            elif combination.get('metric_type') == MetricType.LIBERTY:
                assert value == days_at_liberty
            else:
                assert value == 1

    def test_map_recidivism_combinations_revocation_probation(self):
        """Tests the map_recidivism_combinations function where there is
        recidivism, and they returned from a revocation of parole."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            2008: [RecidivismReleaseEvent(
                'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(2014, 5, 12), 'Upstate',
                ReincarcerationReturnType.REVOCATION,
                from_supervision_type=
                ReincarcerationReturnFromSupervisionType.PROBATION)]
        }

        days_at_liberty = (date(2014, 5, 12) - date(2008, 9, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        expected_combos_count = self.expected_metric_combos_count(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combos_count, len(recidivism_combinations))

        for combination, value in recidivism_combinations:
            if combination.get('metric_type') == MetricType.RATE and \
                    combination.get('follow_up_period') <= 5 or \
                    combination.get('return_type') == \
                    ReincarcerationReturnType.NEW_ADMISSION or \
                    combination.get('from_supervision_type') == \
                    ReincarcerationReturnFromSupervisionType.PAROLE or \
                    combination.get('source_violation_type') is not None:
                assert value == 0
            elif combination.get('metric_type') == MetricType.LIBERTY:
                assert value == days_at_liberty
            else:
                assert value == 1

    def test_map_recidivism_combinations_technical_revocation_parole(self):
        """Tests the map_recidivism_combinations function where there is
        recidivism, and they returned from a technical violation that resulted
        in the revocation of parole."""
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            2008: [RecidivismReleaseEvent(
                'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(2014, 5, 12), 'Upstate',
                ReincarcerationReturnType.REVOCATION,
                from_supervision_type=
                ReincarcerationReturnFromSupervisionType.PAROLE,
                source_violation_type=StateSupervisionViolationType.TECHNICAL)]
        }

        days_at_liberty = (date(2014, 5, 12) - date(2008, 9, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        expected_combos_count = self.expected_metric_combos_count(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combos_count, len(recidivism_combinations))

        for combination, value in recidivism_combinations:
            if combination.get('metric_type') == MetricType.RATE and \
                    combination.get('follow_up_period') <= 5:
                assert value == 0
            elif combination.get('metric_type') == MetricType.LIBERTY:
                assert value == days_at_liberty
            elif combination.get('return_type') == \
                    ReincarcerationReturnType.NEW_ADMISSION or \
                    combination.get('from_supervision_type') == \
                    ReincarcerationReturnFromSupervisionType.PROBATION:
                assert value == 0
            elif combination.get('from_supervision_type') is None or \
                    combination.get('from_supervision_type') == \
                    ReincarcerationReturnFromSupervisionType.PAROLE:
                if combination.get('source_violation_type') not in \
                        [None, StateSupervisionViolationType.TECHNICAL]:
                    assert value == 0
                else:
                    assert value == 1
            else:
                assert value == 1

    def test_map_recidivism_combinations_count_metric_buckets(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            2008: [RecidivismReleaseEvent(
                'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(2014, 5, 12), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)]
        }

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        expected_combos_count = self.expected_metric_combos_count(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        self.assertEqual(expected_combos_count, len(recidivism_combinations))

        for combo, value in recidivism_combinations:
            if combo['metric_type'] == MetricType.COUNT:
                assert combo['year'] == 2014
                assert combo['month'] == 5

                if combo.get('return_type') != \
                        ReincarcerationReturnType.REVOCATION:
                    assert value == 1
                else:
                    assert value == 0

    def test_map_recidivism_combinations_count_metric_no_recidivism(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            2008: [NonRecidivismReleaseEvent('CA', date(2005, 7, 19),
                                             date(2008, 9, 19), 'Hudson')]
        }

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        assert all(value == 0 for _combination, value
                   in recidivism_combinations)
        assert all(_combination['metric_type'] ==
                   MetricType.RATE for _combination, value
                   in recidivism_combinations)

    @freeze_time('1914-09-30')
    def test_map_recidivism_combinations_count_relevant_periods(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1884, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            1908: [RecidivismReleaseEvent(
                'TX', date(1905, 7, 19), date(1908, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(1914, 3, 12), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)],
            1914: [RecidivismReleaseEvent(
                'TX', date(1914, 3, 12), date(1914, 7, 3), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(1914, 9, 1), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)]
        }

        days_at_liberty_1 = (date(1914, 3, 12) - date(1908, 9, 19)).days
        days_at_liberty_2 = (date(1914, 9, 1) - date(1914, 7, 3)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        # For the first event:
        #   For the first 5 periods:
        #       64  combinations of characteristics
        #       * 46 combinations of methodology/return type/supervision type
        #       * 5 periods = 14720 metrics
        #   For the next 2 periods:
        #       64 combinations of characteristics
        #       * (46 combinations of methodology/return type/supervision type
        #           + 23 more instances) * 2 periods = 8832 metrics
        #
        #   Count + liberty windows: 64 * 1 count windows * 46 combos +
        #       64 * 2 liberty windows * 4 combos = 3456
        #   Person-level metrics: (1 count window + 2 liberty windows) * 2 methodologies = 6
        #
        # For the second event:
        #   64 combinations * 46 combos * 1 period +
        #   64 * 1 month window * 46 event and person-based-combos  +
        #   64 * 2 liberty windows * 2 event-based combos +
        #   64 * 1 liberty window (month) * 2 person-based combos = 6272
        #
        # Person-level metrics: (1 count window * 2 methodologies + 2 liberty event-based windows +
        # 1 person-based month window) = 5
        #
        # For the relevant metric_period_months count metrics:
        # (6 event-based + 4 person-based) * 64 combinations * 23 combos = 14720
        #
        # Relevant metric_period_months person-level count metrics:
        # (6 event-based + 4 person-based) = 10

        # Multiplied by 2 to include the county of residence field
        expected_count = (14720 + 8832 + 3456 + 6272 + 14720) * 2

        # Adding person-level metric counts
        expected_count += (6 + 5 + 10)

        assert len(recidivism_combinations) == expected_count

        for combo, value in recidivism_combinations:
            if combo['metric_type'] == MetricType.COUNT:

                assert combo['year'] == 1914
                assert combo['month'] in (3, 9)

                if combo.get('return_type') != \
                        ReincarcerationReturnType.REVOCATION:
                    assert value == 1
                else:
                    assert value == 0

                if combo.get('metric_period_months') > 1:
                    assert combo['year'] == 1914
                    assert combo['month'] == 9
            elif combo['metric_type'] == MetricType.LIBERTY:

                assert combo['start_date'].year == 1914
                if combo['start_date'].month == 3:
                    assert value == days_at_liberty_1

                    # March month bucket
                    assert combo['start_date'] == date(1914, 3, 1)
                    assert combo['end_date'] == date(1914, 3, 31)
                elif combo['start_date'].month == 9:
                    assert value == days_at_liberty_2
                    # September month bucket
                    assert combo['start_date'] == date(1914, 9, 1)
                    assert combo['end_date'] == date(1914, 9, 30)
                else:
                    if combo['methodology'] == MetricMethodologyType.EVENT:
                        assert value in (days_at_liberty_1, days_at_liberty_2)
                    else:
                        assert value == days_at_liberty_1

                    # Year bucket
                    assert combo['start_date'] == date(1914, 1, 1)
                    assert combo['end_date'] == date(1914, 12, 31)

    def test_map_recidivism_combinations_count_twice_in_month(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_events_by_cohort = {
            1908: [RecidivismReleaseEvent(
                'CA', date(1905, 7, 19), date(1908, 9, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(1914, 3, 12), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)],
            1914: [RecidivismReleaseEvent(
                'CA', date(1914, 3, 12), date(1914, 3, 19), 'Hudson',
                _COUNTY_OF_RESIDENCE,
                date(1914, 3, 30), 'Upstate',
                ReincarcerationReturnType.NEW_ADMISSION)]
        }

        days_at_liberty_1 = (date(1914, 3, 12) - date(1908, 9, 19)).days
        days_at_liberty_2 = (date(1914, 3, 30) - date(1914, 3, 19)).days

        recidivism_combinations = calculator.map_recidivism_combinations(
            person, release_events_by_cohort, ALL_INCLUSIONS_DICT)

        # For the first event:
        #   For the first 5 periods:
        #       64 combinations of characteristics
        #       * 46 combinations of methodology/return type/supervision type
        #       * 5 periods = 14720 metrics
        #   For the second 5 periods
        #       64 combinations of characteristics
        #       * (46 combinations of methodology/return type/supervision type
        #           + 23 more instances) * 5 periods = 22080 metrics
        #
        #   Count + liberty windows: 64 * 1 count window * 46 combos +
        #       64 * 2 liberty windows * 4 combos = 3456
        #   Person-level metrics: (1 count window + 2 liberty windows) * 2 methodologies = 6
        #
        # For the second event:
        #   64 combinations * 46 combos * 10 periods +
        #   64 * 1 count window * 23 event-based-combos  +
        #   64 * 0 person-based-combos +
        #   64 * 2 liberty windows * 2 event-based-combos +
        #   64 * 0 person-based-combos = 31168 metrics
        #
        # Person-level metrics: (1 event-based count window + 2 liberty event-based windows) = 3

        # Multiplied by 2 to include the county of residence field
        expected_count = (14720 + 22080 + 3456 + 31168) * 2

        # Adding person-level metric counts
        expected_count += (6 + 3)

        assert len(recidivism_combinations) == expected_count

        for combo, value in recidivism_combinations:
            if combo['metric_type'] == MetricType.COUNT:
                assert combo['year'] == 1914
                assert combo['month'] == 3

                if combo.get('return_type') != \
                        ReincarcerationReturnType.REVOCATION:
                    assert value == 1
                else:
                    assert value == 0
            elif combo['metric_type'] == MetricType.LIBERTY:

                assert combo['start_date'].year == 1914
                if combo['start_date'].month == 3:
                    # March month bucket
                    assert combo['start_date'] == date(1914, 3, 1)
                    assert combo['end_date'] == date(1914, 3, 31)

                    if combo['methodology'] == MetricMethodologyType.EVENT:
                        assert value in (days_at_liberty_1, days_at_liberty_2)
                    else:
                        assert value == days_at_liberty_1
                else:
                    if combo['methodology'] == MetricMethodologyType.EVENT:
                        assert value in (days_at_liberty_1, days_at_liberty_2)
                    else:
                        assert value == days_at_liberty_1

                    # Year bucket
                    assert combo['start_date'] == date(1914, 1, 1)
                    assert combo['end_date'] == date(1914, 12, 31)


def expected_metric_count_for_person_recidivism(
        person: StatePerson,
        inclusions: Dict[str, bool]) -> int:
    """Returns the number of possible recidivism metric combinations for a
    given person, given the metric inclusions list."""
    total_metric_combos = demographic_metric_combos_count_for_person(
        person, inclusions)

    # County of residence is always included
    total_metric_combos *= 2

    return total_metric_combos


class TestCharacteristicCombinations(unittest.TestCase):
    """Tests the characteristic_combinations function."""
    def test_characteristic_combinations(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_event = RecidivismReleaseEvent(
            'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
            _COUNTY_OF_RESIDENCE,
            date(2014, 5, 12), 'Upstate',
            ReincarcerationReturnType.NEW_ADMISSION)

        combinations = calculator.characteristic_combinations(
            person, release_event, ALL_INCLUSIONS_DICT)

        expected_metric_count = expected_metric_count_for_person_recidivism(person, ALL_INCLUSIONS_DICT)

        # Add 1 for the person-level metric
        expected_metric_count += 1

        self.assertEqual(expected_metric_count, len(combinations))

    def test_characteristic_combinations_exclude_age(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_event = RecidivismReleaseEvent(
            'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
            _COUNTY_OF_RESIDENCE,
            date(2014, 5, 12), 'Upstate',
            ReincarcerationReturnType.NEW_ADMISSION)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'age_bucket': False,
        }

        combinations = calculator.characteristic_combinations(
            person, release_event, inclusions)

        expected_metric_count = expected_metric_count_for_person_recidivism(
            person, inclusions)

        # Add 1 for the person-level metric
        expected_metric_count += 1

        self.assertEqual(expected_metric_count, len(combinations))

        for combo in combinations:
            self.assertIsNone(combo.get('age_bucket'))

    def test_characteristic_combinations_exclude_gender(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_event = RecidivismReleaseEvent(
            'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
            _COUNTY_OF_RESIDENCE,
            date(2014, 5, 12), 'Upstate',
            ReincarcerationReturnType.NEW_ADMISSION)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'gender': False,
        }

        combinations = calculator.characteristic_combinations(
            person, release_event, inclusions)

        expected_metric_count = expected_metric_count_for_person_recidivism(
            person, inclusions)

        # Add 1 for the person-level metric
        expected_metric_count += 1

        self.assertEqual(expected_metric_count, len(combinations))

        for combo in combinations:
            self.assertIsNone(combo.get('gender'))

    def test_characteristic_combinations_exclude_race(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_event = RecidivismReleaseEvent(
            'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
            _COUNTY_OF_RESIDENCE,
            date(2014, 5, 12), 'Upstate',
            ReincarcerationReturnType.NEW_ADMISSION)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'race': False,
        }

        combinations = calculator.characteristic_combinations(
            person, release_event, inclusions)
        expected_metric_count = expected_metric_count_for_person_recidivism(
            person, inclusions)

        # Add 1 for the person-level metric
        expected_metric_count += 1

        self.assertEqual(expected_metric_count, len(combinations))

        for combo in combinations:
            self.assertIsNone(combo.get('race'))

    def test_characteristic_combinations_exclude_ethnicity(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_event = RecidivismReleaseEvent(
            'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
            _COUNTY_OF_RESIDENCE,
            date(2014, 5, 12), 'Upstate',
            ReincarcerationReturnType.NEW_ADMISSION)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'ethnicity': False,
        }

        combinations = calculator.characteristic_combinations(
            person, release_event, inclusions)

        expected_metric_count = expected_metric_count_for_person_recidivism(
            person, inclusions)

        # Add 1 for the person-level metric
        expected_metric_count += 1

        self.assertEqual(expected_metric_count, len(combinations))

        for combo in combinations:
            self.assertIsNone(combo.get('ethnicity'))

    def test_characteristic_combinations_exclude_release_facility(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_event = RecidivismReleaseEvent(
            'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
            _COUNTY_OF_RESIDENCE,
            date(2014, 5, 12), 'Upstate',
            ReincarcerationReturnType.NEW_ADMISSION)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'release_facility': False,
        }

        combinations = calculator.characteristic_combinations(
            person, release_event, inclusions)

        expected_metric_count = expected_metric_count_for_person_recidivism(
            person, inclusions)

        # Add 1 for the person-level metric
        expected_metric_count += 1

        self.assertEqual(expected_metric_count, len(combinations))

        for combo in combinations:
            self.assertIsNone(combo.get('release_facility'))

    def test_characteristic_combinations_exclude_stay_length(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_event = RecidivismReleaseEvent(
            'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
            _COUNTY_OF_RESIDENCE,
            date(2014, 5, 12), 'Upstate',
            ReincarcerationReturnType.NEW_ADMISSION)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'stay_length_bucket': False
        }

        combinations = calculator.characteristic_combinations(
            person, release_event, inclusions)

        expected_metric_count = expected_metric_count_for_person_recidivism(
            person, inclusions)

        # Add 1 for the person-level metric
        expected_metric_count += 1

        self.assertEqual(expected_metric_count, len(combinations))

        for combo in combinations:
            self.assertIsNone(combo.get('stay_length_bucket'))

    def test_characteristic_combinations_exclude_multiple(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_event = RecidivismReleaseEvent(
            'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
            _COUNTY_OF_RESIDENCE,
            date(2014, 5, 12), 'Upstate',
            ReincarcerationReturnType.NEW_ADMISSION)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'age_bucket': False,
            'ethnicity': False,
            'stay_length_bucket': False
        }

        combinations = calculator.characteristic_combinations(
            person, release_event, inclusions)

        expected_metric_count = expected_metric_count_for_person_recidivism(
            person, inclusions)

        # Add 1 for the person-level metric
        expected_metric_count += 1

        self.assertEqual(expected_metric_count, len(combinations))

        for combo in combinations:
            self.assertIsNone(combo.get('age_bucket'))
            self.assertIsNone(combo.get('ethnicity'))
            self.assertIsNone(combo.get('stay_length_bucket'))

    def test_characteristic_combinations_exclude_all(self):
        person = StatePerson.new_with_defaults(person_id=12345,
                                               birthdate=date(1984, 8, 31),
                                               gender=Gender.FEMALE)

        race = StatePersonRace.new_with_defaults(state_code='CA',
                                                 race=Race.WHITE)

        person.races = [race]

        ethnicity = StatePersonEthnicity.new_with_defaults(
            state_code='CA',
            ethnicity=Ethnicity.NOT_HISPANIC)

        person.ethnicities = [ethnicity]

        release_event = RecidivismReleaseEvent(
            'CA', date(2005, 7, 19), date(2008, 9, 19), 'Hudson',
            _COUNTY_OF_RESIDENCE,
            date(2014, 5, 12), 'Upstate',
            ReincarcerationReturnType.NEW_ADMISSION)

        inclusions = {
            **ALL_INCLUSIONS_DICT,
            'age_bucket': False,
            'gender': False,
            'race': False,
            'ethnicity': False,
            'release_facility': False,
            'stay_length_bucket': False
        }

        combinations = calculator.characteristic_combinations(
            person, release_event, inclusions)

        expected_metric_count = expected_metric_count_for_person_recidivism(
            person, inclusions)

        # Add 1 for the person-level metric
        expected_metric_count += 1

        self.assertEqual(expected_metric_count, len(combinations))

        # County of residence always populated
        self.assertCountEqual([{},
                               {'county_of_residence': _COUNTY_OF_RESIDENCE},
                               {'county_of_residence': 'county', 'person_id': 12345}],
                              combinations)
