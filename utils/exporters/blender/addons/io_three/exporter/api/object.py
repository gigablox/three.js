import math
import mathutils
import bpy
from bpy import data, context, types
from bpy_extras.io_utils import axis_conversion
from .. import constants, logger, utilities, exceptions
from .constants import (
    MESH,
    EMPTY,
    ARMATURE,
    LAMP,
    SPOT,
    SUN,
    POINT,
    HEMI,
    AREA,
    CAMERA,
    PERSP,
    ORTHO,
    RENDER,
    NO_SHADOW,
    ZYX
)


# Blender doesn't seem to have a good way to link a mesh back to the
# objects that are instancing it, or it is bloody obvious and I haven't
# discovered yet. This manifest serves as a way for me to map a mesh
# node to the object nodes that are using it.
_MESH_MAP = {}


def _object(func):
    """

    :param func:

    """

    def inner(arg, *args, **kwargs):
        """

        :param arg:
        :param *args:
        :param **kwargs:

        """

        if isinstance(arg, types.Object):
            obj = arg
        else:
            obj = data.objects[arg]

        return func(obj, *args, **kwargs)

    return inner


def clear_mesh_map():
    """Clears the mesh map, required on initialization"""
    _MESH_MAP.clear()


def assemblies(valid_types, options):
    """

    :param valid_types:
    :param options:

    """
    logger.debug('object.assemblies(%s)', valid_types)
    for obj in data.objects:

        # rigged assets are parented under armature nodes
        if obj.parent and obj.parent.type != ARMATURE:
            continue
        if obj.parent and obj.parent.type == ARMATURE:
            logger.info('Has armature parent %s', obj.name)
        if _valid_node(obj, valid_types, options):
            yield obj.name


@_object
def cast_shadow(obj):
    """

    :param obj:

    """
    logger.debug('object.cast_shadow(%s)', obj)
    if obj.type == LAMP:
        if obj.data.type in (SPOT, SUN):
            ret = obj.data.shadow_method != NO_SHADOW
        else:
            logger.info('%s is a lamp but this lamp type does not '\
                'have supported shadows in ThreeJS', obj.name)
            ret = None
        return ret
    elif obj.type == MESH:
        mat = material(obj)
        if mat:
            return data.materials[mat].use_cast_shadows
        else:
            return False


@_object
def children(obj, valid_types):
    """

    :param obj:
    :param valid_types:

    """
    logger.debug('object.children(%s, %s)', obj, valid_types)
    for child in obj.children:
        if child.type in valid_types:
            yield child.name


@_object
def material(obj):
    """

    :param obj:

    """
    logger.debug('object.material(%s)', obj)
    try:
        return obj.material_slots[0].name
    except IndexError:
        pass

QUAT_CONVERSION = axis_conversion(from_forward='Y', from_up='Z', to_forward='Z', to_up='Y')

def __swap_quaternions(track):
    for t in track:
        a = t["value"]
        q = mathutils.Quaternion(a)
        q = (QUAT_CONVERSION*q.to_matrix()).to_quaternion()
        a[0] =-q.x
        a[1] =-q.y
        a[2] =-q.z
        a[3] =-q.w
    pass

def __swap_vector3(track):
    for t in track:
        v = t["value"]
        tmp = v[1]
        v[1] = v[2]
        v[2] = tmp
    pass

def __parse_tracked_vector(fcurves, start_index, nb_curves):
    track = []
    for xx in fcurves[start_index].keyframe_points:
        track.append({ "time": xx.co.x, "value": [xx.co.y] })

    swapFunction = __swap_vector3 if nb_curves == 3 else __swap_quaternions

    nb_curves += start_index
    start_index += 1
    while start_index < nb_curves:
        i = 0
        for xx in fcurves[start_index].keyframe_points:
            track[i]["value"].append(xx.co.y)
            i += 1
        start_index += 1
    swapFunction(track)
    return track

# trackable transform fields ( <output field>, <nb fcurve>, <type> )
TRACKABLE_FIELDS = {
    "location": ( "position", 3, "vector3" ),
    "scale": ( "scale", 3, "vector3" ),
    "rotation_euler": ( "rotation", 3, "vector3" ),
    "rotation_quaternion": ( "quaternion", 4, "quaternion" )
}

