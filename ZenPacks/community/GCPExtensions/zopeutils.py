##############################################################################
#
# Copyright (C) Zenoss, Inc. 2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Utilities requiring Zope context."""

# Default Exports - Other symbols should be considered private to the module.
__all__ = [
    "get_id",
]

# Zenoss Imports
from Products.ZenUtils.Utils import prepId


def get_id(selfLink):
    """Return a Zenoss component ID given a GCP selfLink.

    Returns None if selfLink is falsey (None, "", 0, False, etc.)

    Examples of supported selfLink formats:

    * https://www.googleapis.com/compute/v1/projects/zenoss-testing-1/zones/us-central1-a/instances/gke-cluster-1-default-pool-fc3e27a3-f54f
    * projects/469482109134/global/instanceTemplates/gke-cluster-1-default-pool-fc3e27a3

    """
    if not selfLink:
        return

    parts = selfLink.split("/")
    local_name = parts[-1]
    collection = parts[-2]
    parent_name = parts[-3]

    prefix = {
        "disks": "disk",
        "diskTypes": "diskType",
        "functions": "function",
        "images": "image",
        "instanceGroupManagers": "instanceGroupManager",
        "instanceGroups": "instanceGroup",
        "instances": "instance",
        "instanceTemplates": "instanceTemplate",
        "licenses": "license",
        "locations": "region",
        "machineTypes": "machineType",
        "networks": "network",
        "regions": "region",
        "subnetworks": "subnetwork",
        "zones": "zone",
    }.get(collection, collection.rstrip("s"))

    if prefix in {"region", "zone"}:
        return prepId("_".join((prefix, local_name)))
    else:
        return prepId("_".join((prefix, parent_name, local_name)))
