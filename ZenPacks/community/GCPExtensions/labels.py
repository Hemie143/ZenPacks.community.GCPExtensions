##############################################################################
#
# Copyright (C) Zenoss, Inc. 2019, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import logging
log = logging.getLogger('zen.GCP')

import re

from Products.AdvancedQuery import Or, And, In
from Products.ZCatalog.Catalog import CatalogError
from Products.ZCatalog.ZCatalog import manage_addZCatalog
from Products.ZenUtils import unused
from Products.ZenUtils.Utils import prepId
from Products.ZenUtils.Search import makeCaseSensitiveKeywordIndex
from Products.Zuul.interfaces import ICatalogTool
from Products.Zuul import getFacade
from zExceptions import NotFound

labelsComponent = (
    'ZenPacks.zenoss.GoogleCloudPlatform.ComputeImage.ComputeImage',
    'ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstance.ComputeInstance',
    'ZenPacks.zenoss.GoogleCloudPlatform.KubernetesCluster.KubernetesCluster',
    'ZenPacks.zenoss.GoogleCloudPlatform.ComputeSnapshot.ComputeSnapshot',
    'ZenPacks.zenoss.GoogleCloudPlatform.ComputeInstanceTemplate.ComputeInstanceTemplate',
    'ZenPacks.zenoss.GoogleCloudPlatform.ComputeDisk.ComputeDisk',
    'ZenPacks.zenoss.GoogleCloudPlatform.CloudFunction.CloudFunction',
    'ZenPacks.zenoss.GoogleCloudPlatform.StorageBucket.StorageBucket',
    'ZenPacks.zenoss.GoogleCloudPlatform.BigTableInstance',)

COMPONENT_GROUPS_ID = 'ComponentGroups'

AND_TERM = re.compile(r'\sAND\s', re.IGNORECASE)
OR_TERM = re.compile(r'\sOR\s', re.IGNORECASE)


def get_labels_catalog(device):
    """
    Returns or creates GCP labels catalog.
    """
    try:
        return device.labelsCatalog
    except AttributeError:
        return create_labels_catalog(device)


def get_labels_for_device(device):
    """
    Returns list of unique labels for given GCP Project.
    """
    return get_labels_catalog(device).uniqueValuesFor('labels')


def create_labels_catalog(device):
    """
    Creates catalog under GoogleCloudPlatform to search components by GCP label.
    """

    catalog_name = 'labelsCatalog'

    if not hasattr(device, catalog_name):
        log.info('Creating GCP Labels catalog for %s', device.id)
        manage_addZCatalog(device, catalog_name, catalog_name)

        zcatalog = device._getOb(catalog_name)
        catalog = zcatalog._catalog

        try:
            catalog.addIndex('labels', makeCaseSensitiveKeywordIndex('labels'))
        except CatalogError:
            # Index already exists.
            pass
        else:
            log.info('Reindexing all GCP components')
            brains = ICatalogTool(device).search((
                labelsComponent
                )
            )
            for brain in brains:
                brain.getObject().index_object()

    return zcatalog


def search_gcp_labels(device, expression):
    """
    Return components matching labels filter.
    """
    query = expression_to_query(parse_expression(expression))

    return get_labels_catalog(device).evalAdvancedQuery(query)


def create_component_group(device, label, expression):
    """
    Creates ComponentGroup if it is not exists yet.
    """
    try:
        from Products.ZenModel.ComponentGroup import ComponentGroup
    except ImportError:
        return 'Component Groups not available'

    dmd = device.dmd

    if not dmd.hasObject(COMPONENT_GROUPS_ID):
        return 'Component Groups not present in data root'

    cg_root = dmd[COMPONENT_GROUPS_ID]
    if not cg_root.hasObject("GoogleCloudPlatform"):
        obj = ComponentGroup("GoogleCloudPlatform")
        obj.isInTree = True
        cg_root._setObject("GoogleCloudPlatform", obj)
        log.debug('GCP organizer has been added to Component Group root.')

    if not cg_root.GoogleCloudPlatform.hasObject(device.id):
        obj = ComponentGroup(device.id)
        obj.isInTree = True
        cg_root.GoogleCloudPlatform._setObject(device.id, obj)
        log.debug('%s has been added to Component Group "GoogleCloudPlatform".', device.id)

    group = cg_root.GoogleCloudPlatform[device.id]
    new_id = prepId(label, subchar=" ")

    if group.hasObject(new_id):
        return 'Component Group "{}" already exists'.format(label)

    obj = ComponentGroup(new_id)
    obj.isInTree = True
    group._setObject(new_id, obj)
    log.debug('Component Group "%s" has been created.', new_id)

    for brain in search_gcp_labels(device, expression):
        try:
            comp = brain.getObject()
        except NotFound:
            continue
        else:
            group_names = set(comp.getComponentGroupNames())
            group_names.add(obj.getOrganizerName())
            comp.setComponentGroups(list(group_names))

    return 'Component Group "{}" has been created'.format(label)


