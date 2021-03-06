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

"""Tests for supervision/pipeline.py"""
import json
import unittest
from typing import Set

import apache_beam as beam
from apache_beam.pvalue import AsDict
from apache_beam.testing.util import assert_that, equal_to, BeamAssertException
from apache_beam.testing.test_pipeline import TestPipeline
from apache_beam.options.pipeline_options import PipelineOptions

import datetime
from datetime import date

from freezegun import freeze_time

from recidiviz.calculator.pipeline.supervision import pipeline, calculator
from recidiviz.calculator.pipeline.supervision.metrics import \
    SupervisionMetric, SupervisionMetricType, SupervisionRevocationMetric, \
    SupervisionRevocationViolationTypeAnalysisMetric, SupervisionPopulationMetric, \
    SupervisionRevocationAnalysisMetric, \
    TerminatedSupervisionAssessmentScoreChangeMetric, SupervisionSuccessMetric
from recidiviz.calculator.pipeline.supervision.supervision_time_bucket import \
    NonRevocationReturnSupervisionTimeBucket, \
    RevocationReturnSupervisionTimeBucket,\
    ProjectedSupervisionCompletionBucket, SupervisionTerminationBucket
from recidiviz.calculator.pipeline.utils.metric_utils import \
    MetricMethodologyType
from recidiviz.calculator.pipeline.utils import extractor_utils
from recidiviz.calculator.pipeline.recidivism.pipeline import \
    json_serializable_metric_key
from recidiviz.common.constants.state.state_assessment import \
    StateAssessmentType
from recidiviz.common.constants.state.state_case_type import \
    StateSupervisionCaseType
from recidiviz.common.constants.state.state_incarceration import StateIncarcerationType
from recidiviz.common.constants.state.state_incarceration_period import \
    StateIncarcerationPeriodStatus, StateIncarcerationPeriodAdmissionReason, \
    StateIncarcerationPeriodReleaseReason, \
    StateIncarcerationFacilitySecurityLevel
from recidiviz.common.constants.state.state_sentence import StateSentenceStatus
from recidiviz.common.constants.state.state_supervision import \
    StateSupervisionType
from recidiviz.common.constants.state.state_supervision_period import \
    StateSupervisionPeriodTerminationReason, StateSupervisionPeriodSupervisionType, StateSupervisionLevel
from recidiviz.common.constants.state.state_supervision_violation import \
    StateSupervisionViolationType as ViolationType, \
    StateSupervisionViolationType
from recidiviz.common.constants.state.state_supervision_violation_response \
    import StateSupervisionViolationResponseRevocationType as RevocationType, \
    StateSupervisionViolationResponseRevocationType, StateSupervisionViolationResponseType
from recidiviz.persistence.database.schema.state import schema
from recidiviz.persistence.entity.state import entities
from recidiviz.persistence.entity.state.entities import \
    StateIncarcerationPeriod, Gender, Race, ResidencyStatus, Ethnicity, \
    StateSupervisionSentence, StateAssessment, StateSupervisionViolationResponse, StateSupervisionViolation, \
    StateSupervisionViolationTypeEntry, StateIncarcerationSentence
from recidiviz.persistence.entity.state.entities import StatePerson
from recidiviz.tests.calculator.calculator_test_utils import \
    normalized_database_base_dict, normalized_database_base_dict_list
from recidiviz.tests.persistence.database import database_test_utils

ALL_INCLUSIONS_DICT = {
        'age_bucket': True,
        'gender': True,
        'race': True,
        'ethnicity': True,
        SupervisionMetricType.ASSESSMENT_CHANGE.value: True,
        SupervisionMetricType.SUCCESS.value: True,
        SupervisionMetricType.REVOCATION.value: True,
        SupervisionMetricType.REVOCATION_ANALYSIS.value: True,
        SupervisionMetricType.REVOCATION_VIOLATION_TYPE_ANALYSIS.value: True,
        SupervisionMetricType.POPULATION.value: True,
    }


