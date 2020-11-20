##############################################################################
#
# Copyright (C) Zenoss, Inc. 2013-2017, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import logging

from ZenPacks.zenoss.GoogleCloudPlatform.labels import update_component_group

from . import schema

LOG = logging.getLogger("zen.GCP.ProjectDevice")


class ProjectDevice(schema.ProjectDevice):
    """
    Model class for ProjectDevice.
    """

    _v_labels_changed = False
    labels_graphs = None

    def setLastChange(self):
        super(ProjectDevice, self).setLastChange()

        # `setLastChange` is called by zenhub as a last step when anything was
        # changed to device, so check is any labels updates happened and sync
        # label Filters with linked component groups.
        if self._v_labels_changed:
            for label_filter in self.label_filters():
                update_component_group(label_filter)
            self._v_labels_changed = False

    def getGraphObjects(self, drange=None):      # pylint: disable=W0613; # noqa
        """
        Return all but not billing related graphs.
        """
        # 5.x version
        graphs = []
        for template in self.getRRDTemplates():
            if template.id != "EstimatedCharges":
                for g in template.getGraphDefs():
                    graphs.append((g, self))
        return graphs
