##############################################################################
#
# Copyright (C) Zenoss, Inc. 2018-2019, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Constants used in multiple modules."""

# Default Exports - Other symbols should be considered private to the module.
__all__ = [
    "KIND_MAP",
    "PROJECT_KINDS",
    "PROJECT_GLOBAL_KINDS",
    "PROJECT_AGGREGATED_KINDS",
    "REGION_KINDS",
    "ZONE_KINDS",
    "KUBERNETES_KINDS",
    "CLOUD_FUNCTION_KINDS",
]


KIND_MAP = {
    "compute#disk": "disks",
    "compute#diskType": "diskTypes",
    "compute#image": "images",
    "compute#instance": "instances",
    "compute#instanceGroup": "instanceGroups",
    "compute#instanceGroupManager": "instanceGroupManagers",
    "compute#instanceTemplate": "instanceTemplates",
    "compute#machineType": "machineTypes",
    "compute#project": "project",
    "compute#snapshot": "snapshots",
    "compute#region": "regions",
    "compute#zone": "zones",
}

PROJECT_KINDS = (
    "compute#region",
    "compute#zone",
)

PROJECT_GLOBAL_KINDS = (
    "compute#image",
    "compute#instanceTemplate",
    "compute#snapshot",
)

PROJECT_AGGREGATED_KINDS = (
    "compute#disk",
    "compute#diskType",
    "compute#instance",
    "compute#instanceGroup",
    "compute#machineType",
)

REGION_KINDS = (
    "compute#instanceGroup",
    "compute#instanceGroupManager",
)

ZONE_KINDS = (
    "compute#disk",
    "compute#diskType",
    "compute#instance",
    "compute#instanceGroup",
    "compute#instanceGroupManager",
    "compute#machineType",
)

KUBERNETES_KINDS = (
    "kubernetes#cluster",
    "kubernetes#nodePool",
)

CLOUD_FUNCTION_KINDS = (
    "cloud#function",
)