class TestSupervisionPipeline(unittest.TestCase):
    """Tests the entire supervision pipeline."""

    def testSupervisionPipeline(self):
        fake_person_id = 12345

        fake_person = schema.StatePerson(
            person_id=fake_person_id, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        persons_data = [normalized_database_base_dict(fake_person)]

        initial_incarceration = schema.StateIncarcerationPeriod(
            incarceration_period_id=1111,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='US_ND',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.NEW_ADMISSION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.CONDITIONAL_RELEASE,
            admission_date=date(2008, 11, 20),
            release_date=date(2010, 12, 4),
            release_reason=StateIncarcerationPeriodReleaseReason.SENTENCE_SERVED,
            person_id=fake_person_id
        )

        first_reincarceration = schema.StateIncarcerationPeriod(
            incarceration_period_id=2222,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='US_ND',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.NEW_ADMISSION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.CONDITIONAL_RELEASE,
            admission_date=date(2011, 4, 5),
            release_date=date(2014, 4, 14),
            release_reason=StateIncarcerationPeriodReleaseReason.SENTENCE_SERVED,
            person_id=fake_person_id)

        subsequent_reincarceration = schema.StateIncarcerationPeriod(
            incarceration_period_id=3333,
            status=StateIncarcerationPeriodStatus.IN_CUSTODY,
            state_code='US_ND',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.NEW_ADMISSION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.CONDITIONAL_RELEASE,
            admission_date=date(2017, 1, 4),
            person_id=fake_person_id)

        supervision_period = schema.StateSupervisionPeriod(
            supervision_period_id=1111,
            state_code='US_ND',
            county_code='124',
            start_date=date(2015, 3, 14),
            termination_date=date(2016, 12, 29),
            supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
            supervision_level=StateSupervisionLevel.MINIMUM,
            person_id=fake_person_id
        )

        supervision_sentence = schema.StateSupervisionSentence(
            supervision_sentence_id=1122,
            state_code='US_ND',
            supervision_periods=[supervision_period],
            projected_completion_date=date(2016, 12, 31),
            person_id=fake_person_id
        )

        incarceration_sentence = schema.StateIncarcerationSentence(
            incarceration_sentence_id=123,
            state_code='US_ND',
            person_id=fake_person_id,
            incarceration_periods=[initial_incarceration, subsequent_reincarceration, first_reincarceration]
        )

        supervision_sentence_supervision_period_association = [
            {
                'supervision_period_id': 1111,
                'supervision_sentence_id': 1122,
            }
        ]

        charge = database_test_utils.generate_test_charge(
            person_id=fake_person_id,
            charge_id=1234523,
            court_case=None,
            bond=None
        )

        assessment = schema.StateAssessment(
            assessment_id=298374,
            assessment_date=date(2015, 3, 19),
            assessment_type=StateAssessmentType.LSIR,
            person_id=fake_person_id
        )

        incarceration_periods_data = [
            normalized_database_base_dict(initial_incarceration),
            normalized_database_base_dict(first_reincarceration),
            normalized_database_base_dict(subsequent_reincarceration)
        ]

        supervision_periods_data = [
            normalized_database_base_dict(supervision_period)
        ]

        supervision_sentences_data = [
            normalized_database_base_dict(supervision_sentence)
        ]

        incarceration_sentences_data = [
            normalized_database_base_dict(incarceration_sentence)
        ]

        charge_data = [
            normalized_database_base_dict(charge)
        ]

        supervision_violation_response = \
            database_test_utils.generate_test_supervision_violation_response(
                fake_person_id)

        supervision_violation = \
            database_test_utils.generate_test_supervision_violation(
                fake_person_id,
                [supervision_violation_response]
            )

        supervision_violation_data = [
            normalized_database_base_dict(supervision_violation)
        ]

        supervision_violation_response.supervision_violation_id = \
            supervision_violation.supervision_violation_id

        supervision_violation_response_data = [
            normalized_database_base_dict(supervision_violation_response)
        ]

        assessment_data = [
            normalized_database_base_dict(assessment)
        ]

        data_dict = {
            schema.StatePerson.__tablename__: persons_data,
            schema.StateIncarcerationPeriod.__tablename__: incarceration_periods_data,
            schema.StateSupervisionViolationResponse.__tablename__: supervision_violation_response_data,
            schema.StateSupervisionViolation.__tablename__: supervision_violation_data,
            schema.StateSupervisionPeriod.__tablename__: supervision_periods_data,
            schema.StateSupervisionSentence.__tablename__: supervision_sentences_data,
            schema.StateIncarcerationSentence.__tablename__: incarceration_sentences_data,
            schema.StateCharge.__tablename__: charge_data,
            schema.state_charge_supervision_sentence_association_table.name: [{}],
            schema.state_charge_incarceration_sentence_association_table.name: [{}],
            schema.state_incarceration_sentence_incarceration_period_association_table.name: [{}],
            schema.state_incarceration_sentence_supervision_period_association_table.name: [{}],
            schema.state_supervision_sentence_incarceration_period_association_table.name: [{}],
            schema.state_supervision_sentence_supervision_period_association_table.name:
            supervision_sentence_supervision_period_association,
            schema.StateAssessment.__tablename__: assessment_data
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

        # Get StateIncarcerationPeriods
        incarceration_periods = (test_pipeline
                                 | 'Load IncarcerationPeriods' >>
                                 extractor_utils.BuildRootEntity(
                                     dataset=None,
                                     data_dict=data_dict,
                                     root_schema_class=
                                     schema.StateIncarcerationPeriod,
                                     root_entity_class=
                                     entities.StateIncarcerationPeriod,
                                     unifying_id_field='person_id',
                                     build_related_entities=True))

        # Get StateSupervisionViolations
        supervision_violations = \
            (test_pipeline
             | 'Load SupervisionViolations' >>
             extractor_utils.BuildRootEntity(
                 dataset=None,
                 data_dict=data_dict,
                 root_schema_class=schema.StateSupervisionViolation,
                 root_entity_class=entities.StateSupervisionViolation,
                 unifying_id_field='person_id',
                 build_related_entities=True
             ))

        # Get StateSupervisionViolationResponses
        supervision_violation_responses = \
            (test_pipeline
             | 'Load SupervisionViolationResponses' >>
             extractor_utils.BuildRootEntity(
                 dataset=None,
                 data_dict=data_dict,
                 root_schema_class=schema.StateSupervisionViolationResponse,
                 root_entity_class=entities.StateSupervisionViolationResponse,
                 unifying_id_field='person_id',
                 build_related_entities=True
             ))

        # Get StateSupervisionSentences
        supervision_sentences = (test_pipeline
                                 | 'Load SupervisionSentences' >>
                                 extractor_utils.BuildRootEntity(
                                     dataset=None,
                                     data_dict=data_dict,
                                     root_schema_class=
                                     schema.StateSupervisionSentence,
                                     root_entity_class=
                                     entities.StateSupervisionSentence,
                                     unifying_id_field='person_id',
                                     build_related_entities=True))

        # Get StateIncarcerationSentences
        incarceration_sentences = (test_pipeline
                                   | 'Load IncarcerationSentences' >>
                                   extractor_utils.BuildRootEntity(
                                       dataset=None,
                                       data_dict=data_dict,
                                       root_schema_class=schema.StateIncarcerationSentence,
                                       root_entity_class=entities.StateIncarcerationSentence,
                                       unifying_id_field='person_id',
                                       build_related_entities=True))

        # Get StateSupervisionPeriods
        supervision_periods = (test_pipeline
                               | 'Load SupervisionPeriods' >>
                               extractor_utils.BuildRootEntity(
                                   dataset=None,
                                   data_dict=data_dict,
                                   root_schema_class=
                                   schema.StateSupervisionPeriod,
                                   root_entity_class=
                                   entities.StateSupervisionPeriod,
                                   unifying_id_field='person_id',
                                   build_related_entities=False))

        # Get StateAssessments
        assessments = (test_pipeline
                       | 'Load Assessments' >>
                       extractor_utils.BuildRootEntity(
                           dataset=None,
                           data_dict=data_dict,
                           root_schema_class=
                           schema.StateAssessment,
                           root_entity_class=
                           entities.StateAssessment,
                           unifying_id_field='person_id',
                           build_related_entities=False))

        # Group StateSupervisionViolationResponses and StateSupervisionViolations by person_id
        supervision_violations_and_responses = (
            {'violations': supervision_violations,
             'violation_responses': supervision_violation_responses
             } | 'Group StateSupervisionViolationResponses to StateSupervisionViolations' >>
            beam.CoGroupByKey()
        )

        # Set the fully hydrated StateSupervisionViolation entities on the corresponding
        # StateSupervisionViolationResponses
        violation_responses_with_hydrated_violations = (
            supervision_violations_and_responses
            | 'Set hydrated StateSupervisionViolations on the StateSupervisionViolationResponses' >>
            beam.ParDo(pipeline.SetViolationOnViolationsResponse()))

        # Group StateIncarcerationPeriods and StateSupervisionViolationResponses by person_id
        incarceration_periods_and_violation_responses = (
            {'incarceration_periods': incarceration_periods,
             'violation_responses': violation_responses_with_hydrated_violations}
            | 'Group StateIncarcerationPeriods to StateSupervisionViolationResponses' >>
            beam.CoGroupByKey()
        )

        # Set the fully hydrated StateSupervisionViolationResponse entities on
        # the corresponding StateIncarcerationPeriods
        incarceration_periods_with_source_violations = (
            incarceration_periods_and_violation_responses
            | 'Set hydrated StateSupervisionViolationResponses on the StateIncarcerationPeriods' >>
            beam.ParDo(pipeline.SetViolationResponseOnIncarcerationPeriod()))

        # Group each StatePerson with their StateIncarcerationPeriods and
        # StateSupervisionSentences
        person_periods_and_sentences = (
            {'person': persons,
             'assessments': assessments,
             'supervision_periods': supervision_periods,
             'incarceration_periods': incarceration_periods_with_source_violations,
             'supervision_sentences': supervision_sentences,
             'incarceration_sentences': incarceration_sentences,
             'violation_responses': violation_responses_with_hydrated_violations
             }
            | 'Group StatePerson to StateIncarcerationPeriods and StateSupervisionPeriods' >>
            beam.CoGroupByKey()
        )

        ssvr_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_violation_response_id': supervision_violation_response.supervision_violation_response_id
        }

        ssvr_to_agent_associations = (
            test_pipeline | 'Create SSVR to Agent table' >> beam.Create([ssvr_to_agent_map])
        )

        ssvr_agent_associations_as_kv = (
            ssvr_to_agent_associations | 'Convert SSVR to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(), 'supervision_violation_response_id')
        )

        supervision_period_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_period_id': supervision_period.supervision_period_id
        }

        supervision_period_to_agent_associations = (
            test_pipeline | 'Create SupervisionPeriod to Agent table' >> beam.Create([supervision_period_to_agent_map])
        )

        supervision_periods_to_agent_associations_as_kv = (
            supervision_period_to_agent_associations |
            'Convert SupervisionPeriod to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(), 'supervision_period_id')
        )

        identifier_options = {
            'state_code': 'ALL'
        }

        # Identify SupervisionTimeBuckets from the StatePerson's
        # StateSupervisionSentences and StateIncarcerationPeriods
        person_time_buckets = (
            person_periods_and_sentences
            | beam.ParDo(
                pipeline.ClassifySupervisionTimeBuckets(),
                AsDict(ssvr_agent_associations_as_kv),
                AsDict(supervision_periods_to_agent_associations_as_kv),
                **identifier_options))

        # Get pipeline job details for accessing job_id
        all_pipeline_options = PipelineOptions().get_all_options()

        # Add timestamp for local jobs
        job_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S.%f')
        all_pipeline_options['job_timestamp'] = job_timestamp

        # Get supervision metrics
        supervision_metrics = (person_time_buckets
                               | 'Get Supervision Metrics' >>
                               pipeline.GetSupervisionMetrics(
                                   pipeline_options=all_pipeline_options,
                                   inclusions=ALL_INCLUSIONS_DICT,
                                   metric_type='ALL',
                                   calculation_month_limit=-1))

        assert_that(supervision_metrics, AssertMatchers.validate_pipeline_test(
            {SupervisionMetricType.POPULATION, SupervisionMetricType.SUCCESS}))

        test_pipeline.run()

    @freeze_time('2017-01-31')
    def testSupervisionPipeline_withRevocations(self):
        fake_person_id = 12345
        fake_svr_id = 56789
        fake_violation_id = 345789

        fake_person = schema.StatePerson(
            person_id=fake_person_id, gender=Gender.FEMALE,
            birthdate=date(1990, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        persons_data = [normalized_database_base_dict(fake_person)]

        initial_incarceration = schema.StateIncarcerationPeriod(
            incarceration_period_id=1111,
            incarceration_type=StateIncarcerationType.STATE_PRISON,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='US_MO',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.NEW_ADMISSION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.CONDITIONAL_RELEASE,
            admission_date=date(2008, 11, 20),
            release_date=date(2010, 12, 4),
            release_reason=StateIncarcerationPeriodReleaseReason.
            SENTENCE_SERVED,
            person_id=fake_person_id
        )

        first_reincarceration = schema.StateIncarcerationPeriod(
            incarceration_period_id=2222,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            incarceration_type=StateIncarcerationType.STATE_PRISON,
            state_code='US_MO',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.NEW_ADMISSION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.CONDITIONAL_RELEASE,
            admission_date=date(2011, 4, 5),
            release_date=date(2014, 4, 14),
            release_reason=StateIncarcerationPeriodReleaseReason.SENTENCE_SERVED,
            person_id=fake_person_id)

        # This probation supervision period ended in a revocation
        supervision_period = schema.StateSupervisionPeriod(
            supervision_period_id=1111,
            state_code='US_MO',
            county_code='124',
            start_date=date(2015, 3, 14),
            termination_date=date(2017, 1, 4),
            termination_reason=
            StateSupervisionPeriodTerminationReason.REVOCATION,
            supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
            person_id=fake_person_id
        )

        supervision_sentence = schema.StateSupervisionSentence(
            supervision_sentence_id=1122,
            state_code='US_MO',
            supervision_type=StateSupervisionType.PROBATION,
            supervision_periods=[supervision_period],
            projected_completion_date=date(2017, 12, 31),
            person_id=fake_person_id
        )

        incarceration_sentence = schema.StateIncarcerationSentence(
            incarceration_sentence_id=123,
            state_code='US_ND',
            person_id=fake_person_id
        )

        supervision_sentence_supervision_period_association = [
            {
                'supervision_period_id': 1111,
                'supervision_sentence_id': 1122,
            }
        ]

        charge = database_test_utils.generate_test_charge(
            person_id=fake_person_id,
            charge_id=1234523,
            court_case=None,
            bond=None
        )

        ssvr = schema.StateSupervisionViolationResponse(
            supervision_violation_response_id=fake_svr_id,
            state_code='us_ca',
            person_id=fake_person_id,
            revocation_type=StateSupervisionViolationResponseRevocationType.REINCARCERATION,
            supervision_violation_id=fake_violation_id
        )

        state_agent = database_test_utils.generate_test_assessment_agent()

        ssvr.decision_agents = [state_agent]

        violation_report = schema.StateSupervisionViolationResponse(
            supervision_violation_response_id=99999,
            response_type=StateSupervisionViolationResponseType.VIOLATION_REPORT,
            is_draft=False,
            response_date=date(2017, 1, 1),
            person_id=fake_person_id
        )

        supervision_violation_type = schema.StateSupervisionViolationTypeEntry(
            person_id=fake_person_id,
            state_code='US_MO',
            violation_type=StateSupervisionViolationType.FELONY
        )

        supervision_violation = schema.StateSupervisionViolation(
            supervision_violation_id=fake_violation_id,
            state_code='US_MO',
            person_id=fake_person_id,
            supervision_violation_responses=[violation_report, ssvr],
            supervision_violation_types=[supervision_violation_type]
        )

        violation_report.supervision_violation_id = supervision_violation.supervision_violation_id

        # This incarceration period was due to a probation revocation
        revocation_reincarceration = schema.StateIncarcerationPeriod(
            incarceration_period_id=3333,
            incarceration_type=StateIncarcerationType.STATE_PRISON,
            status=StateIncarcerationPeriodStatus.IN_CUSTODY,
            state_code='US_MO',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.PROBATION_REVOCATION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.CONDITIONAL_RELEASE,
            admission_date=date(2017, 1, 4),
            person_id=fake_person_id,
            source_supervision_violation_response_id=fake_svr_id)

        assessment = schema.StateAssessment(
            assessment_id=298374,
            assessment_date=date(2015, 3, 19),
            assessment_type=StateAssessmentType.LSIR,
            person_id=fake_person_id
        )

        incarceration_periods_data = [
            normalized_database_base_dict(initial_incarceration),
            normalized_database_base_dict(first_reincarceration),
            normalized_database_base_dict(revocation_reincarceration)
        ]

        supervision_periods_data = [
            normalized_database_base_dict(supervision_period)
        ]

        supervision_violation_type_data = [
            normalized_database_base_dict(supervision_violation_type)
        ]

        supervision_violation_response_data = [
            normalized_database_base_dict(ssvr),
            normalized_database_base_dict(violation_report)
        ]

        supervision_violation_data = [
            normalized_database_base_dict(supervision_violation)
        ]

        supervision_sentences_data = [
            normalized_database_base_dict(supervision_sentence)
        ]

        incarceration_sentences_data = [
            normalized_database_base_dict(incarceration_sentence)
        ]

        charge_data = [
            normalized_database_base_dict(charge)
        ]

        assessment_data = [
            normalized_database_base_dict(assessment)
        ]

        data_dict = {
            schema.StatePerson.__tablename__: persons_data,
            schema.StateIncarcerationPeriod.__tablename__: incarceration_periods_data,
            schema.StateSupervisionViolationResponse.__tablename__: supervision_violation_response_data,
            schema.StateSupervisionViolation.__tablename__: supervision_violation_data,
            schema.StateSupervisionViolationTypeEntry.__tablename__: supervision_violation_type_data,
            schema.StateSupervisionPeriod.__tablename__: supervision_periods_data,
            schema.StateSupervisionSentence.__tablename__: supervision_sentences_data,
            schema.StateIncarcerationSentence.__tablename__: incarceration_sentences_data,
            schema.StateCharge.__tablename__: charge_data,
            schema.state_charge_supervision_sentence_association_table.name: [{}],
            schema.state_charge_incarceration_sentence_association_table.name: [{}],
            schema.state_incarceration_sentence_incarceration_period_association_table.name: [{}],
            schema.state_incarceration_sentence_supervision_period_association_table.name: [{}],
            schema.state_supervision_sentence_incarceration_period_association_table.name: [{}],
            schema.state_supervision_sentence_supervision_period_association_table.name:
            supervision_sentence_supervision_period_association,
            schema.StateAssessment.__tablename__: assessment_data
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

        # Get StateIncarcerationPeriods
        incarceration_periods = (test_pipeline
                                 | 'Load IncarcerationPeriods' >>
                                 extractor_utils.BuildRootEntity(
                                     dataset=None,
                                     data_dict=data_dict,
                                     root_schema_class=
                                     schema.StateIncarcerationPeriod,
                                     root_entity_class=
                                     entities.StateIncarcerationPeriod,
                                     unifying_id_field='person_id',
                                     build_related_entities=True))

        # Get StateSupervisionViolations
        supervision_violations = \
            (test_pipeline
             | 'Load SupervisionViolations' >>
             extractor_utils.BuildRootEntity(
                 dataset=None,
                 data_dict=data_dict,
                 root_schema_class=schema.StateSupervisionViolation,
                 root_entity_class=entities.StateSupervisionViolation,
                 unifying_id_field='person_id',
                 build_related_entities=True
             ))

        # Get StateSupervisionViolationResponses
        supervision_violation_responses = \
            (test_pipeline
             | 'Load SupervisionViolationResponses' >>
             extractor_utils.BuildRootEntity(
                 dataset=None,
                 data_dict=data_dict,
                 root_schema_class=schema.StateSupervisionViolationResponse,
                 root_entity_class=entities.StateSupervisionViolationResponse,
                 unifying_id_field='person_id',
                 build_related_entities=True
             ))

        # Get StateSupervisionSentences
        supervision_sentences = (test_pipeline
                                 | 'Load SupervisionSentences' >>
                                 extractor_utils.BuildRootEntity(
                                     dataset=None,
                                     data_dict=data_dict,
                                     root_schema_class=
                                     schema.StateSupervisionSentence,
                                     root_entity_class=
                                     entities.StateSupervisionSentence,
                                     unifying_id_field='person_id',
                                     build_related_entities=True))

        # Get StateIncarcerationSentences
        incarceration_sentences = (test_pipeline
                                   | 'Load IncarcerationSentences' >>
                                   extractor_utils.BuildRootEntity(
                                       dataset=None,
                                       data_dict=data_dict,
                                       root_schema_class=schema.StateIncarcerationSentence,
                                       root_entity_class=entities.StateIncarcerationSentence,
                                       unifying_id_field='person_id',
                                       build_related_entities=True))

        # Get StateSupervisionPeriods
        supervision_periods = (test_pipeline
                               | 'Load SupervisionPeriods' >>
                               extractor_utils.BuildRootEntity(
                                   dataset=None,
                                   data_dict=data_dict,
                                   root_schema_class=
                                   schema.StateSupervisionPeriod,
                                   root_entity_class=
                                   entities.StateSupervisionPeriod,
                                   unifying_id_field='person_id',
                                   build_related_entities=False))

        # Get StateAssessments
        assessments = (test_pipeline
                       | 'Load Assessments' >>
                       extractor_utils.BuildRootEntity(
                           dataset=None,
                           data_dict=data_dict,
                           root_schema_class=
                           schema.StateAssessment,
                           root_entity_class=
                           entities.StateAssessment,
                           unifying_id_field='person_id',
                           build_related_entities=False))

        # Group StateSupervisionViolationResponses and StateSupervisionViolations by person_id
        supervision_violations_and_responses = (
            {'violations': supervision_violations,
             'violation_responses': supervision_violation_responses
             } | 'Group StateSupervisionViolationResponses to StateSupervisionViolations' >>
            beam.CoGroupByKey()
        )

        # Set the fully hydrated StateSupervisionViolation entities on the corresponding
        # StateSupervisionViolationResponses
        violation_responses_with_hydrated_violations = (
            supervision_violations_and_responses
            | 'Set hydrated StateSupervisionViolations on the StateSupervisionViolationResponses' >>
            beam.ParDo(pipeline.SetViolationOnViolationsResponse()))

        # Group StateIncarcerationPeriods and StateSupervisionViolationResponses by person_id
        incarceration_periods_and_violation_responses = (
            {'incarceration_periods': incarceration_periods,
             'violation_responses': violation_responses_with_hydrated_violations}
            | 'Group StateIncarcerationPeriods to StateSupervisionViolationResponses' >>
            beam.CoGroupByKey()
        )

        # Set the fully hydrated StateSupervisionViolationResponse entities on
        # the corresponding StateIncarcerationPeriods
        incarceration_periods_with_source_violations = (
            incarceration_periods_and_violation_responses
            | 'Set hydrated StateSupervisionViolationResponses on the StateIncarcerationPeriods' >>
            beam.ParDo(pipeline.SetViolationResponseOnIncarcerationPeriod()))

        # Group each StatePerson with their StateIncarcerationPeriods and
        # StateSupervisionSentences
        person_periods_and_sentences = (
            {'person': persons,
             'assessments': assessments,
             'supervision_periods': supervision_periods,
             'incarceration_periods': incarceration_periods_with_source_violations,
             'supervision_sentences': supervision_sentences,
             'incarceration_sentences': incarceration_sentences,
             'violation_responses': violation_responses_with_hydrated_violations
             }
            | 'Group StatePerson to StateIncarcerationPeriods and StateSupervisionPeriods' >>
            beam.CoGroupByKey()
        )

        ssvr_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'ASSAGENT1234',
            'district_external_id': '4',
            'supervision_violation_response_id': fake_svr_id
        }

        ssvr_to_agent_associations = (
            test_pipeline | 'Create SSVR to Agent table' >> beam.Create([ssvr_to_agent_map])
        )

        ssvr_agent_associations_as_kv = (
            ssvr_to_agent_associations | 'Convert SSVR to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(), 'supervision_violation_response_id')
        )

        supervision_period_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_period_id': supervision_period.supervision_period_id
        }

        supervision_period_to_agent_associations = (
            test_pipeline | 'Create SupervisionPeriod to Agent table' >>
            beam.Create([supervision_period_to_agent_map])
        )

        supervision_periods_to_agent_associations_as_kv = (
            supervision_period_to_agent_associations |
            'Convert SupervisionPeriod to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(), 'supervision_period_id')
        )

        identifier_options = {
            'state_code': 'ALL'
        }

        # Identify SupervisionTimeBuckets from the StatePerson's
        # StateSupervisionSentences and StateIncarcerationPeriods
        person_time_buckets = (
            person_periods_and_sentences
            | beam.ParDo(
                pipeline.ClassifySupervisionTimeBuckets(),
                AsDict(ssvr_agent_associations_as_kv),
                AsDict(supervision_periods_to_agent_associations_as_kv),
                **identifier_options))

        # Get pipeline job details for accessing job_id
        all_pipeline_options = PipelineOptions().get_all_options()

        # Add timestamp for local jobs
        job_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S.%f')
        all_pipeline_options['job_timestamp'] = job_timestamp


        # Get supervision metrics
        supervision_metrics = (person_time_buckets
                               | 'Get Supervision Metrics' >>
                               pipeline.GetSupervisionMetrics(
                                   pipeline_options=all_pipeline_options,
                                   inclusions=ALL_INCLUSIONS_DICT,
                                   metric_type='ALL',
                                   calculation_month_limit=-1))

        assert_that(supervision_metrics, AssertMatchers.validate_pipeline_test(
            {SupervisionMetricType.POPULATION,
             SupervisionMetricType.REVOCATION,
             SupervisionMetricType.REVOCATION_ANALYSIS,
             SupervisionMetricType.REVOCATION_VIOLATION_TYPE_ANALYSIS,
             SupervisionMetricType.ASSESSMENT_CHANGE}))

        test_pipeline.run()

    def testSupervisionPipeline_withTechnicalRevocations(self):
        fake_person_id = 562
        fake_svr_id = 5582552
        fake_violation_id = 4702488

        fake_person = schema.StatePerson(person_id=fake_person_id, gender=Gender.MALE, birthdate=date(1991, 8, 16),
                                         residency_status=ResidencyStatus.PERMANENT)

        persons_data = [normalized_database_base_dict(fake_person)]

        initial_supervision_period = schema.StateSupervisionPeriod(
            supervision_period_id=5876524,
            state_code='US_ND',
            county_code='US_ND_RAMSEY',
            start_date=date(2014, 10, 31),
            termination_date=date(2015, 4, 21),
            termination_reason=StateSupervisionPeriodTerminationReason.REVOCATION,
            supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
            person_id=fake_person_id
        )

        initial_supervision_sentence = schema.StateSupervisionSentence(supervision_sentence_id=105109,
                                                                       state_code='US_ND',
                                                                       supervision_periods=[initial_supervision_period],
                                                                       projected_completion_date=date(2016, 10, 31),
                                                                       person_id=fake_person_id
                                                                       )

        # violation of the first probation
        ssvr_1 = schema.StateSupervisionViolationResponse(
            supervision_violation_response_id=5578679,
            state_code='US_ND',
            response_type=StateSupervisionViolationResponseType.PERMANENT_DECISION,
            person_id=fake_person_id,
            revocation_type=StateSupervisionViolationResponseRevocationType.REINCARCERATION,
            supervision_violation_id=4698615
        )
        state_agent = database_test_utils.generate_test_assessment_agent()
        ssvr_1.decision_agents = [state_agent]
        supervision_violation_type_1 = schema.StateSupervisionViolationTypeEntry(
            person_id=fake_person_id,
            state_code='US_ND',
            violation_type=StateSupervisionViolationType.FELONY,
            supervision_violation_id=4698615
        )
        supervision_violation_1 = schema.StateSupervisionViolation(
            supervision_violation_id=4698615,
            state_code='US_ND',
            person_id=fake_person_id,
            supervision_violation_responses=[ssvr_1],
            supervision_violation_types=[supervision_violation_type_1]
        )
        initial_incarceration = schema.StateIncarcerationPeriod(
            external_id='11111',
            incarceration_period_id=2499739,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='US_ND',
            county_code=None,
            facility='NDSP',
            facility_security_level=None,
            admission_reason=StateIncarcerationPeriodAdmissionReason.PROBATION_REVOCATION,
            projected_release_reason=None,
            admission_date=date(2015, 4, 28),
            release_date=date(2016, 11, 22),
            release_reason=StateIncarcerationPeriodReleaseReason.CONDITIONAL_RELEASE,
            person_id=fake_person_id,
            source_supervision_violation_response_id=ssvr_1.supervision_violation_response_id
        )

        # This probation supervision period ended in a revocation
        supervision_period = schema.StateSupervisionPeriod(
            supervision_period_id=5887825,
            state_code='US_ND',
            county_code='US_ND_BURLEIGH',
            start_date=date(2016, 11, 22),
            termination_date=date(2017, 2, 6),
            termination_reason=StateSupervisionPeriodTerminationReason.REVOCATION,
            supervision_type=StateSupervisionPeriodSupervisionType.PAROLE,
            person_id=fake_person_id
        )

        supervision_sentence = schema.StateSupervisionSentence(supervision_sentence_id=116412, state_code='US_ND',
                                                               supervision_periods=[supervision_period],
                                                               projected_completion_date=date(2017, 7, 24),
                                                               person_id=fake_person_id)

        supervision_sentence_supervision_period_association = [
            {'supervision_period_id': 5876524, 'supervision_sentence_id': 105109},
            {'supervision_period_id': 5887825, 'supervision_sentence_id': 116412},
        ]

        # This incarceration period was due to a parole revocation
        revocation_reincarceration = schema.StateIncarcerationPeriod(
            external_id='3333',
            incarceration_period_id=2508394,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='US_ND',
            county_code=None,
            facility='NDSP',
            facility_security_level=None,
            admission_reason=StateIncarcerationPeriodAdmissionReason.PAROLE_REVOCATION,
            projected_release_reason=None,
            admission_date=date(2017, 1, 31),
            release_date=date(2017, 3, 3),
            release_reason=StateIncarcerationPeriodReleaseReason.TRANSFER,
            person_id=fake_person_id,
            source_supervision_violation_response_id=fake_svr_id
        )

        # violation on parole
        ssvr_2 = schema.StateSupervisionViolationResponse(
            supervision_violation_response_id=fake_svr_id,
            state_code='US_ND',
            response_type=StateSupervisionViolationResponseType.PERMANENT_DECISION,
            person_id=fake_person_id,
            revocation_type=StateSupervisionViolationResponseRevocationType.REINCARCERATION,
            supervision_violation_id=fake_violation_id
        )
        ssvr_2.decision_agents = [state_agent]

        violation_report = schema.StateSupervisionViolationResponse(
            supervision_violation_response_id=99999,
            response_type=StateSupervisionViolationResponseType.VIOLATION_REPORT,
            is_draft=False,
            response_date=date(2017, 1, 1),
            person_id=fake_person_id,
            supervision_violation_id=fake_violation_id
        )

        supervision_violation_type_2 = schema.StateSupervisionViolationTypeEntry(
            person_id=fake_person_id,
            state_code='US_ND',
            violation_type=StateSupervisionViolationType.TECHNICAL,

            supervision_violation_id=fake_violation_id
        )

        supervision_violation_condition = schema.StateSupervisionViolatedConditionEntry(
            person_id=fake_person_id,
            state_code='US_ND',
            condition='DRG',
            supervision_violation_id=fake_violation_id
        )

        supervision_violation = schema.StateSupervisionViolation(
            supervision_violation_id=fake_violation_id,
            state_code='US_ND',
            person_id=fake_person_id,
            supervision_violation_responses=[violation_report, ssvr_2],
            supervision_violation_types=[supervision_violation_type_2],
            supervision_violated_conditions=[supervision_violation_condition]
        )

        assessment = schema.StateAssessment(assessment_id=298374, assessment_date=date(2016, 12, 20),
                                            assessment_score=32, assessment_type=StateAssessmentType.LSIR,
                                            person_id=fake_person_id)

        incarceration_sentence = schema.StateIncarcerationSentence(
            incarceration_sentence_id=123,
            state_code='US_ND',
            person_id=fake_person_id,
            incarceration_periods=[initial_incarceration, revocation_reincarceration]
        )

        incarceration_periods_data = [
            normalized_database_base_dict(initial_incarceration),
            normalized_database_base_dict(revocation_reincarceration)
        ]
        supervision_periods_data = [
            normalized_database_base_dict(initial_supervision_period),
            normalized_database_base_dict(supervision_period)
        ]
        supervision_violation_type_data = [
            normalized_database_base_dict(supervision_violation_type_1),
            normalized_database_base_dict(supervision_violation_type_2)
        ]

        supervision_violation_condition_entry_data = [
            normalized_database_base_dict(supervision_violation_condition)
        ]

        supervision_violation_response_data = [
            normalized_database_base_dict(violation_report),
            normalized_database_base_dict(ssvr_1),
            normalized_database_base_dict(ssvr_2)
        ]
        supervision_violation_data = [
            normalized_database_base_dict(supervision_violation_1),
            normalized_database_base_dict(supervision_violation)
        ]
        supervision_sentences_data = [
            normalized_database_base_dict(initial_supervision_sentence),
            normalized_database_base_dict(supervision_sentence)
        ]

        incarceration_sentences_data = [
            normalized_database_base_dict(incarceration_sentence)
        ]

        assessment_data = [
            normalized_database_base_dict(assessment)
        ]

        data_dict = {
            schema.StatePerson.__tablename__: persons_data,
            schema.StateIncarcerationPeriod.__tablename__: incarceration_periods_data,
            schema.StateSupervisionViolationResponse.__tablename__: supervision_violation_response_data,
            schema.StateSupervisionViolation.__tablename__: supervision_violation_data,
            schema.StateSupervisionPeriod.__tablename__: supervision_periods_data,
            schema.StateSupervisionSentence.__tablename__: supervision_sentences_data,
            schema.StateIncarcerationSentence.__tablename__: incarceration_sentences_data,
            schema.StateSupervisionViolationTypeEntry.__tablename__: supervision_violation_type_data,
            schema.StateSupervisionViolatedConditionEntry.__tablename__: supervision_violation_condition_entry_data,
            schema.state_charge_supervision_sentence_association_table.name: [{}],
            schema.state_charge_incarceration_sentence_association_table.name: [{}],
            schema.state_incarceration_sentence_incarceration_period_association_table.name: [{}],
            schema.state_incarceration_sentence_supervision_period_association_table.name: [{}],
            schema.state_supervision_sentence_incarceration_period_association_table.name: [{}],
            schema.state_supervision_sentence_supervision_period_association_table.name:
            supervision_sentence_supervision_period_association,
            schema.StateAssessment.__tablename__: assessment_data
        }

        test_pipeline = TestPipeline()

        # Get StatePersons
        persons = test_pipeline | 'Load Persons' >> extractor_utils.BuildRootEntity(
            dataset=None,
            data_dict=data_dict,
            root_schema_class=schema.StatePerson,
            root_entity_class=entities.StatePerson,
            unifying_id_field='person_id',
            build_related_entities=True)

        # Get StateIncarcerationPeriods
        incarceration_periods = test_pipeline | 'Load IncarcerationPeriods' >> extractor_utils.BuildRootEntity(
            dataset=None,
            data_dict=data_dict,
            root_schema_class=schema.StateIncarcerationPeriod,
            root_entity_class=entities.StateIncarcerationPeriod,
            unifying_id_field='person_id',
            build_related_entities=True)

        # Get StateSupervisionViolations
        supervision_violations = test_pipeline | 'Load SupervisionViolations' >> extractor_utils.BuildRootEntity(
            dataset=None,
            data_dict=data_dict,
            root_schema_class=schema.StateSupervisionViolation,
            root_entity_class=entities.StateSupervisionViolation,
            unifying_id_field='person_id',
            build_related_entities=True)

        # Get StateSupervisionViolationResponses
        supervision_violation_responses = (test_pipeline | 'Load SupervisionViolationResponses' >>
                                           extractor_utils.BuildRootEntity(
                                               dataset=None,
                                               data_dict=data_dict,
                                               root_schema_class=schema.StateSupervisionViolationResponse,
                                               root_entity_class=entities.StateSupervisionViolationResponse,
                                               unifying_id_field='person_id',
                                               build_related_entities=True))

        # Get StateSupervisionSentences
        supervision_sentences = (test_pipeline | 'Load SupervisionSentences' >>
                                 extractor_utils.BuildRootEntity(
                                     dataset=None,
                                     data_dict=data_dict,
                                     root_schema_class=schema.StateSupervisionSentence,
                                     root_entity_class=entities.StateSupervisionSentence,
                                     unifying_id_field='person_id',
                                     build_related_entities=True))

        # Get StateIncarcerationSentences
        incarceration_sentences = (test_pipeline | 'Load IncarcerationSentences' >>
                                   extractor_utils.BuildRootEntity(
                                       dataset=None,
                                       data_dict=data_dict,
                                       root_schema_class=schema.StateIncarcerationSentence,
                                       root_entity_class=entities.StateIncarcerationSentence,
                                       unifying_id_field='person_id',
                                       build_related_entities=True))

        # Get StateSupervisionPeriods
        supervision_periods = (test_pipeline | 'Load SupervisionPeriods' >>
                               extractor_utils.BuildRootEntity(
                                   dataset=None,
                                   data_dict=data_dict,
                                   root_schema_class=
                                   schema.StateSupervisionPeriod,
                                   root_entity_class=
                                   entities.StateSupervisionPeriod,
                                   unifying_id_field='person_id',
                                   build_related_entities=False))

        # Get StateAssessments
        assessments = test_pipeline | 'Load Assessments' >> extractor_utils.BuildRootEntity(
            dataset=None,
            data_dict=data_dict,
            root_schema_class=schema.StateAssessment,
            root_entity_class=entities.StateAssessment,
            unifying_id_field='person_id',
            build_related_entities=False)

        # Group StateSupervisionViolationResponses and
        # StateSupervisionViolations by person_id
        supervision_violations_and_responses = (
            {'violations': supervision_violations,
             'violation_responses': supervision_violation_responses
             } | 'Group StateSupervisionViolationResponses to StateSupervisionViolations' >> beam.CoGroupByKey()
        )

        # Set the fully hydrated StateSupervisionViolation entities on
        # the corresponding StateSupervisionViolationResponses
        violation_responses_with_hydrated_violations = (
            supervision_violations_and_responses
            | 'Set hydrated StateSupervisionViolations on the StateSupervisionViolationResponses' >>
            beam.ParDo(pipeline.SetViolationOnViolationsResponse()))

        # Group StateIncarcerationPeriods and StateSupervisionViolationResponses
        # by person_id
        incarceration_periods_and_violation_responses = (
            {'incarceration_periods': incarceration_periods,
             'violation_responses': violation_responses_with_hydrated_violations}
            | 'Group StateIncarcerationPeriods to StateSupervisionViolationResponses' >>
            beam.CoGroupByKey()
        )

        # Set the fully hydrated StateSupervisionViolationResponse entities on
        # the corresponding StateIncarcerationPeriods
        incarceration_periods_with_source_violations = (
            incarceration_periods_and_violation_responses
            | 'Set hydrated StateSupervisionViolationResponses on '
            'the StateIncarcerationPeriods' >>
            beam.ParDo(pipeline.SetViolationResponseOnIncarcerationPeriod()))

        # Group each StatePerson with their StateIncarcerationPeriods and
        # StateSupervisionSentences
        person_periods_and_sentences = (
            {'person': persons,
             'assessments': assessments,
             'incarceration_periods': incarceration_periods_with_source_violations,
             'supervision_sentences': supervision_sentences,
             'incarceration_sentences': incarceration_sentences,
             'supervision_periods': supervision_periods,
             'violation_responses': violation_responses_with_hydrated_violations
             }
            | 'Group StatePerson to StateIncarcerationPeriods'
              ' and StateSupervisionPeriods' >>
            beam.CoGroupByKey()
        )

        ssvr_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'ASSAGENT1234',
            'district_external_id': '4',
            'supervision_violation_response_id': fake_svr_id
        }

        ssvr_to_agent_associations = (
            test_pipeline
            | 'Create SSVR to Agent table' >>
            beam.Create([ssvr_to_agent_map])
        )

        ssvr_agent_associations_as_kv = (
            ssvr_to_agent_associations |
            'Convert SSVR to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_violation_response_id')
        )

        supervision_period_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_period_id':
                supervision_period.supervision_period_id
        }

        supervision_period_to_agent_associations = (
            test_pipeline
            | 'Create SupervisionPeriod to Agent table' >>
            beam.Create([supervision_period_to_agent_map])
        )

        supervision_periods_to_agent_associations_as_kv = (
            supervision_period_to_agent_associations |
            'Convert SupervisionPeriod to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_period_id')
        )

        identifier_options = {
            'state_code': 'ALL'
        }

        # Identify SupervisionTimeBuckets from the StatePerson's
        # StateSupervisionSentences and StateIncarcerationPeriods
        person_time_buckets = (
            person_periods_and_sentences
            | beam.ParDo(
                pipeline.ClassifySupervisionTimeBuckets(),
                AsDict(
                    ssvr_agent_associations_as_kv),
                AsDict(
                    supervision_periods_to_agent_associations_as_kv),
                **identifier_options))

        # Get pipeline job details for accessing job_id
        all_pipeline_options = PipelineOptions().get_all_options()

        # Add timestamp for local jobs
        job_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S.%f')
        all_pipeline_options['job_timestamp'] = job_timestamp

        # Get supervision metrics
        supervision_metrics = (person_time_buckets
                               | 'Get Supervision Metrics' >>
                               pipeline.GetSupervisionMetrics(
                                   pipeline_options=all_pipeline_options,
                                   inclusions=ALL_INCLUSIONS_DICT,
                                   metric_type='ALL',
                                   calculation_month_limit=-1))

        assert_that(supervision_metrics, AssertMatchers.validate_pipeline_test(
            {SupervisionMetricType.POPULATION, SupervisionMetricType.SUCCESS, SupervisionMetricType.REVOCATION,
             SupervisionMetricType.REVOCATION_ANALYSIS, SupervisionMetricType.REVOCATION_VIOLATION_TYPE_ANALYSIS}),
                    "Assert all expected metric types are produced.")
        assert_that(supervision_metrics, AssertMatchers.assert_source_violation_type_set(ViolationType.TECHNICAL),
                    "Assert source violation TECHNICAL type is set")

        assert_that(supervision_metrics, AssertMatchers.assert_source_violation_type_set(ViolationType.FELONY),
                    "Assert source violation FELONY type is set")

        test_pipeline.run()

    def testSupervisionPipelineNoSupervision(self):
        """Tests the supervision pipeline when a person doesn't have any supervision periods."""
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

        initial_incarceration_1 = schema.StateIncarcerationPeriod(
            incarceration_period_id=1111,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            external_id='ip1',
            state_code='US_ND',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.NEW_ADMISSION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.CONDITIONAL_RELEASE,
            admission_date=date(2008, 11, 20),
            release_date=date(2010, 12, 4),
            release_reason=StateIncarcerationPeriodReleaseReason.SENTENCE_SERVED,
            person_id=fake_person_id_1)

        supervision_period__1 = schema.StateSupervisionPeriod(
            supervision_period_id=1111,
            state_code='US_ND',
            external_id='sp1',
            county_code='124',
            start_date=date(2016, 3, 14),
            termination_date=date(2016, 12, 29),
            supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
            person_id=fake_person_id_1
        )

        supervision_sentence = schema.StateSupervisionSentence(
            supervision_sentence_id=1122,
            state_code='US_ND',
            external_id='ss1',
            status=StateSentenceStatus.COMPLETED,
            supervision_type=StateSupervisionType.PROBATION,
            supervision_periods=[supervision_period__1],
            projected_completion_date=date(2017, 12, 31),
            completion_date=date(2016, 12, 29),
            person_id=fake_person_id_1
        )

        incarceration_sentence = schema.StateIncarcerationSentence(
            incarceration_sentence_id=123,
            state_code='US_ND',
            incarceration_periods=[
                initial_incarceration_1
            ],
            person_id=fake_person_id_1
        )

        supervision_sentence_supervision_period_association = [
            {
                'supervision_period_id': 1111,
                'supervision_sentence_id': 1122,
            }
        ]

        charge = database_test_utils.generate_test_charge(
            person_id=fake_person_id_1,
            charge_id=1234523,
            court_case=None,
            bond=None
        )

        supervision_violation_response = database_test_utils.generate_test_supervision_violation_response(
            fake_person_id_2)

        state_agent = database_test_utils.generate_test_assessment_agent()

        supervision_violation_response.decision_agents = [state_agent]

        supervision_violation = database_test_utils.generate_test_supervision_violation(
            fake_person_id_2, [supervision_violation_response])

        supervision_violation_response.supervision_violation_id = supervision_violation.supervision_violation_id

        supervision_violation_response_data = [
            normalized_database_base_dict(supervision_violation_response)
        ]

        supervision_violation_data = [
            normalized_database_base_dict(supervision_violation)
        ]

        supervision_sentences_data = [
            normalized_database_base_dict(supervision_sentence)
        ]

        incarceration_sentences_data = [
            normalized_database_base_dict(incarceration_sentence)
        ]

        charge_data = [
            normalized_database_base_dict(charge)
        ]

        first_reincarceration_2 = schema.StateIncarcerationPeriod(
            incarceration_period_id=5555,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='US_ND',
            external_id='ip5',
            county_code='124',
            facility='San Quentin',
            facility_security_level=StateIncarcerationFacilitySecurityLevel.MAXIMUM,
            admission_reason=StateIncarcerationPeriodAdmissionReason.PAROLE_REVOCATION,
            projected_release_reason=StateIncarcerationPeriodReleaseReason.CONDITIONAL_RELEASE,
            admission_date=date(2011, 4, 5),
            release_date=date(2014, 1, 4),
            release_reason=StateIncarcerationPeriodReleaseReason.SENTENCE_SERVED,
            source_supervision_violation_response_id=supervision_violation_response.supervision_violation_response_id,
            person_id=fake_person_id_2)

        subsequent_reincarceration_2 = \
            schema.StateIncarcerationPeriod(
                incarceration_period_id=6666,
                status=StateIncarcerationPeriodStatus.IN_CUSTODY,
                state_code='US_ND',
                external_id='ip6',
                county_code='124',
                facility='San Quentin',
                facility_security_level=StateIncarcerationFacilitySecurityLevel.MAXIMUM,
                admission_reason=StateIncarcerationPeriodAdmissionReason.NEW_ADMISSION,
                projected_release_reason=StateIncarcerationPeriodReleaseReason.CONDITIONAL_RELEASE,
                admission_date=date(2018, 3, 9),
                person_id=fake_person_id_2)

        assessment = schema.StateAssessment(
            assessment_id=298374,
            assessment_date=date(2015, 3, 19),
            assessment_type=StateAssessmentType.LSIR,
            person_id=fake_person_id_1
        )

        incarceration_periods_data = [
            normalized_database_base_dict(initial_incarceration_1),
            normalized_database_base_dict(first_reincarceration_2),
            normalized_database_base_dict(subsequent_reincarceration_2)
        ]

        supervision_periods_data = [
            normalized_database_base_dict(supervision_period__1)
        ]

        assessment_data = [
            normalized_database_base_dict(assessment)
        ]

        data_dict = {
            schema.StatePerson.__tablename__: persons_data,
            schema.StateIncarcerationPeriod.__tablename__: incarceration_periods_data,
            schema.StateSupervisionViolationResponse.__tablename__: supervision_violation_response_data,
            schema.StateSupervisionViolation.__tablename__: supervision_violation_data,
            schema.StateSupervisionPeriod.__tablename__: supervision_periods_data,
            schema.StateSupervisionSentence.__tablename__: supervision_sentences_data,
            schema.StateIncarcerationSentence.__tablename__: incarceration_sentences_data,
            schema.StateCharge.__tablename__: charge_data,
            schema.state_charge_supervision_sentence_association_table.name: [{}],
            schema.state_charge_incarceration_sentence_association_table.name: [{}],
            schema.state_incarceration_sentence_incarceration_period_association_table.name: [{}],
            schema.state_incarceration_sentence_supervision_period_association_table.name: [{}],
            schema.state_supervision_sentence_incarceration_period_association_table.name: [{}],
            schema.state_supervision_sentence_supervision_period_association_table.name:
                supervision_sentence_supervision_period_association,
            schema.StateAssessment.__tablename__: assessment_data
        }

        test_pipeline = TestPipeline()

        # Get StatePersons
        persons = test_pipeline | 'Load Persons' >> extractor_utils.BuildRootEntity(
            dataset=None,
            data_dict=data_dict,
            root_schema_class=schema.StatePerson,
            root_entity_class=entities.StatePerson,
            unifying_id_field='person_id',
            build_related_entities=True)

        # Get StateIncarcerationPeriods
        incarceration_periods = test_pipeline | 'Load IncarcerationPeriods' >> extractor_utils.BuildRootEntity(
            dataset=None,
            data_dict=data_dict,
            root_schema_class=schema.StateIncarcerationPeriod,
            root_entity_class=entities.StateIncarcerationPeriod,
            unifying_id_field='person_id',
            build_related_entities=True)

        # Get StateSupervisionViolations
        supervision_violations = test_pipeline | 'Load SupervisionViolations' >> extractor_utils.BuildRootEntity(
            dataset=None,
            data_dict=data_dict,
            root_schema_class=schema.StateSupervisionViolation,
            root_entity_class=entities.StateSupervisionViolation,
            unifying_id_field='person_id',
            build_related_entities=True)

        # Get StateSupervisionViolationResponses
        supervision_violation_responses = (test_pipeline | 'Load SupervisionViolationResponses' >>
                                           extractor_utils.BuildRootEntity(
                                               dataset=None,
                                               data_dict=data_dict,
                                               root_schema_class=schema.StateSupervisionViolationResponse,
                                               root_entity_class=entities.StateSupervisionViolationResponse,
                                               unifying_id_field='person_id',
                                               build_related_entities=True))

        # Get StateSupervisionSentences
        supervision_sentences = (test_pipeline | 'Load SupervisionSentences' >>
                                 extractor_utils.BuildRootEntity(
                                     dataset=None,
                                     data_dict=data_dict,
                                     root_schema_class=schema.StateSupervisionSentence,
                                     root_entity_class=entities.StateSupervisionSentence,
                                     unifying_id_field='person_id',
                                     build_related_entities=True))

        # Get StateIncarcerationSentences
        incarceration_sentences = (test_pipeline | 'Load IncarcerationSentences' >>
                                   extractor_utils.BuildRootEntity(
                                       dataset=None,
                                       data_dict=data_dict,
                                       root_schema_class=schema.StateIncarcerationSentence,
                                       root_entity_class=entities.StateIncarcerationSentence,
                                       unifying_id_field='person_id',
                                       build_related_entities=True))

        # Get StateSupervisionPeriods
        supervision_periods = (test_pipeline | 'Load SupervisionPeriods' >>
                               extractor_utils.BuildRootEntity(
                                   dataset=None,
                                   data_dict=data_dict,
                                   root_schema_class=
                                   schema.StateSupervisionPeriod,
                                   root_entity_class=
                                   entities.StateSupervisionPeriod,
                                   unifying_id_field='person_id',
                                   build_related_entities=False))

        # Get StateAssessments
        assessments = test_pipeline | 'Load Assessments' >> extractor_utils.BuildRootEntity(
            dataset=None,
            data_dict=data_dict,
            root_schema_class=schema.StateAssessment,
            root_entity_class=entities.StateAssessment,
            unifying_id_field='person_id',
            build_related_entities=False)

        # Group StateSupervisionViolationResponses and
        # StateSupervisionViolations by person_id
        supervision_violations_and_responses = (
            {'violations': supervision_violations,
             'violation_responses': supervision_violation_responses
             } | 'Group StateSupervisionViolationResponses to StateSupervisionViolations' >> beam.CoGroupByKey()
        )

        # Set the fully hydrated StateSupervisionViolation entities on
        # the corresponding StateSupervisionViolationResponses
        violation_responses_with_hydrated_violations = (
            supervision_violations_and_responses
            | 'Set hydrated StateSupervisionViolations on the StateSupervisionViolationResponses' >>
            beam.ParDo(pipeline.SetViolationOnViolationsResponse()))

        # Group StateIncarcerationPeriods and StateSupervisionViolationResponses
        # by person_id
        incarceration_periods_and_violation_responses = (
            {'incarceration_periods': incarceration_periods,
             'violation_responses': violation_responses_with_hydrated_violations}
            | 'Group StateIncarcerationPeriods to StateSupervisionViolationResponses' >>
            beam.CoGroupByKey()
        )

        # Set the fully hydrated StateSupervisionViolationResponse entities on
        # the corresponding StateIncarcerationPeriods
        incarceration_periods_with_source_violations = (
            incarceration_periods_and_violation_responses
            | 'Set hydrated StateSupervisionViolationResponses on '
              'the StateIncarcerationPeriods' >>
            beam.ParDo(pipeline.SetViolationResponseOnIncarcerationPeriod()))

        # Group each StatePerson with their StateIncarcerationPeriods and
        # StateSupervisionSentences
        person_periods_and_sentences = (
            {'person': persons,
             'assessments': assessments,
             'incarceration_periods': incarceration_periods_with_source_violations,
             'supervision_sentences': supervision_sentences,
             'incarceration_sentences': incarceration_sentences,
             'supervision_periods': supervision_periods,
             'violation_responses': violation_responses_with_hydrated_violations
             }
            | 'Group StatePerson to StateIncarcerationPeriods'
              ' and StateSupervisionPeriods' >>
            beam.CoGroupByKey()
        )

        ssvr_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'ASSAGENT1234',
            'district_external_id': '4',
            'supervision_violation_response_id': supervision_violation_response.supervision_violation_response_id
        }

        ssvr_to_agent_associations = (
            test_pipeline
            | 'Create SSVR to Agent table' >>
            beam.Create([ssvr_to_agent_map])
        )

        ssvr_agent_associations_as_kv = (
            ssvr_to_agent_associations |
            'Convert SSVR to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_violation_response_id')
        )

        supervision_period_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_period_id': 9999999
        }

        supervision_period_to_agent_associations = (
            test_pipeline
            | 'Create SupervisionPeriod to Agent table' >>
            beam.Create([supervision_period_to_agent_map])
        )

        supervision_periods_to_agent_associations_as_kv = (
            supervision_period_to_agent_associations |
            'Convert SupervisionPeriod to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_period_id')
        )

        identifier_options = {
            'state_code': 'ALL'
        }

        # Identify SupervisionTimeBuckets from the StatePerson's
        # StateSupervisionSentences and StateIncarcerationPeriods
        person_time_buckets = (
            person_periods_and_sentences
            | beam.ParDo(
                pipeline.ClassifySupervisionTimeBuckets(),
                AsDict(ssvr_agent_associations_as_kv),
                AsDict(supervision_periods_to_agent_associations_as_kv),
                **identifier_options))

        # Get pipeline job details for accessing job_id
        all_pipeline_options = PipelineOptions().get_all_options()

        # Add timestamp for local jobs
        job_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S.%f')
        all_pipeline_options['job_timestamp'] = job_timestamp

        # Get supervision metrics
        supervision_metrics = (person_time_buckets
                               | 'Get Supervision Metrics' >>
                               pipeline.GetSupervisionMetrics(
                                   pipeline_options=all_pipeline_options,
                                   inclusions=ALL_INCLUSIONS_DICT,
                                   metric_type='ALL',
                                   calculation_month_limit=-1))

        assert_that(supervision_metrics, AssertMatchers.validate_pipeline_test(
            {SupervisionMetricType.POPULATION, SupervisionMetricType.SUCCESS, SupervisionMetricType.REVOCATION,
             SupervisionMetricType.REVOCATION_ANALYSIS}), "Assert all expected metric types are produced.")

        test_pipeline.run()


