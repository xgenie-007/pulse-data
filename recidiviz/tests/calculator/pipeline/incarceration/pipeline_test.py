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

"""Tests for incarceration/pipeline.py"""
import json
import unittest

import apache_beam as beam
from apache_beam.pvalue import AsDict
from apache_beam.testing.util import assert_that, equal_to, BeamAssertException
from apache_beam.testing.test_pipeline import TestPipeline
from apache_beam.options.pipeline_options import PipelineOptions

import datetime
from datetime import date

from recidiviz.calculator.pipeline.incarceration import pipeline, calculator
from recidiviz.calculator.pipeline.incarceration.incarceration_event import \
    IncarcerationAdmissionEvent, IncarcerationReleaseEvent, \
    IncarcerationStayEvent
from recidiviz.calculator.pipeline.incarceration.metrics import \
    IncarcerationMetric, IncarcerationMetricType
from recidiviz.calculator.pipeline.utils import extractor_utils
from recidiviz.calculator.pipeline.utils.beam_utils import \
    ConvertDictToKVTuple
from recidiviz.calculator.pipeline.utils.calculator_utils import \
    last_day_of_month
from recidiviz.calculator.pipeline.utils.entity_hydration_utils import SetSentencesOnSentenceGroup
from recidiviz.common.constants.state.state_incarceration import \
    StateIncarcerationType
from recidiviz.common.constants.state.state_incarceration_period import \
    StateIncarcerationPeriodStatus, StateIncarcerationFacilitySecurityLevel, \
    StateIncarcerationPeriodAdmissionReason, \
    StateIncarcerationPeriodReleaseReason
from recidiviz.common.constants.state.state_supervision_period import StateSupervisionPeriodSupervisionType
from recidiviz.persistence.entity.state.entities import \
    Gender, Race, ResidencyStatus, Ethnicity, StatePerson, \
    StateIncarcerationPeriod, StateIncarcerationSentence, StateSentenceGroup, StateCharge
from recidiviz.persistence.database.schema.state import schema
from recidiviz.persistence.entity.state import entities
from recidiviz.tests.calculator.calculator_test_utils import \
    normalized_database_base_dict, normalized_database_base_dict_list

_COUNTY_OF_RESIDENCE = 'county_of_residence'

ALL_INCLUSIONS_DICT = {
        'age_bucket': True,
        'gender': True,
        'race': True,
        'ethnicity': True,
    }


