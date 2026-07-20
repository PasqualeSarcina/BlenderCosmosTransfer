import math
import random
import mathutils
import numpy as np
import bpy

FORBIDDEN_PREFIXES = [
    "01_NY",
    "Cube",
    "CityGen Buildings",
    "Curved Building",
    "fire_escape",
    "HR",
    "NY Trimm",
    "Roof_",
    "Tree"
]

CAR_PREFIXES = [
    "parking car",
    "body"
]


def is_forbidden_object(obj):
    if obj is None:
        return False
    name = obj.name
    for prefix in FORBIDDEN_PREFIXES:
        if name.startswith(prefix):
            return True
    return False


def get_world_bbox(obj):
    bbox_world = []
    for v in obj.bound_box:
        v_local = mathutils.Vector(v)
        v_world = obj.matrix_world @ v_local
        bbox_world.append(v_world[:])
    return np.array(bbox_world)


def is_car_object(obj):
    if obj is None:
        return False
    name = obj.name
    for prefix in CAR_PREFIXES:
        if name.startswith(prefix) or prefix in name:
            return True
    return False


def add_random_street_camera(city_plane, cam_height_range=(1.6, 22.5), max_tries=300, pose_file=None, unreal_file=None, seed=None):
    city_bbox = get_world_bbox(city_plane)
    min_x, min_y = city_bbox[:, :2].min(axis=0)
    max_x, max_y = city_bbox[:, :2].max(axis=0)
    scene = bpy.context.scene
    depsgraph = bpy.context.evaluated_depsgraph_get()

    if seed is not None:
        random.seed(seed)

    for _ in range(max_tries):
        # POSIZIONE CAMERA
        x = random.uniform(min_x, max_x)
        y = random.uniform(min_y, max_y)
        ray_origin = mathutils.Vector((x, y, city_bbox[:, 2].max() + 100.0))
        ray_dir = mathutils.Vector((0, 0, -1))
        hit, loc, normal, fi, hit_obj, _ = scene.ray_cast(depsgraph, ray_origin, ray_dir)
        if not hit:
            continue
        if is_forbidden_object(hit_obj):
            continue
        cam_height = random.uniform(*cam_height_range)
        cam_location = loc + mathutils.Vector((0, 0, cam_height))

        # ORIENTAMENTO CAMERA
        for _ in range(max_tries):
            yaw = random.uniform(0, 2 * math.pi)
            pitch = random.uniform(-0.45, -0.15)
            forward_dir = mathutils.Vector((math.cos(yaw), math.sin(yaw), math.sin(pitch))).normalized()
            # RAY CENTRALE (evita cielo / palazzi)
            hit, _, _, _, obj, _ = scene.ray_cast(depsgraph, cam_location, forward_dir, distance=120.0)
            if not hit:
                continue
            if is_forbidden_object(obj):
                continue
            # RAYCAST MULTIPLI: cerca almeno 1 auto
            num_rays = 10
            found_car = False
            for offset in np.linspace(-0.4, 0.4, num_rays):
                dir = mathutils.Vector((forward_dir.x + offset, forward_dir.y + offset, forward_dir.z)).normalized()
                hit, _, _, _, hit_obj, _ = scene.ray_cast(depsgraph, cam_location, dir, distance=120.0)
                if not hit or hit_obj is None:
                    continue
                if is_car_object(hit_obj):
                    found_car = True
                    break
            if not found_car:
                continue

            # MATRICE CAMERA
            target = cam_location + forward_dir * 30.0
            rot_quat = (target - cam_location).to_track_quat('-Z', 'Y')
            cam2world = (mathutils.Matrix.Translation(cam_location) @ rot_quat.to_matrix().to_4x4())

            # SALVATAGGIO CAMERA
            #location = cam2world.to_translation()
            #rotation_euler = cam2world.to_euler()  # radianti
            #rotation_deg = [math.degrees(a) for a in rotation_euler]
            #index=get_run_index()*N_FRAMES+bpy.context.scene.frame_current
            #pose_file.write(f"{index}, "f"{location.x:.6f}, {location.y:.6f}, {location.z:.6f}, "f"{rotation_deg[0]:.6f}, {rotation_deg[1]:.6f}, {rotation_deg[2]:.6f}\n")
            #unreal_file.write(f"{index}, "f"{location.x*100:.6f}, {location.y*(-100):.6f}, {location.z*100+1:.6f}, "f"{rotation_deg[1]:.6f}, {rotation_deg[0]-90:.6f}, {-90-rotation_deg[2]:.6f}\n")

            return cam2world

    return None