@_object
def animated_xform(obj):
    fcurves = obj.animation_data
    if not fcurves:
        return {}
    fcurves = fcurves.action.fcurves

    tracks = []
    i = 0
    nb_curves = len(fcurves)
    while i < nb_curves:
        field_info = TRACKABLE_FIELDS.get(fcurves[i].data_path)
        if field_info:
            nb_curves = field_info[1]
            tracks.append({
                constants.NAME: field_info[0],
                constants.TYPE: field_info[2],
                constants.KEYS: __parse_tracked_vector(fcurves, i, nb_curves)
            })
            i += nb_curves
        else:
            i += 1

    animation = [{
        constants.KEYFRAMES: tracks,
        constants.FPS: context.scene.render.fps,
        constants.NAME: obj.name
    }]
    return animation

@_object
def mesh(obj, options):
    """

    :param obj:
    :param options:

    """
    logger.debug('object.mesh(%s, %s)', obj, options)
    if obj.type != MESH:
        return

    for mesh_, objects in _MESH_MAP.items():
        if obj in objects:
            return mesh_
    else:
        logger.debug('Could not map object, updating manifest')
        mesh_ = extract_mesh(obj, options)
        if len(mesh_.tessfaces) is not 0:
            manifest = _MESH_MAP.setdefault(mesh_.name, [])
            manifest.append(obj)
            mesh_name = mesh_.name
        else:
            # possibly just being used as a controller
            logger.info('Object %s has no faces', obj.name)
            mesh_name = None

    return mesh_name


@_object
def name(obj):
    """

    :param obj:

    """
    return obj.name


@_object
def node_type(obj):
    """

    :param obj:

    """
    logger.debug('object.node_type(%s)', obj)
    # standard transformation nodes are inferred
    if obj.type == MESH:
        return constants.MESH.title()
    elif obj.type == EMPTY:
        return constants.OBJECT.title()

    dispatch = {
        LAMP: {
            POINT: constants.POINT_LIGHT,
            SUN: constants.DIRECTIONAL_LIGHT,
            SPOT: constants.SPOT_LIGHT,
            HEMI: constants.HEMISPHERE_LIGHT,
            AREA: constants.AREA_LIGHT,
        },
        CAMERA: {
            PERSP: constants.PERSPECTIVE_CAMERA,
            ORTHO: constants.ORTHOGRAPHIC_CAMERA
        }
    }
    try:
        return dispatch[obj.type][obj.data.type]
    except AttributeError:
        msg = 'Invalid type: %s' % obj.type
        raise exceptions.UnsupportedObjectType(msg)


def nodes(valid_types, options):
    """

    :param valid_types:
    :param options:

    """
    for obj in data.objects:
        if _valid_node(obj, valid_types, options):
            yield obj.name

@_object
def position(obj, options):
    """

    :param obj:
    :param options:

    """
    logger.debug('object.position(%s)', obj)
    vector = matrix(obj, options).to_translation()
    return (vector.x, vector.y, vector.z)


@_object
def receive_shadow(obj):
    """

    :param obj:

    """
    if obj.type == MESH:
        mat = material(obj)
        if mat:
            return data.materials[mat].use_shadows
        else:
            return False

AXIS_CONVERSION = axis_conversion(to_forward='Z', to_up='Y').to_4x4()

@_object
def matrix(obj, options):
    """

    :param obj:
    :param options:

    """
    logger.debug('object.matrix(%s)', obj)
    if options.get(constants.HIERARCHY, False) and obj.parent:
        parent_inverted = obj.parent.matrix_world.inverted(mathutils.Matrix())
        return parent_inverted * obj.matrix_world
    else:
        return AXIS_CONVERSION * obj.matrix_world


@_object
def rotation(obj, options):
    """

    :param obj:
    :param options:

    """
    logger.debug('object.rotation(%s)', obj)
    vector = matrix(obj, options).to_euler(ZYX)
    return (vector.x, vector.y, vector.z)