class TestClassifySupervisionTimeBuckets(unittest.TestCase):
    """Tests the ClassifySupervisionTimeBuckets DoFn in the pipeline."""

    def testClassifySupervisionTimeBuckets(self):
        """Tests the ClassifySupervisionTimeBuckets DoFn."""
        fake_person_id = 12345

        fake_person = StatePerson.new_with_defaults(
            person_id=fake_person_id, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        incarceration_period = StateIncarcerationPeriod.new_with_defaults(
            incarceration_period_id=1111,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='US_ND',
            admission_date=date(2008, 11, 20),
            admission_reason=StateIncarcerationPeriodAdmissionReason.NEW_ADMISSION,
            release_date=date(2010, 12, 4),
            release_reason=StateIncarcerationPeriodReleaseReason.SENTENCE_SERVED)

        supervision_period = schema.StateSupervisionPeriod(
            supervision_period_id=1111,
            state_code='US_ND',
            county_code='124',
            start_date=date(2015, 3, 14),
            termination_date=date(2015, 5, 29),
            termination_reason=StateSupervisionPeriodTerminationReason.DISCHARGE,
            supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
            supervision_level=StateSupervisionLevel.MEDIUM,
            supervision_level_raw_text='MEDM',
            person_id=fake_person_id
        )

        supervision_sentence = StateSupervisionSentence.new_with_defaults(
            supervision_sentence_id=111,
            external_id='ss1',
            status=StateSentenceStatus.COMPLETED,
            supervision_type=StateSupervisionType.PROBATION,
            start_date=date(2008, 1, 1),
            projected_completion_date=date(2015, 5, 30),
            completion_date=date(2015, 5, 29),
            supervision_periods=[supervision_period]
        )

        incarceration_sentence = StateIncarcerationSentence.new_with_defaults(
            incarceration_sentence_id=123,
            incarceration_periods=[incarceration_period]
        )

        assessment = StateAssessment.new_with_defaults(
            state_code='US_ND',
            assessment_type=StateAssessmentType.ORAS,
            assessment_score=33,
            assessment_date=date(2015, 3, 10)
        )

        person_periods = {'person': [fake_person],
                          'supervision_periods': [supervision_period],
                          'assessments': [assessment],
                          'incarceration_periods': [incarceration_period],
                          'incarceration_sentences': [incarceration_sentence],
                          'supervision_sentences': [supervision_sentence],
                          'violation_responses': []
                          }

        supervision_period_supervision_type = StateSupervisionPeriodSupervisionType.PROBATION
        supervision_time_buckets = [
            ProjectedSupervisionCompletionBucket(
                state_code=supervision_period.state_code,
                year=2015, month=5,
                supervision_type=supervision_period_supervision_type,
                case_type=StateSupervisionCaseType.GENERAL,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                successful_completion=True
            ),
            NonRevocationReturnSupervisionTimeBucket(
                state_code=supervision_period.state_code,
                year=2015, month=3,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                assessment_score=assessment.assessment_score,
                assessment_level=assessment.assessment_level,
                assessment_type=assessment.assessment_type,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.MEDIUM,
                supervision_level_raw_text='MEDM',
            ),
            NonRevocationReturnSupervisionTimeBucket(
                state_code=supervision_period.state_code,
                year=2015, month=4,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                assessment_score=assessment.assessment_score,
                assessment_level=assessment.assessment_level,
                assessment_type=assessment.assessment_type,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.MEDIUM,
                supervision_level_raw_text='MEDM',
            ),
            NonRevocationReturnSupervisionTimeBucket(
                state_code=supervision_period.state_code,
                year=2015, month=5,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                assessment_score=assessment.assessment_score,
                assessment_level=assessment.assessment_level,
                assessment_type=assessment.assessment_type,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.MEDIUM,
                supervision_level_raw_text='MEDM',
            ),
            SupervisionTerminationBucket(
                state_code=supervision_period.state_code,
                year=supervision_period.termination_date.year,
                month=supervision_period.termination_date.month,
                supervision_type=supervision_period_supervision_type,
                case_type=StateSupervisionCaseType.GENERAL,
                termination_reason=supervision_period.termination_reason,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10'
            )
        ]

        correct_output = [
            (fake_person, supervision_time_buckets)]

        test_pipeline = TestPipeline()

        ssvr_to_agent_map = {
            'agent_id': 000,
            'agent_external_id': 'XXX',
            'district_external_id': 'X',
            'supervision_violation_response_id': 999
        }

        ssvr_to_agent_associations = (
            test_pipeline
            | 'Create SSVR to Agent table' >>
            beam.Create([ssvr_to_agent_map])
        )

        ssvr_agent_associations_as_kv = (
            ssvr_to_agent_associations |
            'Convert SSVR to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_violation_response_id')
        )

        supervision_period_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_period_id':
                supervision_period.supervision_period_id
        }

        supervision_period_to_agent_associations = (
            test_pipeline
            | 'Create SupervisionPeriod to Agent table' >>
            beam.Create([supervision_period_to_agent_map])
        )

        supervision_periods_to_agent_associations_as_kv = (
            supervision_period_to_agent_associations |
            'Convert SupervisionPeriod to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_period_id')
        )

        output = (test_pipeline
                  | beam.Create([(fake_person_id,
                                  person_periods)])
                  | 'Identify Supervision Time Buckets' >>
                  beam.ParDo(
                      pipeline.ClassifySupervisionTimeBuckets(),
                      AsDict(ssvr_agent_associations_as_kv),
                      AsDict(supervision_periods_to_agent_associations_as_kv))
                  )

        assert_that(output, equal_to(correct_output))

        test_pipeline.run()

    def testClassifySupervisionTimeBucketsRevocation(self):
        """Tests the ClassifySupervisionTimeBuckets DoFn when there is an instance of revocation."""
        fake_person_id = 12345

        fake_person = StatePerson.new_with_defaults(
            person_id=fake_person_id, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        supervision_period = schema.StateSupervisionPeriod(
            supervision_period_id=1111,
            state_code='US_MO',
            county_code='124',
            start_date=date(2015, 3, 14),
            termination_date=date(2015, 5, 29),
            supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
            supervision_level=StateSupervisionLevel.HIGH,
            supervision_level_raw_text='H',
            person_id=fake_person_id
        )

        source_supervision_violation_response = StateSupervisionViolationResponse.new_with_defaults(
            state_code='US_MO',
            supervision_violation_response_id=999
        )

        violation_report = StateSupervisionViolationResponse.new_with_defaults(
            state_code='US_MO',
            supervision_violation_response_id=111,
            response_type=StateSupervisionViolationResponseType.VIOLATION_REPORT,
            response_date=date(2015, 5, 24),
            supervision_violation=StateSupervisionViolation.new_with_defaults(
                state_code='US_MO',
                supervision_violation_id=123,
                supervision_violation_types=[StateSupervisionViolationTypeEntry.new_with_defaults(
                    state_code='US_MO',
                    violation_type=StateSupervisionViolationType.MISDEMEANOR
                )]
            )
        )

        incarceration_period = StateIncarcerationPeriod.new_with_defaults(
            incarceration_period_id=1111,
            incarceration_type=StateIncarcerationType.STATE_PRISON,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='US_MO',
            admission_date=date(2015, 5, 30),
            admission_reason=StateIncarcerationPeriodAdmissionReason.PROBATION_REVOCATION,
            release_date=date(2018, 12, 4),
            release_reason=StateIncarcerationPeriodReleaseReason.SENTENCE_SERVED,
            source_supervision_violation_response=source_supervision_violation_response)

        supervision_sentence = \
            StateSupervisionSentence.new_with_defaults(
                supervision_sentence_id=111,
                external_id='ss1',
                start_date=date(2015, 1, 1),
                supervision_type=StateSupervisionType.PROBATION,
                status=StateSentenceStatus.COMPLETED,
                supervision_periods=[supervision_period]
            )

        assessment = StateAssessment.new_with_defaults(
            state_code='US_MO',
            assessment_type=StateAssessmentType.ORAS,
            assessment_score=33,
            assessment_date=date(2015, 3, 10)
        )

        person_periods = {'person': [fake_person],
                          'assessments': [assessment],
                          'supervision_periods': [supervision_period],
                          'incarceration_periods': [incarceration_period],
                          'incarceration_sentences': [],
                          'supervision_sentences': [supervision_sentence],
                          'violation_responses': [violation_report]
                          }

        supervision_period_supervision_type = StateSupervisionPeriodSupervisionType.PROBATION
        supervision_time_buckets = [
            NonRevocationReturnSupervisionTimeBucket(
                supervision_period.state_code,
                year=2015, month=3,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                assessment_score=assessment.assessment_score,
                assessment_level=assessment.assessment_level,
                assessment_type=assessment.assessment_type,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.HIGH,
                supervision_level_raw_text='H',
            ),
            NonRevocationReturnSupervisionTimeBucket(
                supervision_period.state_code,
                year=2015, month=4,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                assessment_score=assessment.assessment_score,
                assessment_level=assessment.assessment_level,
                assessment_type=assessment.assessment_type,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.HIGH,
                supervision_level_raw_text='H',
            ),
            SupervisionTerminationBucket(
                supervision_period.state_code,
                year=supervision_period.termination_date.year,
                month=supervision_period.termination_date.month,
                supervision_type=supervision_period_supervision_type,
                case_type=StateSupervisionCaseType.GENERAL,
                termination_reason=supervision_period.termination_reason,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10'
            ),
            RevocationReturnSupervisionTimeBucket(
                supervision_period.state_code,
                year=2015, month=5,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type=StateSupervisionViolationType.MISDEMEANOR,
                most_severe_violation_type_subtype='UNSET',
                response_count=1,
                violation_history_description='1misd',
                violation_type_frequency_counter=[['MISDEMEANOR']],
                case_type=StateSupervisionCaseType.GENERAL,
                revocation_type=RevocationType.REINCARCERATION,
                assessment_score=assessment.assessment_score,
                assessment_level=assessment.assessment_level,
                assessment_type=assessment.assessment_type,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.HIGH,
                supervision_level_raw_text='H',
            )
        ]

        correct_output = [
            (fake_person, supervision_time_buckets)]

        test_pipeline = TestPipeline()

        ssvr_to_agent_map = {
            'agent_id': 000,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_violation_response_id': 999
        }

        ssvr_to_agent_associations = (
            test_pipeline
            | 'Create SSVR to Agent table' >>
            beam.Create([ssvr_to_agent_map])
        )

        ssvr_agent_associations_as_kv = (
            ssvr_to_agent_associations |
            'Convert SSVR to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_violation_response_id')
        )

        supervision_period_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_period_id':
                supervision_period.supervision_period_id
        }

        supervision_period_to_agent_associations = (
            test_pipeline
            | 'Create SupervisionPeriod to Agent table' >>
            beam.Create([supervision_period_to_agent_map])
        )

        supervision_periods_to_agent_associations_as_kv = (
            supervision_period_to_agent_associations |
            'Convert SupervisionPeriod to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_period_id')
        )

        output = (test_pipeline
                  | beam.Create([(fake_person_id,
                                  person_periods)])
                  | 'Identify Supervision Time Buckets' >>
                  beam.ParDo(
                      pipeline.ClassifySupervisionTimeBuckets(),
                      AsDict(ssvr_agent_associations_as_kv),
                      AsDict(supervision_periods_to_agent_associations_as_kv))
                  )

        assert_that(output, equal_to(correct_output))

        test_pipeline.run()

    def testClassifySupervisionTimeBuckets_NoIncarcerationPeriods(self):
        """Tests the ClassifySupervisionTimeBuckets DoFn when the person has no
        incarceration periods."""
        fake_person_id = 12345

        fake_person = StatePerson.new_with_defaults(
            person_id=fake_person_id, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        supervision_period = schema.StateSupervisionPeriod(
            supervision_period_id=1111,
            state_code='US_ND',
            county_code='124',
            start_date=date(2015, 3, 14),
            termination_date=date(2015, 5, 29),
            supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
            supervision_level=StateSupervisionLevel.INTERNAL_UNKNOWN,
            supervision_level_raw_text='XXXX',
            person_id=fake_person_id
        )

        supervision_sentence = \
            StateSupervisionSentence.new_with_defaults(
                supervision_sentence_id=111,
                external_id='ss1',
                start_date=date(2015, 3, 1),
                supervision_type=StateSupervisionType.PROBATION,
                status=StateSentenceStatus.COMPLETED,
                supervision_periods=[supervision_period]
            )

        assessment = StateAssessment.new_with_defaults(
            state_code='US_ND',
            assessment_type=StateAssessmentType.ORAS,
            assessment_score=33,
            assessment_date=date(2015, 3, 23)
        )

        person_periods = {'person': [fake_person],
                          'assessments': [assessment],
                          'supervision_periods': [supervision_period],
                          'incarceration_periods': [],
                          'incarceration_sentences': [],
                          'supervision_sentences': [supervision_sentence],
                          'violation_responses': []
                          }

        supervision_period_supervision_type = StateSupervisionPeriodSupervisionType.PROBATION
        supervision_time_buckets = [
            NonRevocationReturnSupervisionTimeBucket(
                supervision_period.state_code,
                year=2015, month=3,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                assessment_score=assessment.assessment_score,
                assessment_level=assessment.assessment_level,
                assessment_type=assessment.assessment_type,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.INTERNAL_UNKNOWN,
                supervision_level_raw_text='XXXX',
            ),
            NonRevocationReturnSupervisionTimeBucket(
                supervision_period.state_code,
                year=2015, month=4,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                assessment_score=assessment.assessment_score,
                assessment_level=assessment.assessment_level,
                assessment_type=assessment.assessment_type,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.INTERNAL_UNKNOWN,
                supervision_level_raw_text='XXXX',
            ),
            NonRevocationReturnSupervisionTimeBucket(
                supervision_period.state_code,
                year=2015, month=5,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                assessment_score=assessment.assessment_score,
                assessment_level=assessment.assessment_level,
                assessment_type=assessment.assessment_type,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.INTERNAL_UNKNOWN,
                supervision_level_raw_text='XXXX',
            ),
            SupervisionTerminationBucket(
                supervision_period.state_code,
                year=supervision_period.termination_date.year,
                month=supervision_period.termination_date.month,
                supervision_type=supervision_period_supervision_type,
                case_type=StateSupervisionCaseType.GENERAL,
                termination_reason=supervision_period.termination_reason,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10'
            )
        ]

        correct_output = [
            (fake_person, supervision_time_buckets)]

        test_pipeline = TestPipeline()

        ssvr_to_agent_map = {
            'agent_id': 000,
            'agent_external_id': 'XXX',
            'district_external_id': 'X',
            'supervision_violation_response_id': 999
        }

        ssvr_to_agent_associations = (
            test_pipeline
            | 'Create SSVR to Agent table' >>
            beam.Create([ssvr_to_agent_map])
        )

        ssvr_agent_associations_as_kv = (
            ssvr_to_agent_associations |
            'Convert SSVR to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_violation_response_id')
        )

        supervision_period_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_period_id':
                supervision_period.supervision_period_id
        }

        supervision_period_to_agent_associations = (
            test_pipeline
            | 'Create SupervisionPeriod to Agent table' >>
            beam.Create([supervision_period_to_agent_map])
        )

        supervision_periods_to_agent_associations_as_kv = (
            supervision_period_to_agent_associations |
            'Convert SupervisionPeriod to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_period_id')
        )

        output = (test_pipeline
                  | beam.Create([(fake_person_id,
                                  person_periods)])
                  | 'Identify Supervision Time Buckets' >>
                  beam.ParDo(
                      pipeline.ClassifySupervisionTimeBuckets(),
                      AsDict(ssvr_agent_associations_as_kv),
                      AsDict(supervision_periods_to_agent_associations_as_kv))
                  )

        assert_that(output, equal_to(correct_output))

        test_pipeline.run()

    def testClassifySupervisionTimeBuckets_NoAssessments(self):
        """Tests the ClassifySupervisionTimeBuckets DoFn when the person has no
        assessments."""
        fake_person_id = 12345

        fake_person = StatePerson.new_with_defaults(
            person_id=fake_person_id, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        supervision_period = schema.StateSupervisionPeriod(
            supervision_period_id=1111,
            state_code='US_ND',
            county_code='124',
            start_date=date(2015, 3, 14),
            termination_date=date(2015, 5, 29),
            supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
            supervision_level=StateSupervisionLevel.INTERNAL_UNKNOWN,
            supervision_level_raw_text='XXXX',
            person_id=fake_person_id
        )

        supervision_sentence = \
            StateSupervisionSentence.new_with_defaults(
                supervision_sentence_id=111,
                external_id='ss1',
                start_date=date(2015, 3, 1),
                supervision_type=StateSupervisionType.PROBATION,
                status=StateSentenceStatus.COMPLETED,
                supervision_periods=[supervision_period]
            )

        person_periods = {'person': [fake_person],
                          'assessments': [],
                          'supervision_periods': [supervision_period],
                          'incarceration_periods': [],
                          'incarceration_sentences': [],
                          'supervision_sentences': [supervision_sentence],
                          'violation_responses': []
                          }

        supervision_period_supervision_type = StateSupervisionPeriodSupervisionType.PROBATION

        supervision_time_buckets = [
            NonRevocationReturnSupervisionTimeBucket(
                supervision_period.state_code,
                year=2015, month=3,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.INTERNAL_UNKNOWN,
                supervision_level_raw_text='XXXX',
            ),
            NonRevocationReturnSupervisionTimeBucket(
                supervision_period.state_code,
                year=2015, month=4,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.INTERNAL_UNKNOWN,
                supervision_level_raw_text='XXXX',
            ),
            NonRevocationReturnSupervisionTimeBucket(
                supervision_period.state_code,
                year=2015, month=5,
                supervision_type=supervision_period_supervision_type,
                most_severe_violation_type_subtype='UNSET',
                case_type=StateSupervisionCaseType.GENERAL,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10',
                supervision_level=StateSupervisionLevel.INTERNAL_UNKNOWN,
                supervision_level_raw_text='XXXX',
            ),
            SupervisionTerminationBucket(
                supervision_period.state_code,
                year=supervision_period.termination_date.year,
                month=supervision_period.termination_date.month,
                supervision_type=supervision_period_supervision_type,
                case_type=StateSupervisionCaseType.GENERAL,
                termination_reason=supervision_period.termination_reason,
                supervising_officer_external_id='OFFICER0009',
                supervising_district_external_id='10'
            )
        ]

        correct_output = [
            (fake_person, supervision_time_buckets)]

        test_pipeline = TestPipeline()

        ssvr_to_agent_map = {
            'agent_id': 000,
            'agent_external_id': 'XXX',
            'district_external_id': 'X',
            'supervision_violation_response_id': 999
        }

        ssvr_to_agent_associations = (
            test_pipeline
            | 'Create SSVR to Agent table' >>
            beam.Create([ssvr_to_agent_map])
        )

        ssvr_agent_associations_as_kv = (
            ssvr_to_agent_associations |
            'Convert SSVR to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_violation_response_id')
        )

        supervision_period_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_period_id':
                supervision_period.supervision_period_id
        }

        supervision_period_to_agent_associations = (
            test_pipeline
            | 'Create SupervisionPeriod to Agent table' >>
            beam.Create([supervision_period_to_agent_map])
        )

        supervision_periods_to_agent_associations_as_kv = (
            supervision_period_to_agent_associations |
            'Convert SupervisionPeriod to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_period_id')
        )

        output = (test_pipeline
                  | beam.Create([(fake_person_id,
                                  person_periods)])
                  | 'Identify Supervision Time Buckets' >>
                  beam.ParDo(
                      pipeline.ClassifySupervisionTimeBuckets(),
                      AsDict(ssvr_agent_associations_as_kv),
                      AsDict(supervision_periods_to_agent_associations_as_kv))
                  )

        assert_that(output, equal_to(correct_output))

        test_pipeline.run()

    def testClassifySupervisionTimeBuckets_NoSupervisionPeriods(self):
        """Tests the ClassifySupervisionTimeBuckets DoFn when the person
        has no supervision periods."""
        fake_person_id = 12345

        fake_person = StatePerson.new_with_defaults(
            person_id=fake_person_id, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        incarceration_period = StateIncarcerationPeriod.new_with_defaults(
            incarceration_period_id=1111,
            status=StateIncarcerationPeriodStatus.NOT_IN_CUSTODY,
            state_code='US_ND',
            admission_date=date(2008, 11, 20),
            admission_reason=StateIncarcerationPeriodAdmissionReason.
            NEW_ADMISSION,
            release_date=date(2010, 12, 4),
            release_reason=StateIncarcerationPeriodReleaseReason.
            SENTENCE_SERVED)

        assessment = StateAssessment.new_with_defaults(
            state_code='US_ND',
            assessment_type=StateAssessmentType.ORAS,
            assessment_score=33,
            assessment_date=date(2015, 3, 10)
        )

        person_periods = {'person': [fake_person],
                          'assessments': [assessment],
                          'supervision_periods': [],
                          'incarceration_periods': [incarceration_period],
                          'incarceration_sentences': [],
                          'supervision_sentences': [],
                          'violation_responses': []
                          }

        correct_output = []

        test_pipeline = TestPipeline()

        ssvr_to_agent_map = {
            'agent_id': 000,
            'agent_external_id': 'XXX',
            'district_external_id': 'X',
            'supervision_violation_response_id': 999
        }

        ssvr_to_agent_associations = (
            test_pipeline
            | 'Create SSVR to Agent table' >>
            beam.Create([ssvr_to_agent_map])
        )

        ssvr_agent_associations_as_kv = (
            ssvr_to_agent_associations |
            'Convert SSVR to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_violation_response_id')
        )

        supervision_period_to_agent_map = {
            'agent_id': 1010,
            'agent_external_id': 'OFFICER0009',
            'district_external_id': '10',
            'supervision_period_id': 9999
        }

        supervision_period_to_agent_associations = (
            test_pipeline
            | 'Create SupervisionPeriod to Agent table' >>
            beam.Create([supervision_period_to_agent_map])
        )

        supervision_periods_to_agent_associations_as_kv = (
            supervision_period_to_agent_associations |
            'Convert SupervisionPeriod to Agent table to KV tuples' >>
            beam.ParDo(pipeline.ConvertDictToKVTuple(),
                       'supervision_period_id')
        )

        output = (test_pipeline
                  | beam.Create([(fake_person_id,
                                  person_periods)])
                  | 'Identify Supervision Time Buckets' >>
                  beam.ParDo(
                      pipeline.ClassifySupervisionTimeBuckets(),
                      AsDict(ssvr_agent_associations_as_kv),
                      AsDict(supervision_periods_to_agent_associations_as_kv))
                  )

        assert_that(output, equal_to(correct_output))

        test_pipeline.run()


