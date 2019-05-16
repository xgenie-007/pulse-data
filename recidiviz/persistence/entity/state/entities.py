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
# ============================================================================
"""Domain logic entities used in the persistence layer for state data.

Note: These classes mirror the SQL Alchemy ORM objects but are kept separate.
This allows these persistence layer objects additional flexibility that the SQL
Alchemy ORM objects can't provide.
"""

from typing import Optional, List

import datetime
import attr

from recidiviz.common.attr_mixins import BuildableAttr, DefaultableAttr
from recidiviz.common.constants.state.agent import AgentType
from recidiviz.common.constants.state.assessment import AssessmentClass, \
    AssessmentType

from recidiviz.common.constants.bond import BondType, BondStatus
from recidiviz.common.constants.charge import ChargeDegree, ChargeStatus
from recidiviz.common.constants.person_characteristics import (
    Gender,
    Race,
    Ethnicity,
    ResidencyStatus
)
from recidiviz.common.constants.county.sentence import SentenceStatus

from recidiviz.common.constants.state.court_case import CourtType, \
    CourtCaseStatus
from recidiviz.common.constants.state.incarceration import IncarcerationType
from recidiviz.common.constants.state.incarceration_incident import \
    IncarcerationIncidentOffense, IncarcerationIncidentOutcome
from recidiviz.common.constants.state.incarceration_period import (
    IncarcerationPeriodStatus,
    IncarcerationPeriodAdmissionReason,
    IncarcerationPeriodReleaseReason,
    IncarcerationFacilitySecurityLevel,
)

from recidiviz.common.constants.state.fine import FineStatus
from recidiviz.common.constants.state.charge import ChargeClassification
from recidiviz.common.constants.state.supervision import SupervisionType
from recidiviz.common.constants.state.supervision_period import \
    SupervisionPeriodStatus, SupervisionPeriodAdmissionReason, \
    SupervisionPeriodTerminationReason, SupervisionLevel

from recidiviz.common.constants.state.supervision_violation import \
    SupervisionViolationType
from recidiviz.common.constants.state.supervision_violation_response import \
    SupervisionViolationResponseType, SupervisionViolationResponseDecision, \
    SupervisionViolationResponseRevocationType, \
    SupervisionViolationResponseDecidingBodyType
from recidiviz.persistence.entity.base_entity import Entity, ExternalIdEntity


# **** Entity ordering template *****:

# Primary key - Only optional when hydrated in the data converter, before
# we have written this entity to the persistence layer

# Status

# Type

# Attributes
#   - When
#   - Where
#   - What
#   - Who

# Cross-entity relationships

@attr.s
class PersonExternalId(Entity, BuildableAttr, DefaultableAttr):
    external_id: str = attr.ib()

    #   - Where
    # State providing the external id
    state_code: str = attr.ib()  # non-nullable

    # Cross-entity relationships
    person_id: Optional[int] = attr.ib()