@_object
def scale(obj, options):
    """

    :param obj:
    :param options:

    """
    logger.debug('object.scale(%s)', obj)
    vector = matrix(obj, options).to_scale()
    return (vector.x, vector.y, vector.z)


@_object
def select(obj):
    """

    :param obj:

    """
    obj.select = True


@_object
def unselect(obj):
    """

    :param obj:

    """
    obj.select = False


@_object
def visible(obj):
    """

    :param obj:

    """
    logger.debug('object.visible(%s)', obj)
    return obj.is_visible(context.scene)


def extract_mesh(obj, options, recalculate=False):
    """

    :param obj:
    :param options:
    :param recalculate:  (Default value = False)

    """
    logger.debug('object.extract_mesh(%s, %s)', obj, options)
    mesh_node = obj.to_mesh(context.scene, True, RENDER)

    # transfer the geometry type to the extracted mesh
    mesh_node.THREE_geometry_type = obj.data.THREE_geometry_type

    # now determine whether or not to export using the geometry type
    # set globally from the exporter's options or to use the local
    # override on the mesh node itself
    opt_buffer = options.get(constants.GEOMETRY_TYPE)
    opt_buffer = opt_buffer == constants.BUFFER_GEOMETRY
    prop_buffer = mesh_node.THREE_geometry_type == constants.BUFFER_GEOMETRY

    bpy.context.scene.objects.active = obj

    # if doing buffer geometry it is imperative to triangulate the mesh
    if opt_buffer or prop_buffer:
        original_mesh = obj.data
        obj.data = mesh_node
        logger.debug('swapped %s for %s',
                     original_mesh.name,
                     mesh_node.name)

        hidden_state = obj.hide
        obj.hide = False
        bpy.ops.object.mode_set(mode='OBJECT')
        obj.select = True
        bpy.context.scene.objects.active = obj
        logger.info('Applying triangulation to %s', obj.data.name)
        bpy.ops.object.modifier_add(type='TRIANGULATE')
        bpy.ops.object.modifier_apply(apply_as='DATA',
                                      modifier='Triangulate')
        obj.data = original_mesh
        obj.select = False
        obj.hide = hidden_state

    # recalculate the normals to face outwards, this is usually
    # best after applying a modifiers, especialy for something
    # like the mirror
    if recalculate:
        logger.info('Recalculating normals')
        original_mesh = obj.data
        obj.data = mesh_node

        bpy.context.scene.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.normals_make_consistent()
        bpy.ops.object.editmode_toggle()

        obj.data = original_mesh

    if not options.get(constants.SCENE):
        xrot = mathutils.Matrix.Rotation(-math.pi/2, 4, 'X')
        mesh_node.transform(xrot * obj.matrix_world)

    # blend shapes
    if options.get(constants.BLEND_SHAPES) and not options.get(constants.MORPH_TARGETS):
        original_mesh = obj.data
        if original_mesh.shape_keys:
            logger.info('Using blend shapes')
            obj.data = mesh_node  # swap to be able to add the shape keys
            shp = original_mesh.shape_keys

            animCurves = shp.animation_data
            if animCurves:
                animCurves = animCurves.action.fcurves

            src_kbs = shp.key_blocks
            for key in src_kbs.keys():
                logger.info("-- Parsing key %s", key)
                obj.shape_key_add(name=key, from_mix=False)
                src_kb = src_kbs[key].data
                if key == 'Basis':
                    dst_kb = mesh_node.vertices
                else:
                    dst_kb = mesh_node.shape_keys.key_blocks[key].data
                for idx in range(len(src_kb)):
                    dst_kb[idx].co = src_kb[idx].co

                if animCurves:
                    data_path = 'key_blocks["'+key+'"].value'
                    for fcurve in animCurves:
                        if fcurve.data_path == data_path:
                            dst_kb = mesh_node.shape_keys.key_blocks[key]
                            for xx in fcurve.keyframe_points:
                                dst_kb.value = xx.co.y
                                dst_kb.keyframe_insert("value",frame=xx.co.x)
                            pass
                            break  # no need to continue to loop
                    pass
            obj.data = original_mesh

    # now generate a unique name
    index = 0
    while True:
        if index is 0:
            mesh_name = '%sGeometry' % obj.data.name
        else:
            mesh_name = '%sGeometry.%d' % (obj.data.name, index)
        try:
            data.meshes[mesh_name]
            index += 1
        except KeyError:
            break
    mesh_node.name = mesh_name

    mesh_node.update(calc_tessface=True)
    mesh_node.calc_normals()
    mesh_node.calc_tessface()
    scale_ = options.get(constants.SCALE, 1)
    mesh_node.transform(mathutils.Matrix.Scale(scale_, 4))

    return mesh_node