class TestIncarcerationPipeline(unittest.TestCase):
    """Tests the entire incarceration pipeline."""

    def testIncarcerationPipeline(self):
        fake_person_id = 12345

        fake_person = schema.StatePerson(
            person_id=fake_person_id, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        persons_data = [normalized_database_base_dict(fake_person)]

        race_1 = schema.StatePersonRace(
            person_race_id=111,
            state_code='CA',
            race=Race.BLACK,
            person_id=fake_person_id
        )

        race_2 = schema.StatePersonRace(
            person_race_id=111,
            state_code='ND',
            race=Race.WHITE,
            person_id=fake_person_id
        )

        races_data = normalized_database_base_dict_list([race_1, race_2])

        ethnicity = schema.StatePersonEthnicity(
            person_ethnicity_id=111,
            state_code='CA',
            ethnicity=Ethnicity.HISPANIC,
            person_id=fake_person_id)

        ethnicity_data = normalized_database_base_dict_list([ethnicity])

        sentence_group = schema.StateSentenceGroup(
            sentence_group_id=111,
            person_id=fake_person_id
        )

        initial_incarceration = schema.StateIncarcerationPeriod(
            incarceration_period_id=1111,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='CA',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.
            MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.
            NEW_ADMISSION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.
            CONDITIONAL_RELEASE,
            admission_date=date(2008, 11, 20),
            release_date=date(2010, 12, 4),
            release_reason=StateIncarcerationPeriodReleaseReason.
            SENTENCE_SERVED,
            person_id=fake_person_id,

        )

        first_reincarceration = schema.StateIncarcerationPeriod(
            incarceration_period_id=2222,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='CA',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.
            MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.
            NEW_ADMISSION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.
            CONDITIONAL_RELEASE,
            admission_date=date(2011, 4, 5),
            release_date=date(2014, 4, 14),
            release_reason=StateIncarcerationPeriodReleaseReason.
            SENTENCE_SERVED,
            person_id=fake_person_id)

        subsequent_reincarceration = schema.StateIncarcerationPeriod(
            incarceration_period_id=3333,
            status=StateIncarcerationPeriodStatus.IN_CUSTODY,
            state_code='CA',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.
            MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.
            NEW_ADMISSION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.
            CONDITIONAL_RELEASE,
            admission_date=date(2017, 1, 4),
            person_id=fake_person_id)

        incarceration_sentence = schema.StateIncarcerationSentence(
            incarceration_sentence_id=1111,
            sentence_group_id=sentence_group.sentence_group_id,
            incarceration_periods=[
                initial_incarceration,
                first_reincarceration,
                subsequent_reincarceration
            ],
            person_id=fake_person_id
        )

        supervision_sentence = schema.StateSupervisionSentence(
            supervision_sentence_id=123,
            person_id=fake_person_id
        )

        sentence_group.incarceration_sentences = [incarceration_sentence]

        sentence_group_data = [
            normalized_database_base_dict(sentence_group)
        ]

        incarceration_sentence_data = [
            normalized_database_base_dict(incarceration_sentence)
        ]

        supervision_sentence_data = [
            normalized_database_base_dict(supervision_sentence)
        ]

        incarceration_periods_data = [
            normalized_database_base_dict(initial_incarceration),
            normalized_database_base_dict(first_reincarceration),
            normalized_database_base_dict(subsequent_reincarceration)
        ]

        state_incarceration_sentence_incarceration_period_association = [
            {
                'incarceration_period_id': initial_incarceration.incarceration_period_id,
                'incarceration_sentence_id': incarceration_sentence.incarceration_sentence_id,
            },
            {
                'incarceration_period_id': first_reincarceration.incarceration_period_id,
                'incarceration_sentence_id': incarceration_sentence.incarceration_sentence_id,
            },
            {
                'incarceration_period_id': subsequent_reincarceration.incarceration_period_id,
                'incarceration_sentence_id': incarceration_sentence.incarceration_sentence_id,
            },
        ]

        data_dict = {
            schema.StatePerson.__tablename__: persons_data,
            schema.StatePersonRace.__tablename__: races_data,
            schema.StatePersonEthnicity.__tablename__: ethnicity_data,
            schema.StateSentenceGroup.__tablename__: sentence_group_data,
            schema.StateIncarcerationSentence.__tablename__: incarceration_sentence_data,
            schema.StateSupervisionSentence.__tablename__: supervision_sentence_data,
            schema.StateIncarcerationPeriod.__tablename__: incarceration_periods_data,
            schema.state_incarceration_sentence_incarceration_period_association_table.name:
                state_incarceration_sentence_incarceration_period_association,
            schema.state_supervision_sentence_incarceration_period_association_table.name: [{}]
        }

        test_pipeline = TestPipeline()

        # Get StatePersons
        persons = (test_pipeline
                   | 'Load Persons' >>
                   extractor_utils.BuildRootEntity(
                       dataset=None,
                       data_dict=data_dict,
                       root_schema_class=schema.StatePerson,
                       root_entity_class=entities.StatePerson,
                       unifying_id_field='person_id',
                       build_related_entities=True))

        # Get StateSentenceGroups
        sentence_groups = (test_pipeline
                           | 'Load StateSentencegroups' >>
                           extractor_utils.BuildRootEntity(
                               dataset=None,
                               data_dict=data_dict,
                               root_schema_class=
                               schema.StateSentenceGroup,
                               root_entity_class=
                               entities.StateSentenceGroup,
                               unifying_id_field='person_id',
                               build_related_entities=True))

        # Get StateIncarcerationSentences
        incarceration_sentences = (test_pipeline | 'Load StateIncarcerationSentences' >>
                                   extractor_utils.BuildRootEntity(
                                       dataset=None,
                                       data_dict=data_dict,
                                       root_schema_class=schema.StateIncarcerationSentence,
                                       root_entity_class=entities.StateIncarcerationSentence,
                                       unifying_id_field='person_id',
                                       build_related_entities=True
                                   ))

        # Get StateSupervisionSentences
        supervision_sentences = (test_pipeline | 'Load StateSupervisionSentences' >>
                                 extractor_utils.BuildRootEntity(
                                     dataset=None,
                                     data_dict=data_dict,
                                     root_schema_class=schema.StateSupervisionSentence,
                                     root_entity_class=entities.StateSupervisionSentence,
                                     unifying_id_field='person_id',
                                     build_related_entities=True
                                 ))

        sentences_and_sentence_groups = (
            {'sentence_groups': sentence_groups,
             'incarceration_sentences': incarceration_sentences,
             'supervision_sentences': supervision_sentences}
            | 'Group sentences to sentence groups' >>
            beam.CoGroupByKey()
        )

        sentence_groups_with_hydrated_sentences = (
            sentences_and_sentence_groups | 'Set hydrated sentences on sentence groups' >>
            beam.ParDo(SetSentencesOnSentenceGroup())
        )

        # Group each StatePerson with their related entities
        person_and_sentence_groups = (
            {'person': persons,
             'sentence_groups': sentence_groups_with_hydrated_sentences}
            | 'Group StatePerson to SentenceGroups' >>
            beam.CoGroupByKey()
        )

        # Identify IncarcerationEvents events from the StatePerson's
        # StateIncarcerationPeriods
        fake_person_id_to_county_query_result = [
            {'person_id': fake_person_id,
             'county_of_residence': _COUNTY_OF_RESIDENCE}]
        person_id_to_county_kv = (
            test_pipeline
            | "Read person id to county associations from BigQuery" >>
            beam.Create(fake_person_id_to_county_query_result)
            | "Convert to KV" >>
            beam.ParDo(ConvertDictToKVTuple(), 'person_id')
        )

        person_events = (
            person_and_sentence_groups |
            'Classify Incarceration Events' >>
            beam.ParDo(
                pipeline.ClassifyIncarcerationEvents(),
                AsDict(person_id_to_county_kv)))

        # Get pipeline job details for accessing job_id
        all_pipeline_options = PipelineOptions().get_all_options()

        # Add timestamp for local jobs
        job_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S.%f')
        all_pipeline_options['job_timestamp'] = job_timestamp

        # Get IncarcerationMetrics
        incarceration_metrics = (person_events
                                 | 'Get Incarceration Metrics' >>
                                 pipeline.GetIncarcerationMetrics(
                                     pipeline_options=all_pipeline_options,
                                     inclusions=ALL_INCLUSIONS_DICT,
                                     calculation_month_limit=-1))

        assert_that(incarceration_metrics,
                    AssertMatchers.validate_metric_type())

        test_pipeline.run()

    def testIncarcerationPipelineNoIncarceration(self):
        """Tests the incarceration pipeline when a person doesn't have any
        incarceration periods."""
        fake_person_id_1 = 12345

        fake_person_1 = schema.StatePerson(
            person_id=fake_person_id_1, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        fake_person_id_2 = 6789

        fake_person_2 = schema.StatePerson(
            person_id=fake_person_id_2, gender=Gender.FEMALE,
            birthdate=date(1990, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        persons_data = [normalized_database_base_dict(fake_person_1),
                        normalized_database_base_dict(fake_person_2)]

        sentence_group = schema.StateSentenceGroup(
            sentence_group_id=111,
            person_id=fake_person_id_1
        )

        incarceration_period = schema.StateIncarcerationPeriod(
            incarceration_period_id=1111,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='CA',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.
            MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.
            NEW_ADMISSION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.
            CONDITIONAL_RELEASE,
            admission_date=date(2008, 11, 20),
            release_date=date(2010, 12, 4),
            release_reason=StateIncarcerationPeriodReleaseReason.
            SENTENCE_SERVED,
            person_id=fake_person_id_1)

        incarceration_sentence = schema.StateIncarcerationSentence(
            incarceration_sentence_id=1111,
            sentence_group_id=sentence_group.sentence_group_id,
            incarceration_periods=[incarceration_period],
            person_id=fake_person_id_1
        )

        supervision_sentence = schema.StateSupervisionSentence(
            supervision_sentence_id=123,
            person_id=fake_person_id_1
        )

        sentence_group.incarceration_sentences = [incarceration_sentence]

        sentence_group_data = [
            normalized_database_base_dict(sentence_group)
        ]

        incarceration_sentence_data = [
            normalized_database_base_dict(incarceration_sentence)
        ]

        supervision_sentence_data = [
            normalized_database_base_dict(supervision_sentence)
        ]

        incarceration_periods_data = [
            normalized_database_base_dict(incarceration_period)
        ]

        state_incarceration_sentence_incarceration_period_association = [
            {
                'incarceration_period_id': incarceration_period.incarceration_period_id,
                'incarceration_sentence_id': incarceration_sentence.incarceration_sentence_id,
            },
        ]

        data_dict = {
            schema.StatePerson.__tablename__: persons_data,
            schema.StateSentenceGroup.__tablename__: sentence_group_data,
            schema.StateIncarcerationSentence.__tablename__: incarceration_sentence_data,
            schema.StateSupervisionSentence.__tablename__: supervision_sentence_data,
            schema.StateIncarcerationPeriod.__tablename__: incarceration_periods_data,
            schema.state_incarceration_sentence_incarceration_period_association_table.name:
                state_incarceration_sentence_incarceration_period_association,
            schema.state_supervision_sentence_incarceration_period_association_table.name: [{}]
        }

        test_pipeline = TestPipeline()

        # Get StatePersons
        persons = (test_pipeline
                   | 'Load Persons' >>
                   extractor_utils.BuildRootEntity(
                       dataset=None,
                       data_dict=data_dict,
                       root_schema_class=schema.StatePerson,
                       root_entity_class=entities.StatePerson,
                       unifying_id_field='person_id',
                       build_related_entities=True))

        # Get StateSentenceGroups
        sentence_groups = (test_pipeline
                           | 'Load StateSentencegroups' >>
                           extractor_utils.BuildRootEntity(
                               dataset=None,
                               data_dict=data_dict,
                               root_schema_class=
                               schema.StateSentenceGroup,
                               root_entity_class=
                               entities.StateSentenceGroup,
                               unifying_id_field='person_id',
                               build_related_entities=True))

        # Get StateIncarcerationSentences
        incarceration_sentences = (test_pipeline | 'Load StateIncarcerationSentences' >>
                                   extractor_utils.BuildRootEntity(
                                       dataset=None,
                                       data_dict=data_dict,
                                       root_schema_class=schema.StateIncarcerationSentence,
                                       root_entity_class=entities.StateIncarcerationSentence,
                                       unifying_id_field='person_id',
                                       build_related_entities=True
                                   ))

        # Get StateSupervisionSentences
        supervision_sentences = (test_pipeline | 'Load StateSupervisionSentences' >>
                                 extractor_utils.BuildRootEntity(
                                     dataset=None,
                                     data_dict=data_dict,
                                     root_schema_class=schema.StateSupervisionSentence,
                                     root_entity_class=entities.StateSupervisionSentence,
                                     unifying_id_field='person_id',
                                     build_related_entities=True
                                 ))

        sentences_and_sentence_groups = (
            {'sentence_groups': sentence_groups,
             'incarceration_sentences': incarceration_sentences,
             'supervision_sentences': supervision_sentences}
            | 'Group sentences to sentence groups' >>
            beam.CoGroupByKey()
        )

        sentence_groups_with_hydrated_sentences = (
            sentences_and_sentence_groups | 'Set hydrated sentences on sentence groups' >>
            beam.ParDo(SetSentencesOnSentenceGroup())
        )

        # Group each StatePerson with their related entities
        person_and_sentence_groups = (
            {'person': persons,
             'sentence_groups': sentence_groups_with_hydrated_sentences}
            | 'Group StatePerson to SentenceGroups' >>
            beam.CoGroupByKey()
        )

        # Identify IncarcerationEvents events from the StatePerson's
        # StateIncarcerationPeriods
        fake_person_id_to_county_query_result = [
            {'person_id': fake_person_id_1,
             'county_of_residence': _COUNTY_OF_RESIDENCE}]
        person_id_to_county_kv = (
            test_pipeline
            | "Read person id to county associations from BigQuery" >>
            beam.Create(fake_person_id_to_county_query_result)
            | "Convert to KV" >>
            beam.ParDo(ConvertDictToKVTuple(), 'person_id')
        )

        person_events = (
            person_and_sentence_groups |
            'Classify Incarceration Events' >>
            beam.ParDo(
                pipeline.ClassifyIncarcerationEvents(),
                AsDict(person_id_to_county_kv)))

        # Get pipeline job details for accessing job_id
        all_pipeline_options = PipelineOptions().get_all_options()

        # Add timestamp for local jobs
        job_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S.%f')
        all_pipeline_options['job_timestamp'] = job_timestamp

        # Get IncarcerationMetrics
        incarceration_metrics = (person_events
                                 | 'Get Incarceration Metrics' >>
                                 pipeline.GetIncarcerationMetrics(
                                     pipeline_options=all_pipeline_options,
                                     inclusions=ALL_INCLUSIONS_DICT,
                                     calculation_month_limit=-1))

        assert_that(incarceration_metrics,
                    AssertMatchers.validate_metric_type())

        test_pipeline.run()


class TestClassifyIncarcerationEvents(unittest.TestCase):
    """Tests the ClassifyIncarcerationEvents DoFn in the pipeline."""

    def testClassifyIncarcerationEvents(self):
        """Tests the ClassifyIncarcerationEvents DoFn."""
        fake_person_id = 12345

        fake_person = StatePerson.new_with_defaults(
            person_id=fake_person_id, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        incarceration_period = StateIncarcerationPeriod.new_with_defaults(
            incarceration_period_id=1111,
            incarceration_type=StateIncarcerationType.STATE_PRISON,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='TX',
            facility='PRISON XX',
            admission_date=date(2010, 11, 20),
            admission_reason=StateIncarcerationPeriodAdmissionReason.PROBATION_REVOCATION,
            release_date=date(2010, 12, 4),
            release_reason=StateIncarcerationPeriodReleaseReason.SENTENCE_SERVED)

        incarceration_sentence = StateIncarcerationSentence.new_with_defaults(
            incarceration_sentence_id=123,
            incarceration_periods=[incarceration_period],
            charges=[
                StateCharge.new_with_defaults(
                    ncic_code='5699',
                    statute='CIVIL RIGHTS',
                    offense_date=date(2009, 1, 9)
                )
            ]
        )

        sentence_group = StateSentenceGroup.new_with_defaults(
            sentence_group_id=123,
            incarceration_sentences=[incarceration_sentence]
        )

        incarceration_sentence.sentence_group = sentence_group

        incarceration_period.incarceration_sentences = [incarceration_sentence]

        person_entities = {'person': [fake_person], 'sentence_groups': [sentence_group]}

        fake_person_id_to_county_query_result = [
            {'person_id': fake_person_id, 'county_of_residence': _COUNTY_OF_RESIDENCE}]

        incarceration_events = [
            IncarcerationStayEvent(
                admission_reason=incarceration_period.admission_reason,
                admission_reason_raw_text=incarceration_period.admission_reason_raw_text,
                supervision_type_at_admission=StateSupervisionPeriodSupervisionType.PROBATION,
                state_code=incarceration_period.state_code,
                event_date=last_day_of_month(incarceration_period.admission_date),
                facility=incarceration_period.facility,
                county_of_residence=_COUNTY_OF_RESIDENCE,
                most_serious_offense_statute='CIVIL RIGHTS'
            ),
            IncarcerationAdmissionEvent(
                state_code=incarceration_period.state_code,
                event_date=incarceration_period.admission_date,
                facility=incarceration_period.facility,
                county_of_residence=_COUNTY_OF_RESIDENCE,
                admission_reason=incarceration_period.admission_reason,
                admission_reason_raw_text=incarceration_period.admission_reason_raw_text,
                supervision_type_at_admission=StateSupervisionPeriodSupervisionType.PROBATION,
            ),
            IncarcerationReleaseEvent(
                state_code=incarceration_period.state_code,
                event_date=incarceration_period.release_date,
                facility=incarceration_period.facility,
                county_of_residence=_COUNTY_OF_RESIDENCE,
                release_reason=incarceration_period.release_reason
            )
        ]

        correct_output = [(fake_person, incarceration_events)]

        test_pipeline = TestPipeline()

        person_id_to_county_kv = (
            test_pipeline
            | "Read person id to county associations from BigQuery" >>
            beam.Create(fake_person_id_to_county_query_result)
            | "Convert to KV" >> beam.ParDo(ConvertDictToKVTuple(), 'person_id')
        )

        output = (test_pipeline
                  | beam.Create([(fake_person_id, person_entities)])
                  | 'Identify Incarceration Events' >> beam.ParDo(
                      pipeline.ClassifyIncarcerationEvents(), AsDict(person_id_to_county_kv)))

        assert_that(output, equal_to(correct_output))

        test_pipeline.run()

    def testClassifyIncarcerationEvents_NoSentenceGroups(self):
        """Tests the ClassifyIncarcerationEvents DoFn when the person has no sentence groups."""
        fake_person = StatePerson.new_with_defaults(
            person_id=123, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        person_periods = {'person': [fake_person],
                          'sentence_groups': []}

        test_pipeline = TestPipeline()

        output = (test_pipeline
                  | beam.Create([(fake_person.person_id, person_periods)])
                  | 'Identify Incarceration Events' >>
                  beam.ParDo(
                      pipeline.ClassifyIncarcerationEvents(), {})
                  )

        assert_that(output, equal_to([]))

        test_pipeline.run()


class TestCalculateIncarcerationMetricCombinations(unittest.TestCase):
    """Tests the CalculateIncarcerationMetricCombinations DoFn
    in the pipeline."""

    def testCalculateIncarcerationMetricCombinations(self):
        """Tests the CalculateIncarcerationMetricCombinations DoFn."""
        fake_person = StatePerson.new_with_defaults(
            person_id=123, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        incarceration_events = [
            IncarcerationAdmissionEvent(
                state_code='CA',
                event_date=date(2001, 3, 16),
                facility='SAN QUENTIN',
                county_of_residence='county_of_residence',
                admission_reason=StateIncarcerationPeriodAdmissionReason.
                PROBATION_REVOCATION
            ),
            IncarcerationReleaseEvent(
                state_code='CA',
                event_date=date(2002, 5, 26),
                facility='SAN QUENTIN',
                county_of_residence='county_of_residence',
                release_reason=StateIncarcerationPeriodReleaseReason.
                SENTENCE_SERVED
            )
        ]

        # Get the number of combinations of person-event characteristics.
        num_combinations = len(calculator.characteristic_combinations(
            fake_person, incarceration_events[0], ALL_INCLUSIONS_DICT, IncarcerationMetricType.POPULATION))
        assert num_combinations > 0

        expected_metric_count = num_combinations * 2

        expected_admission_combination_counts = \
            {'admissions': expected_metric_count}

        expected_releases_combination_counts = \
            {'releases': expected_metric_count}

        test_pipeline = TestPipeline()

        output = (test_pipeline
                  | beam.Create([(fake_person, incarceration_events)])
                  | 'Calculate Incarceration Metrics' >>
                  beam.ParDo(
                      pipeline.CalculateIncarcerationMetricCombinations(),
                      -1, ALL_INCLUSIONS_DICT).with_outputs('admissions', 'releases')
                  )

        assert_that(output.admissions, AssertMatchers.
                    count_combinations(expected_admission_combination_counts),
                    'Assert number of admission metrics is expected value')

        assert_that(output.releases, AssertMatchers.
                    count_combinations(expected_releases_combination_counts),
                    'Assert number of release metrics is expected value')

        test_pipeline.run()

    def testCalculateIncarcerationMetricCombinations_NoIncarceration(self):
        """Tests the CalculateIncarcerationMetricCombinations when there are
        no incarceration_events. This should never happen because any person
        without incarceration events is dropped entirely from the pipeline."""
        fake_person = StatePerson.new_with_defaults(
            person_id=123, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        test_pipeline = TestPipeline()

        output = (test_pipeline
                  | beam.Create([(fake_person, [])])
                  | 'Calculate Incarceration Metrics' >>
                  beam.ParDo(
                      pipeline.CalculateIncarcerationMetricCombinations(),
                      -1, ALL_INCLUSIONS_DICT)
                  )

        assert_that(output, equal_to([]))

        test_pipeline.run()

    def testCalculateIncarcerationMetricCombinations_NoInput(self):
        """Tests the CalculateIncarcerationMetricCombinations when there is
        no input to the function."""

        test_pipeline = TestPipeline()

        output = (test_pipeline
                  | beam.Create([])
                  | 'Calculate Incarceration Metrics' >>
                  beam.ParDo(
                      pipeline.CalculateIncarcerationMetricCombinations(),
                      -1, ALL_INCLUSIONS_DICT)
                  )

        assert_that(output, equal_to([]))

        test_pipeline.run()


class AssertMatchers:
    """Functions to be used by Apache Beam testing `assert_that` functions to
    validate pipeline outputs."""

    @staticmethod
    def validate_metric_type():

        def _validate_metric_type(output):

            for metric in output:
                if not isinstance(metric, IncarcerationMetric):
                    raise BeamAssertException(
                        'Failed assert. Output is not of type'
                        'IncarcerationMetric.')

        return _validate_metric_type

    @staticmethod
    def count_combinations(expected_combination_counts):
        """Asserts that the number of metric combinations matches the expected
        counts."""
        def _count_combinations(output):
            actual_combination_counts = {}

            for key in expected_combination_counts.keys():
                actual_combination_counts[key] = 0

            for result in output:
                combination, _ = result

                combination_dict = json.loads(combination)
                metric_type = combination_dict.get('metric_type')

                if metric_type == IncarcerationMetricType.ADMISSION.value:
                    actual_combination_counts['admissions'] = \
                        actual_combination_counts['admissions'] + 1
                elif metric_type == IncarcerationMetricType.RELEASE.value:
                    actual_combination_counts['releases'] = \
                        actual_combination_counts['releases'] + 1

            for key in expected_combination_counts:
                if expected_combination_counts[key] != \
                        actual_combination_counts[key]:

                    raise BeamAssertException('Failed assert. Count does not'
                                              'match expected value.')

        return _count_combinations