@attr.s
class PersonRace(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    # Attributes
    race: Optional[Race] = attr.ib()
    race_raw_text: Optional[str] = attr.ib()

    # Cross-entity relationships
    person_id: Optional[int] = attr.ib()


@attr.s
class PersonEthnicity(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    # Attributes
    ethnicity: Optional[Ethnicity] = attr.ib()
    ethnicity_raw_text: Optional[str] = attr.ib()

    # Cross-entity relationships
    person_id: Optional[int] = attr.ib()


@attr.s
class Person(Entity, BuildableAttr, DefaultableAttr):
    """Models a Person moving through the criminal justice system."""
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    person_id: Optional[int] = attr.ib()

    # Attributes

    #   - Where
    current_address: Optional[str] = attr.ib(default=None)

    #   - What
    full_name: Optional[str] = attr.ib(default=None)
    aliases: List[str] = attr.ib(factory=list)

    birthdate: Optional[datetime.date] = attr.ib(default=None)
    birthdate_inferred_from_age: Optional[bool] = attr.ib(default=None)

    gender: Optional[Gender] = attr.ib(default=None)
    gender_raw_text: Optional[str] = attr.ib(default=None)

    # NOTE: This may change over time - we track these changes in history tables
    residency_status: Optional[ResidencyStatus] = attr.ib(default=None)

    # Cross-entity relationships
    external_ids: List['PersonExternalId'] = attr.ib(factory=list)
    races: List['PersonRace'] = attr.ib(factory=list)
    ethnicities: List['PersonEthnicity'] = attr.ib(factory=list)
    assessments: List['Assessment'] = attr.ib(factory=list)
    sentence_groups: List['SentenceGroup'] = attr.ib(factory=list)

    # NOTE: Eventually we might have a relationship to objects holding
    # pre-sentence information so we can track encounters with the justice
    # system that don't result in sentences.


@attr.s
class Bond(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """Models a Bond associated with a particular Charge."""
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    bond_id: Optional[int] = attr.ib()

    # Status
    status: BondStatus = attr.ib()  # non-nullable
    status_raw_text: Optional[str] = attr.ib()

    # Type
    bond_type: Optional[BondType] = attr.ib()
    bond_type_raw_text: Optional[str] = attr.ib()

    # Attributes
    #   - When
    date_paid: Optional[datetime.date] = attr.ib()

    #   - Where
    state_code: str = attr.ib()  # non-nullable
    county_code: Optional[str] = attr.ib()

    #   - What
    amount_dollars: Optional[int] = attr.ib()

    #   - Who
    bond_agent: Optional[str] = attr.ib()

    # Cross-entity relationships
    person_id: Optional[int] = attr.ib()
    charge_ids: List[int] = attr.ib(factory=list)


@attr.s
class CourtCase(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """Models a CourtCase associated with some set of Charges"""
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    court_case_id: Optional[int] = attr.ib()

    # Status
    status: CourtCaseStatus = attr.ib()

    # Type
    court_type: Optional[CourtType] = attr.ib()
    court_type_raw_text: Optional[str] = attr.ib()

    # Attributes
    #   - When
    next_court_date: Optional[datetime.date] = attr.ib()

    #   - Where
    # Location of the court itself
    state_code: str = attr.ib()  # non-nullable
    # County where the court case took place
    county_code: Optional[str] = attr.ib()

    #   - What
    court_fee_dollars: Optional[int] = attr.ib()

    #   - Who
    judge_name: Optional[str] = attr.ib()

    # Cross-entity relationships
    person_id: Optional[int] = attr.ib()
    charge_ids: List[int] = attr.ib(factory=list)


@attr.s
class Charge(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """Models a Charge against a particular Person."""

    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    charge_id: Optional[int] = attr.ib()

    # Status
    status: ChargeStatus = attr.ib()  # non-nullable
    status_raw_text: Optional[str] = attr.ib()

    # Type
    # N/A

    # Attributes
    #   - When
    offense_date: Optional[datetime.date] = attr.ib()
    date_charged: Optional[datetime.date] = attr.ib()

    #   - Where
    state_code: str = attr.ib()  # non-nullable

    #   - What
    # A code corresponding to actual sentencing terms that
    statute: Optional[str] = attr.ib()
    description: Optional[str] = attr.ib()
    attempted: Optional[bool] = attr.ib()
    charge_classification: Optional[ChargeClassification] = attr.ib()
    charge_classification_raw_text: Optional[str] = attr.ib()
    degree: Optional[ChargeDegree] = attr.ib()
    degree_raw_text: Optional[str] = attr.ib()
    counts: Optional[int] = attr.ib()
    charge_notes: Optional[str] = attr.ib()

    #   - Who
    charging_entity: Optional[str] = attr.ib()

    # Cross-entity relationships
    person_id: Optional[int] = attr.ib()
    court_case: Optional['CourtCase'] = attr.ib(default=None)
    bond: Optional['Bond'] = attr.ib(default=None)

    incarceration_sentence_ids: List[int] = attr.ib(factory=list)
    supervision_sentence_ids: List[int] = attr.ib(factory=list)
    fine_ids: List[int] = attr.ib(factory=list)


@attr.s
class Assessment(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """Models an Assessment conducted about a particular Person."""

    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    assessment_id: Optional[int] = attr.ib()

    # Status
    # N/A - Always "COMPLETED", for now

    # Type
    assessment_class: Optional[AssessmentClass] = attr.ib()
    assessment_class_raw_text: Optional[str] = attr.ib()
    assessment_type: Optional[AssessmentType] = attr.ib()
    assessment_type_raw_text: Optional[str] = attr.ib()

    # Attributes
    #   - When
    assessment_date: Optional[datetime.date] = attr.ib()

    #   - Where
    # N/A this question is answered by the Stay period referenced below

    #   - What
    assessment_score: Optional[int] = attr.ib()
    assessment_level: Optional[str] = attr.ib()
    assessment_metadata: Optional[str] = attr.ib()

    #   - Who
    conducting_agent_name: Optional[str] = attr.ib()
    conducting_agent_id: Optional[str] = attr.ib()

    # Cross-entity relationships

    # Only optional when hydrated in the data converter, before we have written
    # this entity to the persistence layer
    person_id: Optional[int] = attr.ib()

    incarceration_period_id: Optional[int] = attr.ib()
    supervision_period_id: Optional[int] = attr.ib()


@attr.s
class SentenceGroup(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """
    Models a group of related sentences, which may be served consecutively or
    concurrently.
    """
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    sentence_group_id: Optional[int] = attr.ib()

    # Status
    # TODO(1698): Look at Measures for Justice doc for methodology on how to
    #  calculate an aggregate sentence status from multiple sentence statuses.
    # This will be a composite of all the linked individual statuses
    status: SentenceStatus = attr.ib()  # non-nullable
    status_raw_text: Optional[str] = attr.ib()

    # Type
    # N/A

    # Attributes
    #   - When
    date_imposed: Optional[datetime.date] = attr.ib()
    # TODO(1698): Consider including rollup projected completion dates?

    #   - Where
    state_code: str = attr.ib()  # non-nullable
    # The county where this sentence was issued
    county_code: Optional[str] = attr.ib()

    #   - What
    # See |supervision_sentences|, |incarceration_sentences|, and |fines| in
    # entity relationships below.

    #   - Who
    # See |person_id| in entity relationships below.

    # Cross-entity relationships
    person_id: Optional[int] = attr.ib()
    supervision_sentences: List['SupervisionSentence'] = attr.ib(factory=list)
    incarceration_sentences: List['IncarcerationSentence'] = \
        attr.ib(factory=list)
    fines: List['Fine'] = attr.ib(factory=list)
    # TODO(1698): Add information about the time relationship between individual
    #  sentences (i.e. consecutive vs concurrent).


@attr.s
class SupervisionSentence(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """
    Models a sentence for a supervisory period associated with one or more
    Charges against a Person.
    """
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    supervision_sentence_id: Optional[int] = attr.ib()

    # Status
    status: SentenceStatus = attr.ib()  # non-nullable
    status_raw_text: Optional[str] = attr.ib()

    # Type
    supervision_type: Optional[SupervisionType] = attr.ib()
    supervision_type_raw_text: Optional[str] = attr.ib()

    # Attributes
    #   - When
    projected_completion_date: Optional[datetime.date] = attr.ib()
    completion_date: Optional[datetime.date] = attr.ib()

    #   - Where
    state_code: str = attr.ib()  # non-nullable
    # The county where this sentence was issued
    county_code: Optional[str] = attr.ib()

    #   - What
    min_length_days: Optional[int] = attr.ib()
    max_length_days: Optional[int] = attr.ib()

    #   - Who

    # Cross-entity relationships
    state_person_id: Optional[int] = attr.ib(default=None)
    sentence_group_id: Optional[int] = attr.ib(default=None)
    charges: List['Charge'] = attr.ib(factory=list)

    # NOTE: A person might have an incarceration period associated with a
    # supervision sentence if they violate the terms of the sentence and are
    # sent back to prison.
    incarceration_periods: List['IncarcerationPeriod'] = attr.ib(factory=list)
    supervision_periods: List['SupervisionPeriod'] = attr.ib(factory=list)


@attr.s
class IncarcerationSentence(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """
    Models a sentence for prison/jail time associated with one or more Charges
    against a Person.
    """
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    incarceration_sentence_id: Optional[int] = attr.ib()

    # Status
    status: SentenceStatus = attr.ib()  # non-nullable
    status_raw_text: Optional[str] = attr.ib()

    # Type
    incarceration_type: Optional[IncarcerationType] = attr.ib()
    incarceration_type_raw_text: Optional[str] = attr.ib()

    # Attributes
    #   - When
    projected_min_release_date: Optional[datetime.date] = attr.ib()
    projected_max_release_date: Optional[datetime.date] = attr.ib()
    parole_eligibility_date: Optional[datetime.date] = attr.ib()

    #   - Where
    state_code: str = attr.ib()  # non-nullable
    # The county where this sentence was issued
    county_code: Optional[str] = attr.ib()

    #   - What
    # These will be None if is_life is true
    min_length_days: Optional[int] = attr.ib()
    max_length_days: Optional[int] = attr.ib()

    is_life: Optional[bool] = attr.ib()

    parole_possible: Optional[bool] = attr.ib()
    is_suspended: Optional[bool] = attr.ib()
    initial_time_served_days: Optional[int] = attr.ib()
    good_time_days: Optional[int] = attr.ib()
    earned_time_days: Optional[int] = attr.ib()

    #   - Who
    # See |person_id| in entity relationships below.

    # Cross-entity relationships
    state_person_id: Optional[int] = attr.ib(default=None)
    sentence_group_id: Optional[int] = attr.ib(default=None)
    charges: List['Charge'] = attr.ib(factory=list)

    incarceration_periods: List['IncarcerationPeriod'] = attr.ib(factory=list)
    supervision_periods: List['SupervisionPeriod'] = attr.ib(factory=list)


@attr.s
class Fine(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """
    Models a fine that a Person is sentenced to pay in association with a
    Charge.
    """
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    fine_id: Optional[int] = attr.ib()

    # Status
    status: FineStatus = attr.ib()  # non-nullable
    status_raw_text: Optional[str] = attr.ib()

    # Type
    # N/A

    # Attributes
    #   - When
    date_paid: Optional[datetime.date] = attr.ib()

    #   - Where
    state_code: str = attr.ib()  # non-nullable
    # The county where this fine was issued
    county_code: Optional[str] = attr.ib()

    #   - What
    fine_dollars: Optional[int] = attr.ib()

    #   - Who
    # See |person_id| in entity relationships below.

    # Cross-entity relationships
    state_person_id: Optional[int] = attr.ib(default=None)
    sentence_group_id: Optional[int] = attr.ib(default=None)
    charges: List['Charge'] = attr.ib(factory=list)


@attr.s
class IncarcerationPeriod(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """
    Models an uninterrupted period of time that a Person is incarcerated at a
    single facility as a result of a particular sentence.
    """

    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    incarceration_period_id: Optional[int] = attr.ib()

    # Status
    status: IncarcerationPeriodStatus = attr.ib()  # non-nullable
    status_raw_text: Optional[str] = attr.ib()

    # Type
    incarceration_type: Optional[IncarcerationType] = attr.ib()
    incarceration_type_raw_text: Optional[str] = attr.ib()

    # Attributes
    #   - When
    admission_date: Optional[datetime.date] = attr.ib()
    release_date: Optional[datetime.date] = attr.ib()

    #   - Where
    state_code: str = attr.ib()  # non-nullable
    # The county where the facility is located
    county_code: Optional[str] = attr.ib()

    facility: Optional[str] = attr.ib()
    housing_unit: Optional[str] = attr.ib()

    #   - What
    facility_security_level: Optional[IncarcerationFacilitySecurityLevel] = \
        attr.ib()
    facility_security_level_raw_text: Optional[str] = attr.ib()

    admission_reason: Optional[IncarcerationPeriodAdmissionReason] = attr.ib()
    admission_reason_raw_text: Optional[str] = attr.ib()

    projected_release_reason: \
        Optional[IncarcerationPeriodReleaseReason] = attr.ib()
    projected_release_reason_raw_text: Optional[str] = attr.ib()

    release_reason: Optional[IncarcerationPeriodReleaseReason] = \
        attr.ib()
    release_reason_raw_text: Optional[str] = attr.ib()

    #   - Who
    # See |person_id| in entity relationships below.

    # Cross-entity relationships
    state_person_id: Optional[int] = attr.ib(default=None)

    # NOTE: An incarceration period might count towards multiple sentences
    incarceration_sentence_ids: List[int] = attr.ib(default=None)
    supervision_sentence_ids: List[int] = attr.ib(default=None)

    incarceration_incidents: List['IncarcerationIncident'] = \
        attr.ib(factory=list)
    parole_decisions: List['ParoleDecision'] = attr.ib(factory=list)
    assessments: List['Assessment'] = attr.ib(factory=list)

    # When the admission reason is SUPERVISION_VIOLATION, this is the object
    # with info about the violation/hearing that resulted in the revocation
    source_supervision_violation_response: Optional[int] = \
        attr.ib(default=None)


@attr.s
class SupervisionPeriod(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """
    Models a distinct period of time that a Person is under supervision as a
    result of a particular sentence.
    """
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    supervision_period_id: Optional[int] = attr.ib()

    # Status
    status: SupervisionPeriodStatus = attr.ib()  # non-nullable
    status_raw_text: Optional[str] = attr.ib()

    # Type
    supervision_type: Optional[SupervisionType] = attr.ib()
    supervision_type_type_raw_text: Optional[str] = attr.ib()

    # Attributes
    #   - When
    start_date: Optional[datetime.date] = attr.ib()
    termination_date: Optional[datetime.date] = attr.ib()

    #   - Where
    state_code: str = attr.ib()  # non-nullable
    # The county where this person is being supervised
    county_code: Optional[str] = attr.ib()

    #   - What
    admission_reason: Optional[SupervisionPeriodAdmissionReason] = attr.ib()
    admission_reason_raw_text: Optional[str] = attr.ib()

    termination_reason: Optional[SupervisionPeriodTerminationReason] = \
        attr.ib()
    termination_reason_raw_text: Optional[str] = attr.ib()

    supervision_level: Optional[SupervisionLevel] = attr.ib()
    supervision_level_raw_text: Optional[str] = attr.ib()

    conditions: List[str] = attr.ib(factory=list)

    #   - Who
    # See |person_id| in entity relationships below.

    # Cross-entity relationships
    state_person_id: Optional[int] = attr.ib(default=None)

    # NOTE: A supervision period might count towards multiple sentences
    incarceration_sentence_ids: List[int] = attr.ib(default=None)
    supervision_sentence_ids: List[int] = attr.ib(default=None)

    supervision_violations: List['SupervisionViolation'] = attr.ib(
        factory=list)
    assessments: List['Assessment'] = attr.ib(factory=list)


@attr.s
class IncarcerationIncident(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """Models a documented incident for a Person while incarcerated."""
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    incident_id: Optional[int] = attr.ib()

    # Status
    # N/A

    # Type
    # N/A

    # Attributes
    #   - When
    incident_date: Optional[datetime.date] = attr.ib()

    #   - Where
    state_code: str = attr.ib()  # non-nullable
    # The county where this intervention happened - should match the linked
    # incarceration period.
    county_code: Optional[str] = attr.ib()

    location_within_facility: Optional[str] = attr.ib()

    #   - What
    offense: Optional[IncarcerationIncidentOffense] = attr.ib()
    offense_raw_text: Optional[str] = attr.ib()
    outcome: Optional[IncarcerationIncidentOutcome] = attr.ib()
    outcome_raw_text: Optional[str] = attr.ib()

    #   - Who
    responding_officer_name: Optional[str] = attr.ib()
    responding_officer_id: Optional[str] = attr.ib()

    # Cross-entity relationships
    state_person_id: Optional[int] = attr.ib(default=None)
    incarceration_period_id: Optional[int] = attr.ib(default=None)


@attr.s
class ParoleDecision(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """Models a Parole Decision for a Person while under Incarceration."""
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    parole_decision_id: Optional[int] = attr.ib()

    # Status
    received_parole: Optional[bool] = attr.ib()

    # Type

    # Attributes
    #   - When
    decision_date: Optional[datetime.date] = attr.ib()
    corrective_action_deadline: Optional[datetime.date] = attr.ib()

    #   - Where
    state_code: str = attr.ib()  # non-nullable
    # The county where the decision was made, if different from the county where
    # this person is incarcerated.
    county_code: Optional[str] = attr.ib()

    #   - What
    decision_outcome: Optional[str] = attr.ib()
    decision_reasoning: Optional[str] = attr.ib()
    corrective_action: Optional[str] = attr.ib()

    #   - Who
    # TODO(1625) - Convert to List[Agent]
    decision_agent_names: List[str] = attr.ib(factory=list)

    # Cross-entity relationships
    incarceration_period_id: Optional[int] = attr.ib(default=None)


class SupervisionViolation(ExternalIdEntity, BuildableAttr, DefaultableAttr):
    """
    Models a recorded instance where a Person has violated one or more of the
    conditions of their SupervisionSentence.
    """
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    supervision_violation_id: Optional[int] = attr.ib()

    # Status
    # N/A

    # Type
    violation_type: Optional[SupervisionViolationType] = attr.ib()
    violation_type_raw_text: Optional[str] = attr.ib()

    # Attributes
    #   - When
    violation_date: Optional[datetime.date] = attr.ib()

    #   - Where
    # State that recorded this violation, not necessarily where the violation
    # took place
    state_code: str = attr.ib()  # non-nullable

    #   - What
    # These should correspond to |conditions| in SupervisionPeriod
    is_violent: Optional[bool] = attr.ib()

    violated_conditions: List[str] = attr.ib(factory=list)

    #   - Who
    # See |person_id| in entity relationships below.

    # Cross-entity relationships
    state_person_id: Optional[int] = attr.ib(default=None)
    supervision_period_id: Optional[int] = attr.ib(default=None)
    supervision_violation_responses: List['SupervisionViolationResponse'] = \
        attr.ib(factory=list)


class Agent(Entity, BuildableAttr, DefaultableAttr):
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    agent_id: Optional[int] = attr.ib()

    # Type
    agent_type: Optional[AgentType] = attr.ib()

    # Attributes
    #   - Where
    state_code: str = attr.ib()  # non-nullable

    #   - What
    full_name: Optional[str] = attr.ib()


@attr.s
class SupervisionViolationResponse(ExternalIdEntity,
                                   BuildableAttr,
                                   DefaultableAttr):
    """Models a response to a SupervisionViolation"""
    # Primary key - Only optional when hydrated in the data converter, before
    # we have written this entity to the persistence layer
    supervision_violation_response_id: Optional[int] = attr.ib()

    # Status
    # N/A

    # Type
    response_type: Optional[SupervisionViolationResponseType] = attr.ib()

    # Attributes
    #   - When
    response_date: Optional[datetime.date] = attr.ib()

    #   - Where
    state_code: str = attr.ib()  # non-nullable

    #   - What
    decision: Optional[SupervisionViolationResponseDecision] = attr.ib()

    # Only nonnull if decision is REVOCATION
    revocation_type: Optional[SupervisionViolationResponseRevocationType] = \
        attr.ib()

    #   - Who
    # See SupervisionViolationResponders below
    deciding_body_type: Optional[SupervisionViolationResponseDecidingBodyType] \
        = attr.ib()
    # See also |deciding_agents| below

    # Cross-entity relationships
    person_id: Optional[int] = attr.ib()
    supervision_violation_id: Optional[int] = attr.ib()

    decision_agents: List['Agent'] = attr.ib(factory=list)