def objects_using_mesh(mesh_node):
    """

    :param mesh_node:
    :return: list of object names

    """
    logger.debug('object.objects_using_mesh(%s)', mesh_node)
    for mesh_name, objects in _MESH_MAP.items():
        if mesh_name == mesh_node.name:
            return objects
    else:
        logger.warning('Could not find mesh mapping')


def prep_meshes(options):
    """Prep the mesh nodes. Preperation includes identifying:
        - nodes that are on visible layers
        - nodes that have export disabled
        - nodes that have modifiers that need to be applied

    :param options:

    """
    logger.debug('object.prep_meshes(%s)', options)
    mapping = {}

    visible_layers = _visible_scene_layers()

    for obj in data.objects:
        if obj.type != MESH:
            continue

        # this is ideal for skipping controller or proxy nodes
        # that may apply to a Blender but not a 3js scene
        if not _on_visible_layer(obj, visible_layers):
            logger.info('%s is not on a visible layer', obj.name)
            continue

        # if someone really insists on a visible node not being exportable
        if not obj.THREE_export:
            logger.info('%s export is disabled', obj.name)
            continue

        # need to apply modifiers before moving on, and before
        # handling instancing. it is possible for 2 or more objects
        # instance the same mesh but to not all use the same modifiers
        # this logic identifies the object with modifiers and extracts
        # the mesh making the mesh unique to this particular object
        if len(obj.modifiers):
            logger.info('%s has modifiers' % obj.name)
            mesh_node = extract_mesh(obj, options, recalculate=True)
            _MESH_MAP[mesh_node.name] = [obj]
            continue

        logger.info('adding mesh %s.%s to prep',
                    obj.name, obj.data.name)
        manifest = mapping.setdefault(obj.data.name, [])
        manifest.append(obj)

    # now associate the extracted mesh node with all the objects
    # that are instancing it
    for objects in mapping.values():
        mesh_node = extract_mesh(objects[0], options)
        _MESH_MAP[mesh_node.name] = objects


def extracted_meshes():
    """

    :return: names of extracted mesh nodes

    """
    logger.debug('object.extracted_meshes()')
    return [key for key in _MESH_MAP.keys()]


def _on_visible_layer(obj, visible_layers):
    """

    :param obj:
    :param visible_layers:

    """
    is_visible = False
    for index, layer in enumerate(obj.layers):
        if layer and index in visible_layers:
            is_visible = True
            break

    if not is_visible:
        logger.info('%s is on a hidden layer', obj.name)

    return is_visible


def _visible_scene_layers():
    """

    :return: list of visiible layer indices

    """
    visible_layers = []
    for index, layer in enumerate(context.scene.layers):
        if layer:
            visible_layers.append(index)
    return visible_layers


def _valid_node(obj, valid_types, options):
    """

    :param obj:
    :param valid_types:
    :param options:

    """
    if obj.type not in valid_types:
        return False

    # skip objects that are not on visible layers
    visible_layers = _visible_scene_layers()
    if not _on_visible_layer(obj, visible_layers):
        return False

    try:
        export = obj.THREE_export
    except AttributeError:
        export = True
    if not export:
        return False

    mesh_node = mesh(obj, options)
    is_mesh = obj.type == MESH

    # skip objects that a mesh could not be resolved
    if is_mesh and not mesh_node:
        return False

    # secondary test; if a mesh node was resolved but no
    # faces are detected then bow out
    if is_mesh:
        mesh_node = data.meshes[mesh_node]
        if len(mesh_node.tessfaces) is 0:
            return False

    # if we get this far assume that the mesh is valid
    return True



