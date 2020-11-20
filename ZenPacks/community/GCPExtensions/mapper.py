##############################################################################
#
# Copyright (C) Zenoss, Inc. 2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Generic modeling support."""

# Default Exports
__all__ = [
    "DataMapper",
]

# stdlib Imports
import collections

# Third-Party Imports
import networkx

# Zenoss Imports
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap
from Products.ZenModel.Device import Device
from Products.ZenRelations.RelSchema import ToManyCont, ToOne
from Products.ZenUtils.Utils import importClass


# Only Zenoss >= 7.0 supports ObjectMap.plugin_name.
if hasattr(ObjectMap, "plugin_name"):
    FEATURE_PLUGIN_NAME = True
else:
    FEATURE_PLUGIN_NAME = False


# Public Classes

class DataMapper(object):
    plugin_name = None

    # Public Methods

    def __init__(self, plugin_name):
        self.plugin_name = plugin_name
        self.object_types = {}
        self.objects = {}
        self.delayed = {}
        self.delayed_oms = []
        self.objects_by_type = collections.defaultdict(set)

    def add(self, object_id, datum):
        obj = self.stub(object_id)

        # print('XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX')
        # print('XXX add object_id: {}'.format(object_id))
        # print('XXX add datum: {}'.format(datum))
        # print('XXX add obj: {}'.format(obj))

        object_type = self.get_object_type(object_id, datum)
        if not object_type:
            raise Exception("no type specified for %s", object_id)

        # print('XXX add object_type: {}'.format(object_type))

        obj["type"] = object_type.name
        self.objects_by_type[object_type.name].add(object_id)

        # print('XXX add objects_by_type: {}'.format(self.objects_by_type))

        if "title" in datum:
            obj["title"] = datum["title"]

        if "properties" in datum:
            for prop_name, prop_value in datum["properties"].iteritems():
                self.add_property(
                    object_id,
                    object_type,
                    prop_name,
                    prop_value)

        if "links" in datum:
            for link_name, remote_ids in datum["links"].iteritems():
                if remote_ids:
                    self.add_link(
                        object_id,
                        object_type,
                        link_name,
                        remote_ids)
        if "delay" in datum:
            # Delayed data are typically set_* methods that have to execute
            # after initial objects are created. Once identified, the delayed
            # data will be removed from the existing maps and added in a
            # new ObjectMap at the end of the datamaps.

            delay_data = {'delayed': datum.get('delay'),
                          'modname': datum.get('type')}

            self.delayed.update({object_id: delay_data})

        # print('XXX add obj2: {}'.format(obj))

    def update(self, data):
        for object_id, datum in data.iteritems():
            self.add(object_id, datum)

    def extend(self, data):
        for object_id, datum in data:
            self.add(object_id, datum)

    def remove(self, object_id):
        datum = self.objects.get(object_id)
        if datum is None:
            return

        object_type = self.get_object_type(object_id)
        if object_type:
            self.objects_by_type[object_type.name].discard(object_id)

            for link_name, remote_ids in datum["links"].iteritems():
                self.remove_link(
                    object_id,
                    object_type,
                    link_name,
                    remote_ids)

        self.objects.pop(object_id)

    def by_type(self, type_name):
        for object_id in list(self.objects_by_type.get(type_name, ())):
            yield object_id, self.objects[object_id]

    # Private Methods

    def stub(self, object_id):
        if object_id not in self.objects:
            self.objects[object_id] = {
                "type": None,
                "title": None,
                "properties": {},
                "links": collections.defaultdict(set)}

        return self.objects[object_id]

    def add_property(self, object_id, object_type, name, value):
        object_property = object_type.get_property(name)
        if not object_property:
            raise Exception(
                "invalid property name for {}: {}".format(
                    object_id, name))

        # TODO: Property type checking? Automatic coercion?
        self.objects[object_id]["properties"][name] = value

    def add_link(self, object_id, object_type, link_name, remote_ids):
        link_type = object_type.get_link_type(link_name)

        # print('GGG add_link object_id: {}'.format(object_id))
        # print('GGG add_link object_type: {}'.format(object_type))
        # print('GGG add_link link_name: {}'.format(link_name))
        # print('GGG add_link remote_ids: {}'.format(remote_ids))
        # print('GGG add_link link_type: {}'.format(link_type))

        if not link_type:
            raise Exception(
                "invalid link name for {}: {}".format(
                    object_id, link_name))

        if remote_ids is None:
            remote_ids = []
        elif isinstance(remote_ids, basestring):
            remote_ids = [remote_ids]

        # print('GGG add_link remote_ids: {}'.format(remote_ids))

        local_links = self.objects[object_id]["links"]
        local_links[link_type.local_name].update(remote_ids)

        # print('GGG add_link local_links: {}'.format(local_links))


        if not link_type.local_many:
            local_link = local_links[link_type.local_name]
            if len(local_link) > 1:
                raise Exception(
                    "too many items in to-one {} relationship for {}: {}"
                    .format(
                        link_type.local_name,
                        object_id,
                        local_link))

        for remote_id in remote_ids:
            remote_links = self.stub(remote_id)["links"]
            remote_links[link_type.remote_name].add(object_id)

            if not link_type.remote_many:
                remote_link = remote_links[link_type.remote_name]
                if len(remote_link) > 1:
                    raise Exception(
                        "too many items in to-one {} relationship for {}: {}"
                        .format(
                            link_type.remote_name,
                            remote_id,
                            remote_link))

    def remove_link(self, object_id, object_type, link_name, remote_ids):
        if not remote_ids:
            return

        link_type = object_type.get_link_type(link_name)
        remote_name = link_type.remote_name
        for remote_id in list(remote_ids):
            if link_type.local_containing:
                self.remove(remote_id)
            else:
                self.objects[remote_id]["links"][remote_name].remove(object_id)

    def get_object_type(self, object_id, datum=None):
        type_name = datum.get("type") if datum else None

        if not type_name:
            type_name = self.objects.get(object_id, {}).get("type")

        if not type_name:
            return

        if type_name not in self.object_types:
            self.object_types[type_name] = ObjectType(type_name)

        return self.object_types[type_name]

    # Private Methods: Full & Partial Modeling

    def get_objectmap(self, object_id):
        object_datum = self.objects.get(object_id)
        if not object_datum:
            raise Exception("missing data for {}".format(object_id))

        object_type = self.get_object_type(object_id, object_datum)
        if not object_type:
            return

        if object_type.device:
            # Device ObjectMaps get no id, title, compname, modname, etc.
            om = ObjectMap()
        else:
            # Component ObjectMaps need all identification information.
            om = ObjectMap(
                data={
                    "id": object_id,
                    "title": object_datum["title"],
                },
                modname=self.get_modname(object_id))

        if FEATURE_PLUGIN_NAME:
            om.plugin_name = self.plugin_name

        om.updateFromDict(object_datum["properties"])

        return om

    def get_modname(self, object_id):
        return self.objects.get(object_id, {}).get("type")

    # Private Methods: Full Modeling Only

    def get_full_datamaps(self):
        """Return list of datamaps for a complete model."""
        # TODO: Refactor this monster. There must be a cleaner way.
        rm_dependencies = networkx.DiGraph()

        ids_by_path = collections.defaultdict(list)
        links_by_id = collections.defaultdict(dict)

        # print('ZZZ get_full_datamaps objects: {}'.format(self.objects))

        # Remove objects that were stubbed, but never specified.
        valid_object_ids = set()
        for object_id, datum in self.objects.items():
            if datum.get("type"):
                valid_object_ids.add(object_id)
            else:
                self.remove(object_id)

        for object_id, datum in self.objects.items():
            object_type = self.get_object_type(object_id)

            # print('ZZZ get_full_datamaps object_id: {}'.format(object_id))
            # print('ZZZ get_full_datamaps object_type: {}'.format(object_type))

            object_path = self.get_path(object_id)
            ids_by_path[object_path].append(object_id)
            rm_dependencies.add_node(object_path)

            links = self.objects.get(object_id, {}).get("links", {})
            for link_name, remote_ids in links.iteritems():

                # print('ZZZ get_full_datamaps ZZZ')
                # print('ZZZ get_full_datamaps link_name: {}'.format(link_name))
                # print('ZZZ get_full_datamaps remote_ids: {}'.format(remote_ids))

                link_type = object_type.get_link_type(link_name)

                # print('ZZZ get_full_datamaps object_type: {}'.format(object_type))
                # print('ZZZ get_full_datamaps link_type: {}'.format(link_type))

                # Prune links to nonexistent objects.
                remote_ids = remote_ids.intersection(valid_object_ids)

                # ToManyCont(ToOne)
                if link_type.local_containing:
                    if remote_ids:
                        for remote_id in remote_ids:
                            rm_dependencies.add_edge(
                                object_path,
                                self.get_path(remote_id))
                    else:
                        contained_path = (
                            "/".join(
                                x for x in (
                                    object_path[0],
                                    object_path[1],
                                    "" if object_type.device else object_id)
                                if x),
                            link_type.local_name)

                        ids_by_path[contained_path] = []

                        rm_dependencies.add_edge(
                            object_path,
                            contained_path)

                # ToMany(ToOne)
                elif link_type.local_many and not link_type.remote_many:
                    links_by_id[object_id][link_type.local_name] = set(remote_ids)
                    for remote_id in remote_ids:
                        rm_dependencies.add_edge(
                            self.get_path(remote_id),
                            object_path)

                # ToOne(ToMany) | ToOne(ToManyCont)
                elif link_type.remote_many and not link_type.local_many:
                    continue

                # ToMany(ToMany) | ToOne(ToOne)
                else:
                    object_is_descendant = False
                    for remote_id in remote_ids:
                        antecedent, descendant = sorted((
                            object_path,
                            self.get_path(remote_id)))

                        rm_dependencies.add_edge(antecedent, descendant)

                        if object_path == descendant:
                            object_is_descendant = True

                    if object_is_descendant:
                        links = links_by_id[object_id]
                        links[link_type.local_name] = set(remote_ids)

        datamaps = []

        # TODO: Handle cycles that make topological_sort fail.

        for compname, relname in networkx.topological_sort(rm_dependencies):
            oms = []

            for object_id in sorted(ids_by_path[(compname, relname)]):
                om = self.get_objectmap(object_id)
                if not om:
                    continue

                # -------------------------------------------------------------
                # Handle any delayed items.
                #
                # Delayed items are typically set_* methods on ObjectMaps that
                # specify other obects to act on. If these objects don't yes
                # exist, then the operation fails.
                #
                # To remedy this, we remove the premature property from the
                # existing ObjectMap, and allow it to be created normally.
                #
                # Afterwards we add in a stripped down ObjectMap that has
                # the set_* method to act on the newly created objects.
                # -------------------------------------------------------------
                delayed_data = self.delayed.get(object_id)
                if delayed_data and delayed_data.get('modname') == om.modname:
                    delayed_id = delayed_data.get('delayed')
                    delayed_payload = getattr(om, delayed_id, None)
                    # First create a New ObjectMap based on the old one.
                    delayed_om = ObjectMap(
                        data={
                            "id": object_id,
                            "compname": '',
                            "relname": relname,
                            delayed_id: delayed_payload,
                            "modname": om.modname,
                        },
                    )
                    delayed_om._directive = 'update'
                    self.delayed_oms.append(delayed_om)

                    # Now remove (not required but sensible) the delayed item
                    # from the original om:
                    delattr(om, delayed_id)

                # Add non-containing links.
                object_type = self.get_object_type(object_id)
                links = links_by_id.get(object_id, {})
                for link_name, remote_ids in links.iteritems():
                    link_type = object_type.get_link_type(link_name)

                    if link_type.local_many:
                        link_value = sorted(remote_ids)
                    else:
                        link_value = next(iter(remote_ids), None)

                    setattr(om, "set_{}".format(link_name), link_value)

                oms.append(om)

            if relname:
                rm = RelationshipMap(compname=compname, relname=relname)
                rm.extend(oms)
                datamaps.append(rm)
            else:
                datamaps.extend(oms)

        # Extend the datamaps with the delayed_oms, if any:
        datamaps.extend(self.delayed_oms)


        # print('ZZZ get_full_datamaps datamaps: {}'.format(datamaps))

        return datamaps

    def get_path(self, object_id):
        """Return (compname, relname) tuple for object_id."""

        # print('YYYYYY get_path object_id: {}'.format(object_id))


        if hasattr(self, "_path_cache"):
            # print('YYYYYY get_path FOUND _path_cache')
            if object_id in self._path_cache:
                return self._path_cache[object_id]
        else:
            self._path_cache = {}

        # print('YYYYYY get_path NO _path_cache')

        object_type = self.get_object_type(object_id)

        # print('YYYYYY get_path object_type: {}'.format(object_type))

        if object_type.device:
            self._path_cache[object_id] = ("", "")
        else:
            links = self.objects.get(object_id, {}).get("links", {})
            for link_name, remote_ids in links.iteritems():
                link_type = object_type.get_link_type(link_name)
                if not link_type.remote_containing:
                    continue

                parent_id = next(iter(remote_ids), None)
                if not parent_id:
                    raise Exception("no parent found for {}".format(object_id))

                parent_type = self.get_object_type(parent_id)
                parent_compname, parent_relname = self.get_path(parent_id)

                object_compname = "/".join(
                    x for x in (
                        parent_compname,
                        parent_relname,
                        "" if parent_type.device else parent_id)
                    if x)

                self._path_cache[object_id] = (
                    object_compname,
                    link_type.remote_name)

        return self._path_cache[object_id]


