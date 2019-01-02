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

"""Utilities for working with the ingest docket, such as enqueueing and leasing
docket items, and purging the docket queue.

The ingest docket is a pull-based queue of ingest tasks that are ready to be
performed. Each docket item is a high-level task for some region and scraping
type that some scraper must perform before the scraping process can be
considered complete. It typically contains a name, id, and/or other information
to search for in some criminal justice system we are scraping.

The docket is made up of multiple queues, one for each combination of region and
scrape type. Each item is placed on the appropriate queue so that it is consumed
and processed by the correct scraper. When a scraper wants more work, it will
lease a docket item: pulling it from the queue and marking it as leased for some
duration. When the work is complete, the scraper acks the item on the queue. If
it has not been acked by some specified time period, i.e. it expires, it is
returned to the queue to be attempted again.

Note that the docket is backed by Pub/Sub. Typically Pub/Sub delivers each
message once and in the order in which it was published. However, messages may
sometimes be delivered out of order or more than once (never less than once).

Each task can launch zero to many additional tasks within the push-based queue
that the scraper is running atop. A high-level lifecycle looks like this:

1. Scraping is launched for a region and scrape type, e.g. (US_NY, background)
2. One or more docket items are enqueued on the appropriate docket queue
3. A scraper worker for (US_NY, background) leases the next task from the
appropriate docket and begins to process it
4. In the lifecycle of that task: a search is made, with a response including
potentially zero to many search results. For each result, a new task is enqueued
on the us-ny-scraper push queue to be picked up by another scraper worker for
(US_NY, background).
5. Based on the implementation of the scraper, a scraper worker may attempt to
fully drain its push queue of work before returning to the docket, or may lease
another docket item on its own time.

Attributes:
    BACKGROUND_BATCH_SIZE: (int) the number of rows to load from a name list
        file into memory at a time, for individual enqueue into the docket,
        for background scrapes specifically
    SNAPSHOT_BATCH_SIZE: (int) the number of snapshots or records to query from
        the database into memory at a time, for individual enqueue into the
        docket, for snapshot scrapes specifically
    SNAPSHOT_DISTANCE_YEARS: (int) the max number of years into the past we will
        search for relevant snapshots whose data to scrape again
    FILENAME_PREFIX: (string) the directory in which to find name list files
"""

import csv
import json
import logging

from google.api_core import exceptions  # pylint: disable=no-name-in-module
from google.cloud import pubsub

from recidiviz.ingest import constants
from recidiviz.utils import environment, metadata, regions

SNAPSHOT_BATCH_SIZE = 100
SNAPSHOT_DISTANCE_YEARS = 10
FILENAME_PREFIX = "./name_lists/"

# We only lease tasks for 5min, so that they pop back into the queue
# if we pause or stop the scrape for very long.
# Note: This may be the right number for us_ny snapshot scraping, but
#   if reused with another scraper the background scrapes might need
#   more time depending on e.g. # results for query 'John Doe'.
ACK_DEADLINE_SECONDS = 300

_publisher = None
def publisher():
    global _publisher
    if not _publisher:
        _publisher = pubsub.PublisherClient()
    return _publisher


@environment.test_only
def clear_publisher():
    global _publisher
    _publisher = None


_subscriber = None
def subscriber():
    global _subscriber
    if not _subscriber:
        _subscriber = pubsub.SubscriberClient()
    return _subscriber


@environment.test_only
def clear_subscriber():
    global _subscriber
    _subscriber = None


def _docket_topic_path(scrape_key):
    return publisher().topic_path(
        metadata.project_id(),
        "v1.{}-{}".format(scrape_key.region_code, scrape_key.scrape_type))


def _docket_subscription_path(scrape_key):
    return subscriber().subscription_path(
        metadata.project_id(),
        "v1.{}-{}".format(scrape_key.region_code, scrape_key.scrape_type))


@environment.test_only
def create_topic_and_subscription(scrape_key):
    _create_topic_and_subscription(scrape_key)


def _create_topic_and_subscription(scrape_key):
    topic_path = _docket_topic_path(scrape_key)
    try:
        logging.info("Creating pubsub topic: '%s'", topic_path)
        publisher().create_topic(topic_path)
    except exceptions.AlreadyExists:
        logging.info("Topic already exists")

    subscription_path = _docket_subscription_path(scrape_key)
    try:
        logging.info("Creating pubsub subscription: '%s'", subscription_path)
        subscriber().create_subscription(
            subscription_path, topic_path,
            ack_deadline_seconds=ACK_DEADLINE_SECONDS)
    except exceptions.AlreadyExists:
        logging.info("Subscription already exists")


# ##################### #
# Populating the docket #
# ##################### #


def load_target_list(scrape_key, given_names="", surname=""):
    """Starts docket loading based on scrape type and region.

    Determines correct scrape type and kicks off target list generation,
    loading of docket items based on the target list.

    Args:
        scrape_key: (ScrapeKey) The scraper to load docket for
        given_names: Given names of where to begin
        surname: Surname of where to begin

    Returns:
        N/A
    """
    logging.info("Getting target list for scraper: %s", scrape_key)

    if scrape_key.scrape_type == constants.BACKGROUND_SCRAPE:
        name_list_file = regions.Region(scrape_key.region_code).names_file

        # Construct filename, process user-supplied name query (if provided)
        filename = FILENAME_PREFIX + name_list_file
        query_name = (surname, given_names) if surname or given_names else None

        load_background_target_list(scrape_key, filename, query_name)