def update_component_group(label_filter):
    if not label_filter.link_with_group:
        return False

    try:
        from Products.ZenModel.ComponentGroup import ComponentGroup
        unused(ComponentGroup)
    except ImportError:
        return False

    device = label_filter.device()

    label_objects_ids = set(
        brain.getPath()
        for brain in search_gcp_labels(device, label_filter.expression))

    group_id = prepId(label_filter.title, subchar=" ")
    uid = '/'.join([COMPONENT_GROUPS_ID, "GoogleCloudPlatform", device.id, group_id])

    try:
        component_group = device.dmd.getObjByPath(uid)
        component_group_name = component_group.getOrganizerName()
    except Exception:
        log.warning('Could not find linked Component Group %s', uid)
        return False

    cg_objects_ids = set(
        obj.getPrimaryId() for obj in component_group.getComponents())

    # Remove components which are not match label expression anymore.
    for obj_id in cg_objects_ids - label_objects_ids:
        try:
            obj = device.dmd.getObjByPath(obj_id)
        except Exception:
            log.warning('Could not find object: %s', obj_id)
            continue

        group_names = set(obj.getComponentGroupNames())

        if component_group_name in group_names:
            group_names.remove(component_group_name)
            obj.setComponentGroups(list(group_names))

    # Add new components.
    for obj_id in label_objects_ids - cg_objects_ids:
        try:
            obj = device.dmd.getObjByPath(obj_id)
        except Exception:
            log.warning('Could not find object: %s', obj_id)
            continue

        group_names = set(obj.getComponentGroupNames())
        group_names.add(component_group_name)
        obj.setComponentGroups(list(group_names))

    return True


def remove_component_groups(device, comps):
    '''
    Removes Component Group(s) when label Filter(s) removed.
    '''
    try:
        from Products.ZenModel.ComponentGroup import ComponentGroup
        unused(ComponentGroup)
    except ImportError:
        return 'Component Groups not available'

    try:
        group = device.dmd.getObjByPath(
            '/'.join([COMPONENT_GROUPS_ID, "GoogleCloudPlatform", device.id])
        )
    except KeyError:
        return 'Component Group {} not present'.format(device.id)

    device_facade = getFacade('device', device)

    for label in comps:
        if not label.link_with_group:
            continue
        group_id = prepId(label.title, subchar=" ")
        uid = '/'.join([COMPONENT_GROUPS_ID, "GoogleCloudPlatform", device.id, group_id])

        if group.hasObject(group_id):
            # If there is a component group for this label filter, remove
            # it, using the deviceFacade's deleteNode method (which ensures
            # that the objects are re-indexed properly, so they don't
            # remain listed as children of the containing component group
            # in the Global Catalog, even though the child component group
            # was removed)
            device_facade.deleteNode(uid=uid)

    return 'Component Groups deleted'


def labels_list(labels):
    '''
    Return list for storing in device labels' cache set
    '''
    return ['{}:{}'.format(k.strip(), labels[k].strip()) for k in labels]


def label_graph_title(tid, gid, labels):
    '''
    Compose title of Tag Filter chart, handles cases with all/multiple labels
    '''
    title = "<input type='button' onclick='Zenoss.remove_label_chart(\"{}\",\"{}\")' value='Remove' /> {} - {}".format(tid, gid, gid, labels)
    return title


def parse_expression(expression):
    """Parse Label_Filter's expression string into Abstract syntax tree for future parsing.
    >>> parse_expression('label1:val1 OR label2:val2 OR label3:val3')
    ['OR', [':', 'label1', 'val1'], [':', 'label2', 'val2'], [':', 'label3', 'val3']]
    """
    result = []

    expression = expression.strip()

    if AND_TERM.search(expression):
        result.append('AND')
        bits = AND_TERM.split(expression)
        for bit in bits:
            key, _, value = bit.partition(':')
            result.append([':', key, value])
    elif OR_TERM.search(expression):
        result.append('OR')
        bits = OR_TERM.split(expression)
        for bit in bits:
            key, _, value = bit.partition(':')
            result.append([':', key, value])
    else:
        key, _, value = expression.partition(':')
        result.extend([':', key, value])

    return result


def extract_labels_from_expression(expression):
    """Returns set of all label names used in parsed to AST expression.
    >>> extract_labels_from_expression(['OR', [':', 'label1', 'val1'],
        [':', 'label2', 'val2'],
        [':', 'label3', 'val3']])

    return value : {'label1:val1', 'label2:val2', 'label3:val3'}
    """
    if not expression:
        return set()
    if expression[0] == ':':
        return set([expression[1] + ':' + expression[2]])
    else:
        result = set()
        for sub_expr in expression[1:]:
            result.update(extract_labels_from_expression(sub_expr))
        return result


def expression_to_query(expression_ast):
    """Returns AdvancedQuery object built from expression's AST."""
    if expression_ast[0] == ':':
        return In('labels', '%s:%s' % tuple(expression_ast[1:3]))
    elif expression_ast[0] == 'AND':
        query_set = []
        for bit in expression_ast[1:]:
            query_set.append(expression_to_query(bit))
        return And(*query_set)
    elif expression_ast[0] == 'OR':
        query_set = []
        for bit in expression_ast[1:]:
            query_set.append(expression_to_query(bit))
        return Or(*query_set)