# Private Classes

class ObjectType(object):
    name = None
    device = None
    properties = None
    link_types = None

    def __init__(self, name):
        self.name = name

        class_ = importClass(name)

        self.device = issubclass(class_, Device)

        self.properties = {
            x["id"]
            for x in class_._properties}

        self.link_types = {
            k: LinkType(k, v)
            for k, v in class_._relations}

    def get_property(self, name):
        if 'set_' in name:
            name = name.replace('set_', '')

        if name in self.properties:
            return name

    def get_link_type(self, name):
        # print('AAAA get_link_type name: {}'.format(name))
        return self.link_types.get(name)


class LinkType(object):
    local_name = None
    remote_name = None
    local_containing = None
    remote_containing = None
    local_many = None
    remote_many = None

    def __init__(self, name, relschema):
        self.local_name = name
        self.remote_name = relschema.remoteName

        if isinstance(relschema, ToManyCont):
            self.local_containing = True
        else:
            self.local_containing = False

        if issubclass(relschema.remoteType, ToManyCont):
            self.remote_containing = True
        else:
            self.remote_containing = False

        if isinstance(relschema, ToOne):
            self.local_many = False
        else:
            self.local_many = True

        if issubclass(relschema.remoteType, ToOne):
            self.remote_many = False
        else:
            self.remote_many = True