def load_background_target_list(scrape_key, name_file, query_name):
    """Load background scrape docket items, from name file.

    Iterates over a CSV of common names, loading a docket item for the scraper
    to search for each one. We load batches of lines into memory at a time,
    until the entire file has been processed.

    If a name was provided in the initial request, will attempt to only load
    names from the index of that name in the file onward, allowing for
    'resuming' a background scrape from a specific point if there were
    problems. If the provided name is not found in the name file at all, a
    single docket item will be created to search for that name only.

    Args:
        scrape_key: (ScrapeKey) Scrape key
        name_file: (string) Name of the name file to be loaded
        query_name: User-provided name, in the form of a tuple (surname,
            given names). Empty strings if not provided.

    Returns:
        N/A
    """
    futures = []
    # If a query is provided then the names aren't relevant until we find the
    # query name, so `should_write_names` starts as False. If no query is
    # provided then all names should be written.
    should_write_names = not bool(query_name)

    _create_topic_and_subscription(scrape_key)

    with open(name_file, 'r') as csvfile:
        names_reader = csv.reader(csvfile)

        for row in names_reader:
            if not row:
                continue

            name = (row[0], "") if len(row) == 1 else tuple(row)
            if not should_write_names:
                # Check to see if this is the `query_name` and if so mark that
                # all further names should be written to the docket.
                should_write_names = name == query_name

            if should_write_names:
                futures.append(_add_to_query_docket(scrape_key, name))

    # The query string was not found, add it as a separate docket item.
    if not should_write_names:
        logging.info("Couldn't find user-provided name '%s' in name list, "
                     "adding one-off docket item for the name instead.",
                     str(query_name))
        futures.append(_add_to_query_docket(scrape_key, query_name))

    # TODO(#176): wrap with concurrent.futures.as_completed
    for future in futures:
        future.result()
    logging.info("Finished loading background target list to docket.")


@environment.test_only
def add_to_query_docket(scrape_key, item):
    return _add_to_query_docket(scrape_key, item)


def _add_to_query_docket(scrape_key, item):
    """Add docket item to the query docket for relevant region / scrape type

    Adds item the query docket for the given region and scrape type. The scraper
    will pull each item from the docket in turn for scraping (e.g. each name, if
    a background scrape, or each person ID if a snapshot scrape.)

    The pubsub client library automatically batches messages before sending
    them.

    This requires that the topic and subscription already exist.

    Args:
        scrape_key: (ScrapeKey) The scraper to add to the docket for
        item: Payload to add

    Returns:
        Future for the added message
    """
    logging.debug("Attempting to add item to '%s' docket: %s",
                  scrape_key, item)
    return publisher().publish(_docket_topic_path(scrape_key),
                               data=json.dumps(item).encode())


# ########################## #
# Retrieving from the docket #
# ########################## #


def _retry_with_create(scrape_key, fn):
    try:
        result = fn()
    except exceptions.NotFound:
        _create_topic_and_subscription(scrape_key)
        result = fn()
    return result


def get_new_docket_item(scrape_key, return_immediately=False):
    """Retrieves an item from the docket for the specified region / scrape type

    Retrieves an arbitrary item still in the docket (whichever docket
    type is specified). If the docket is currently empty this will wait for
    a bounded period of time for a message to be published, ensuring that newly
    created tasks are received. This behavior can be overriden using the
    return_immediately param.

    Args:
        scrape_key: (ScrapeKey) The scraper to lease an item for
        return_immediately: (bool) Whether to return immediately or to wait for
            a bounded period of time for a message to enter the docket.

    Returns:
        Task entity from queue
        None if query returns None
    """
    docket_message = None

    subscription_path = _docket_subscription_path(scrape_key)
    def inner():
        return subscriber().pull(subscription_path, max_messages=1,
                                 return_immediately=return_immediately)
    response = _retry_with_create(scrape_key, inner)

    if response.received_messages:
        docket_message = response.received_messages[0]
        logging.info("Leased docket item from subscription: %s",
                     subscription_path)
    else:
        logging.info("No matching docket item found in the docket queue for "
                     "scraper: %s", scrape_key)

    return docket_message


# ######################## #
# Removing from the docket #
# ######################## #


def purge_query_docket(scrape_key):
    """Purges the docket of all tasks for provided region / scrape type

    This deletes our current subscription to the given docket topic. When we try
    to add or pull from the topic next, we will create a new subscription. That
    subscription will only receive messages that are published after it is
    created.

    Args:
        scrape_key: (ScrapeKey) The scraper whose tasks to purge the docket of

    Returns:
        N/A
    """
    logging.info("Purging existing query docket for scraper: %s", scrape_key)

    # TODO(#342): Use subscriber().seek(subscription_path, time=timestamp)
    # once available on the emulator.
    try:
        subscriber().delete_subscription(_docket_subscription_path(scrape_key))
    except exceptions.NotFound:
        pass

    _create_topic_and_subscription(scrape_key)


def ack_docket_item(scrape_key, ack_id):
    """Ack a specific docket item

    Acknowledges a specific docket item once it's been completed. This indicates
    to pubsub that it should not be delivered again.

    Args:
        ack_id: (string) Id used to ack the message

    Returns:
        N/A
    """
    def inner():
        subscriber().acknowledge(_docket_subscription_path(scrape_key),
                                 [ack_id])
    _retry_with_create(scrape_key, inner)