class TestCalculateSupervisionMetricCombinations(unittest.TestCase):
    """Tests the CalculateSupervisionMetricCombinations DoFn in the pipeline."""

    def testCalculateSupervisionMetricCombinations(self):
        """Tests the CalculateSupervisionMetricCombinations DoFn."""
        fake_person = StatePerson.new_with_defaults(
            person_id=123, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        supervision_time_buckets = [
            NonRevocationReturnSupervisionTimeBucket(
                state_code='CA',
                year=2015, month=3,
                supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
                most_severe_violation_type_subtype='UNSET',
                supervision_level=StateSupervisionLevel.MINIMUM,
                supervision_level_raw_text='MIN',
            ),
        ]

        # Get the number of combinations of person-event characteristics.
        num_combinations = len(calculator.characteristic_combinations(
            fake_person, supervision_time_buckets[0], ALL_INCLUSIONS_DICT, SupervisionMetricType.POPULATION))
        assert num_combinations > 0

        # Each characteristic combination will be tracked for each of the
        # months and the two methodology types
        expected_population_metric_count = \
            num_combinations * len(supervision_time_buckets) * 2

        expected_combination_counts = \
            {'population': expected_population_metric_count}

        test_pipeline = TestPipeline()

        calculation_month_limit = -1

        output = (test_pipeline
                  | beam.Create([(fake_person, supervision_time_buckets)])
                  | 'Calculate Supervision Metrics' >>
                  beam.ParDo(pipeline.CalculateSupervisionMetricCombinations(),
                             calculation_month_limit, ALL_INCLUSIONS_DICT).with_outputs('populations')
                  )

        assert_that(output.populations, AssertMatchers.
                    count_combinations(expected_combination_counts),
                    'Assert number of population metrics is expected value')

        test_pipeline.run()

    def testCalculateSupervisionMetricCombinations_withRevocations(self):
        """Tests the CalculateSupervisionMetricCombinations DoFn where
        revocations are identified."""
        fake_person = StatePerson.new_with_defaults(
            person_id=123, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        supervision_months = [
            RevocationReturnSupervisionTimeBucket(
                state_code='CA', year=2015, month=2,
                supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
                revocation_type=RevocationType.REINCARCERATION,
                source_violation_type=ViolationType.TECHNICAL),
            RevocationReturnSupervisionTimeBucket(
                state_code='CA', year=2015, month=3,
                supervision_type=StateSupervisionPeriodSupervisionType.PROBATION,
                revocation_type=RevocationType.REINCARCERATION,
                source_violation_type=ViolationType.TECHNICAL),
        ]

        # Get expected number of combinations for revocation counts
        num_combinations_revocation = len(
            calculator.characteristic_combinations(
                fake_person, supervision_months[0], ALL_INCLUSIONS_DICT,
                SupervisionMetricType.REVOCATION))
        assert num_combinations_revocation > 0

        # Multiply by the number of months and by 2 (to account for methodology)
        expected_revocation_metric_count = \
            num_combinations_revocation * len(supervision_months) * 2

        expected_combination_counts_revocations = {
            'revocation': expected_revocation_metric_count
        }

        # Get expected number of combinations for population count
        num_combinations_population = len(
            calculator.characteristic_combinations(
                fake_person, supervision_months[0], ALL_INCLUSIONS_DICT, SupervisionMetricType.POPULATION))
        assert num_combinations_population > 0

        # Multiply by the number of months and by 2 (to account for methodology)
        expected_population_metric_count = \
            num_combinations_population * len(supervision_months) * 2

        expected_combination_counts_populations = {
            'population': expected_population_metric_count,
        }

        test_pipeline = TestPipeline()

        calculation_month_limit = -1

        output = (test_pipeline
                  | beam.Create([(fake_person, supervision_months)])
                  | 'Calculate Supervision Metrics' >>
                  beam.ParDo(pipeline.CalculateSupervisionMetricCombinations(),
                             calculation_month_limit,
                             ALL_INCLUSIONS_DICT).with_outputs('populations',
                                                               'revocations')
                  )

        assert_that(output.revocations, AssertMatchers.
                    count_combinations(expected_combination_counts_revocations),
                    'Assert number of revocation metrics is expected value')

        assert_that(output.populations, AssertMatchers.
                    count_combinations(expected_combination_counts_populations),
                    'Assert number of population metrics is expected value')

        test_pipeline.run()

    def testCalculateSupervisionMetricCombinations_NoSupervision(self):
        """Tests the CalculateSupervisionMetricCombinations when there are
        no supervision months. This should never happen because any person
        without supervision time is dropped entirely from the pipeline."""
        fake_person = StatePerson.new_with_defaults(
            person_id=123, gender=Gender.MALE,
            birthdate=date(1970, 1, 1),
            residency_status=ResidencyStatus.PERMANENT)

        test_pipeline = TestPipeline()

        output = (test_pipeline
                  | beam.Create([(fake_person, [])])
                  | 'Calculate Supervision Metrics' >>
                  beam.ParDo(pipeline.CalculateSupervisionMetricCombinations(),
                             calculation_month_limit=-1, inclusions=ALL_INCLUSIONS_DICT)
                  )

        assert_that(output, equal_to([]))

        test_pipeline.run()

    def testCalculateSupervisionMetricCombinations_NoInput(self):
        """Tests the CalculateSupervisionMetricCombinations when there is
        no input to the function."""

        test_pipeline = TestPipeline()

        output = (test_pipeline
                  | beam.Create([])
                  | 'Calculate Supervision Metrics' >>
                  beam.ParDo(pipeline.CalculateSupervisionMetricCombinations(),
                             calculation_month_limit=-1, inclusions=ALL_INCLUSIONS_DICT)
                  )

        assert_that(output, equal_to([]))

        test_pipeline.run()


class TestProduceSupervisionPopulationMetric(unittest.TestCase):
    """Tests the ProduceSupervisionPopulationMetric DoFn in the pipeline."""

    def testProduceSupervisionPopulationMetric(self):
        metric_key_dict = {'gender': Gender.MALE,
                           'methodology': MetricMethodologyType.PERSON,
                           'year': 1999,
                           'month': 3,
                           'metric_type':
                               SupervisionMetricType.POPULATION.value,
                           'state_code': 'CA'}

        metric_key = json.dumps(json_serializable_metric_key(metric_key_dict),
                                sort_keys=True)

        value = 10

        test_pipeline = TestPipeline()

        all_pipeline_options = PipelineOptions().get_all_options()

        job_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S.%f')
        all_pipeline_options['job_timestamp'] = job_timestamp

        output = (test_pipeline
                  | beam.Create([(metric_key, value)])
                  | 'Produce Supervision Population Metric' >>
                  beam.ParDo(pipeline.
                             ProduceSupervisionMetrics(),
                             **all_pipeline_options)
                  )

        assert_that(output, AssertMatchers.
                    validate_supervision_population_metric(value))

        test_pipeline.run()

    def testProduceSupervisionPopulationMetric_revocation(self):
        metric_key_dict = {'gender': Gender.FEMALE,
                           'methodology': MetricMethodologyType.PERSON,
                           'year': 2012,
                           'month': 12,
                           'metric_type':
                               SupervisionMetricType.REVOCATION.value,
                           'state_code': 'VA'}

        metric_key = json.dumps(json_serializable_metric_key(metric_key_dict),
                                sort_keys=True)

        value = 10

        test_pipeline = TestPipeline()

        all_pipeline_options = PipelineOptions().get_all_options()

        job_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S.%f')
        all_pipeline_options['job_timestamp'] = job_timestamp

        output = (test_pipeline
                  | beam.Create([(metric_key, value)])
                  | 'Produce Supervision Population Metric' >>
                  beam.ParDo(pipeline.
                             ProduceSupervisionMetrics(),
                             **all_pipeline_options)
                  )

        assert_that(output, AssertMatchers.
                    validate_supervision_population_metric(value))

        test_pipeline.run()

    def testProduceSupervisionPopulationMetric_EmptyMetric(self):
        metric_key_dict = {}

        metric_key = json.dumps(json_serializable_metric_key(metric_key_dict),
                                sort_keys=True)

        value = 1131

        test_pipeline = TestPipeline()

        all_pipeline_options = PipelineOptions().get_all_options()

        job_timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H_%M_%S.%f')
        all_pipeline_options['job_timestamp'] = job_timestamp

        output = (test_pipeline
                  | beam.Create([(metric_key, value)])
                  | 'Produce Supervision Population Metric' >>
                  beam.ParDo(pipeline.
                             ProduceSupervisionMetrics(),
                             **all_pipeline_options)
                  )

        assert_that(output, equal_to([]))

        test_pipeline.run()


class AssertMatchers:
    """Functions to be used by Apache Beam testing `assert_that` functions to
    validate pipeline outputs."""

    @staticmethod
    def validate_pipeline_test(expected_metric_types: Set[SupervisionMetricType]):

        def _validate_pipeline_test(output):
            observed_metric_types: Set[SupervisionMetricType] = set()

            for metric in output:
                if not isinstance(metric, SupervisionMetric):
                    raise BeamAssertException('Failed assert. Output is not of type SupervisionMetric.')

                if isinstance(metric, TerminatedSupervisionAssessmentScoreChangeMetric):
                    observed_metric_types.add(SupervisionMetricType.ASSESSMENT_CHANGE)
                elif isinstance(metric, SupervisionSuccessMetric):
                    observed_metric_types.add(SupervisionMetricType.SUCCESS)
                elif isinstance(metric, SupervisionPopulationMetric):
                    observed_metric_types.add(SupervisionMetricType.POPULATION)
                elif isinstance(metric, SupervisionRevocationAnalysisMetric):
                    observed_metric_types.add(SupervisionMetricType.REVOCATION_ANALYSIS)
                elif isinstance(metric, SupervisionRevocationViolationTypeAnalysisMetric):
                    observed_metric_types.add(SupervisionMetricType.REVOCATION_VIOLATION_TYPE_ANALYSIS)
                elif isinstance(metric, SupervisionRevocationMetric):
                    observed_metric_types.add(SupervisionMetricType.REVOCATION)

            if observed_metric_types != expected_metric_types:
                raise BeamAssertException(f"Failed assert. Expected metric types {expected_metric_types} does not equal"
                                          f" observed metric types {observed_metric_types}.")

        return _validate_pipeline_test

    @staticmethod
    def assert_source_violation_type_set(expected_violation: ViolationType):
        """Asserts that there are some revocation metrics with the source_violation_type set."""
        def _assert_source_violation_type_set(output):

            with_violation_types = [metric for metric in output if
                                    isinstance(metric, SupervisionRevocationMetric)
                                    and metric.source_violation_type == expected_violation]

            if len(with_violation_types) == 0:
                raise BeamAssertException('No metrics with source violation type {} set.'.format(expected_violation))

        return _assert_source_violation_type_set

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

                if metric_type == SupervisionMetricType.POPULATION.value:
                    actual_combination_counts['population'] = \
                        actual_combination_counts['population'] + 1
                elif metric_type == SupervisionMetricType.REVOCATION.value:
                    actual_combination_counts['revocation'] = \
                        actual_combination_counts['revocation'] + 1

            for key in expected_combination_counts:
                if expected_combination_counts[key] != \
                        actual_combination_counts[key]:
                    raise BeamAssertException('Failed assert. Count does not'
                                              'match expected value.')

        return _count_combinations

    @staticmethod
    def validate_supervision_population_metric(expected_population_count):
        """Asserts that the count on the SupervisionMetric produced by the
        pipeline matches the expected population count."""
        def _validate_supervision_population_metric(output):
            if len(output) != 1:
                raise BeamAssertException('Failed assert. Should be only one '
                                          'SupervisionMetric returned.')

            supervision_metric = output[0]

            if supervision_metric.count != expected_population_count:
                raise BeamAssertException('Failed assert. Supervision count '
                                          'does not match expected value.')

        return _validate_supervision_population_metric
