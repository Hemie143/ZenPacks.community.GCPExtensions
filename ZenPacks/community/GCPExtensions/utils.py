##############################################################################
#
# Copyright (C) Zenoss, Inc. 2018-2019, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Utilities with no third-party library dependencies."""

# Default Exports
__all__ = [
    "valid_project_id",
    "valid_email_address",
    "valid_private_key",
]

# stdlib Imports
from datetime import datetime
import json
import logging
import re
import sre_constants


from Acquisition import aq_chain
from Products.Zuul.decorators import memoize
from Products.ZenModel.MaintenanceWindowable import MaintenanceWindowable


# ZenPack Imports
# from . import jwt
from ZenPacks.zenoss.GoogleCloudPlatform import jwt

LOG = logging.getLogger('zen.GCP.utils')


def chunks(s, n):
    """Generate lists of size n from iterable s."""
    for chunk in (s[i:i + n] for i in range(0, len(s), n)):
        yield chunk


def maybe_bounded(n, minimum=None, maximum=None):
    if n is None:
        return n

    if minimum is not None:
        n = max(n, minimum)

    if maximum is not None:
        n = min(n, maximum)

    return n


def maybe_int(x=0):
    """Return same as int(x) or None of that would raise an Exception."""
    try:
        return int(x)
    except Exception:
        return None


def valid_project_id(project_id):
    if not project_id:
        return False

    return bool(re.match(r'^[a-zA-Z0-9\-\'\" \!]+$', project_id))


def valid_email_address(email_address):
    if not email_address:
        return False

    return bool(re.match(r'[^@]+@[^@]+\.[^@]+', email_address))


def valid_private_key(private_key):
    if not private_key:
        return False

    try:
        jwt.prepare_key(private_key)
    except (AttributeError, ValueError):
        # AttributeError if private_key is not a string.
        # ValueError if the contents aren't a private key.
        return False

    return True


def is_greater_timestamp(timestamp1, timestamp2):
    """ Example: 2019-05-30T16:07:27.819670Z"""
    ts1 = datetime.strptime(timestamp1, "%Y-%m-%dT%H:%M:%S.%fZ")
    ts2 = datetime.strptime(timestamp2, "%Y-%m-%dT%H:%M:%S.%fZ")

    return ts1 > ts2


# -----------------------------------------------------------------------------
# Guest Device related utilities
# -----------------------------------------------------------------------------

def guest_status_prodState_map(status):
    """
    Map the GCP instance status to Zenoss Production States.

    https://cloud.google.com/compute/docs/instances/instance-life-cycle

    Zenoss production values for device:

       [{'name': 'Production', 'value': 1000},
        {'name': 'Pre-Production', 'value': 500},
        {'name': 'Test', 'value': 400},
        {'name': 'Maintenance', 'value': 300},
        {'name': 'Decommissioned', 'value': -1}]

    """

    # Don't change any Production state for guest devices that exist!
    # Only should apply to device creation, in general.
    # Behavioud should depend what comes first, the component or device.

    status_to_provision = {'PROVISIONING': 1000,
                           'REPAIRING':     500,
                           'RUNNING':      1000,
                           'STAGING':       500,
                           'STOPPED':       200,
                           'STOPPING':      200,
                           'SUSPENDED':     100,
                           'SUSPENDING':    100,
                           'TERMINATED':     -1,        # noqa
                          }
    return status_to_provision.get(status, -1)


def find_shared_labels(regex_labels, instance_labels):
    """
    Return sorted set of labels that are regex-match between 2 sets.

    Params:
        regex_labels: list
        instance_labels: list
    Output:
        list
    """
    if not regex_labels or not instance_labels:
        return None

    # ?: indicates that re is not to create capture groups (faster).
    regex = re.compile('^(?:{})$'.format('|'.join(regex_labels)))

    matched_instance_labels = filter(regex.match, instance_labels)
    return matched_instance_labels


def find_first_shared_label(regex_labels, instance_labels):
    """
    Return a first alpha-num sorted label, shared between 2 lists of labels.
    Else return None

    Params:
        regex_labels: list
        instance_labels: list
    Output:
        string
    """
    if not regex_labels or not instance_labels:
        return

    intersect = find_shared_labels(regex_labels, instance_labels)
    if not intersect:
        return

    if len(intersect) > 1:
        LOG.debug("Multiple matches found for: %s and %s", regex_labels, instance_labels)

    return intersect[0]


@memoize
def getLabelToDeviceClassMap(gcpGuestLabels):
    """Helper to prepare the guestLabelLines provided by
    zGoogleCloudPlatformGuestLabels.

    * Keys with be regular expressions
    * Values with be path strings

    Output will look like: {label_regex: device_class}
    """
    guest_labelRx_dc = {}
    if not gcpGuestLabels:
        return guest_labelRx_dc

    for gl in gcpGuestLabels:
        try:
            label_dc = json.loads(gl)
            label_rx = label_dc.get('label').strip()
            re.compile(label_rx)
            _dc = label_dc.get('dc').strip()
            guest_labelRx_dc.update({label_rx: _dc})
        except sre_constants.error as ex:
            raise Exception('Invalid Regular Expression Guest Label: {}'.format(ex.message))
        except Exception as ex:
            LOG.debug('Malformed Guest Label-DC entry detected: %s.', ex)
    return guest_labelRx_dc


def get_device_maint_windows(device):
    """Generator which returns all maintanance windows this device is affected."""
    orgs = [device, device.location()] + device.systems() + device.groups()
    objs = [org.primaryAq() for org in orgs if org]
    for obj in objs:
        for parent_obj in aq_chain(obj):
            if isinstance(parent_obj, MaintenanceWindowable):
                for mw in parent_obj.getMaintenanceWindows():
                    yield mw


def is_device_in_active_mw(device):
    """Return True if device in active maintanance window."""
    return any(mw.isActive() for mw in get_device_maint_windows(device))
