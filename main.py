import argparse
import json
import math
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

import bpy
import mathutils
import numpy as np
from camera_utils import add_random_street_camera
from hdr import apply_hdr
from segmentation_utils import (
    apply_segmentation,
    restore_geometry_modifier_material_assignments,
    restore_geometry_node_material_assignments,
    restore_material_id_remaps,
    restore_material_assignments,
    reset_object_segmentation_state,
    enter_fast_segmentation_render_mode,
    exit_fast_segmentation_render_mode,
)
from wsm_utils import enter_wsm_mode, exit_wsm_mode


def estimate_dynamic_depth_range(scene, camera, depth_cfg):
    """Estimate one robust depth range for the whole clip without image files."""
    sample_width = int(depth_cfg.get("sample_width", 64))
    sample_height = int(depth_cfg.get("sample_height", 36))
    max_sample_frames = int(depth_cfg.get("sample_frames", 24))
    near_percentile = float(depth_cfg.get("near_percentile", 1.0))
    far_percentile = float(depth_cfg.get("far_percentile", 99.0))

    if sample_width < 2 or sample_height < 2:
        raise ValueError("depth sample_width/sample_height devono essere >= 2")
    if max_sample_frames < 1:
        raise ValueError("depth sample_frames deve essere >= 1")
    if not 0.0 <= near_percentile < far_percentile <= 100.0:
        raise ValueError(
            "depth near_percentile/far_percentile devono rispettare "
            "0 <= near < far <= 100"
        )
    if camera.data.type not in {"PERSP", "ORTHO"}:
        raise ValueError(
            "La normalizzazione depth automatica supporta camere PERSP e ORTHO"
        )

    total_frames = scene.frame_end - scene.frame_start + 1
    sample_count = min(total_frames, max_sample_frames)
    sampled_frames = np.unique(
        np.rint(
            np.linspace(scene.frame_start, scene.frame_end, sample_count)
        ).astype(np.int32)
    )

    u_values = (np.arange(sample_width, dtype=np.float32) + 0.5) / sample_width
    v_values = (np.arange(sample_height, dtype=np.float32) + 0.5) / sample_height

    original_frame = scene.frame_current
    sampled_depths = []

    try:
        for sample_index, frame in enumerate(sampled_frames, start=1):
            print(
                f"[depth auto-range] frame {sample_index}/{len(sampled_frames)} "
                f"(scene frame {int(frame)})",
                flush=True,
            )

            scene.frame_set(int(frame))
            depsgraph = bpy.context.evaluated_depsgraph_get()
            camera_world = camera.matrix_world.copy()
            world_to_camera = camera_world.inverted_safe()
            camera_rotation = camera_world.to_quaternion()

            frame_corners = camera.data.view_frame(scene=scene)
            min_x = min(corner.x for corner in frame_corners)
            max_x = max(corner.x for corner in frame_corners)
            min_y = min(corner.y for corner in frame_corners)
            max_y = max(corner.y for corner in frame_corners)
            frame_z = frame_corners[0].z

            for v in v_values:
                local_y = min_y + (max_y - min_y) * float(v)

                for u in u_values:
                    local_x = min_x + (max_x - min_x) * float(u)

                    if camera.data.type == "ORTHO":
                        local_origin = mathutils.Vector((local_x, local_y, 0.0))
                        ray_origin = camera_world @ local_origin
                        local_direction = mathutils.Vector((0.0, 0.0, -1.0))
                    else:
                        ray_origin = camera_world.translation
                        local_direction = mathutils.Vector(
                            (local_x, local_y, frame_z)
                        ).normalized()

                    ray_direction = (
                        camera_rotation @ local_direction
                    ).normalized()
                    ray_distance = camera.data.clip_end

                    if camera.data.type == "PERSP":
                        ray_distance /= max(-local_direction.z, 1e-6)

                    hit, location, _, _, _, _ = scene.ray_cast(
                        depsgraph,
                        ray_origin,
                        ray_direction,
                        distance=ray_distance,
                    )

                    if not hit:
                        continue

                    camera_point = world_to_camera @ location
                    depth = -camera_point.z

                    if (
                        math.isfinite(depth)
                        and camera.data.clip_start < depth < camera.data.clip_end
                    ):
                        sampled_depths.append(depth)
    finally:
        scene.frame_set(original_frame)

    if len(sampled_depths) < 2:
        raise RuntimeError(
            "Normalizzazione depth automatica fallita: superfici valide insufficienti"
        )

    depth_values = np.asarray(sampled_depths, dtype=np.float32)
    near, far = np.percentile(
        depth_values,
        [near_percentile, far_percentile],
    )
    near = float(near)
    far = float(far)

    if not math.isfinite(near) or not math.isfinite(far) or far <= near:
        raise RuntimeError(
            f"Range depth automatico non valido: near={near}, far={far}"
        )

    print(
        "Depth auto-range globale: "
        f"near={near:.3f}, far={far:.3f}, "
        f"percentili={near_percentile:g}-{far_percentile:g}, "
        f"campioni={len(depth_values)}"
    )

    return near, far


def build_depth_compositor(nodes, links, render_layers, near, far, gamma):
    """Map metric Z depth to a stable, Depth-Anything-like inverse depth."""
    depth_socket = render_layers.outputs["Depth"]

    valid = nodes.new(type="CompositorNodeMath")
    valid.operation = "GREATER_THAN"
    valid.inputs[1].default_value = 0.0
    links.new(depth_socket, valid.inputs[0])

    clamp_near = nodes.new(type="CompositorNodeMath")
    clamp_near.operation = "MAXIMUM"
    clamp_near.inputs[1].default_value = near
    links.new(depth_socket, clamp_near.inputs[0])

    clamp_far = nodes.new(type="CompositorNodeMath")
    clamp_far.operation = "MINIMUM"
    clamp_far.inputs[1].default_value = far
    links.new(clamp_near.outputs[0], clamp_far.inputs[0])

    inverse = nodes.new(type="CompositorNodeMath")
    inverse.operation = "DIVIDE"
    inverse.inputs[0].default_value = 1.0
    links.new(clamp_far.outputs[0], inverse.inputs[1])

    subtract_far = nodes.new(type="CompositorNodeMath")
    subtract_far.operation = "SUBTRACT"
    subtract_far.inputs[1].default_value = 1.0 / far
    links.new(inverse.outputs[0], subtract_far.inputs[0])

    normalize = nodes.new(type="CompositorNodeMath")
    normalize.operation = "MULTIPLY"
    normalize.inputs[1].default_value = 1.0 / ((1.0 / near) - (1.0 / far))
    links.new(subtract_far.outputs[0], normalize.inputs[0])

    clamp_min = nodes.new(type="CompositorNodeMath")
    clamp_min.operation = "MAXIMUM"
    clamp_min.inputs[1].default_value = 0.0
    links.new(normalize.outputs[0], clamp_min.inputs[0])

    clamp_max = nodes.new(type="CompositorNodeMath")
    clamp_max.operation = "MINIMUM"
    clamp_max.inputs[1].default_value = 1.0
    links.new(clamp_min.outputs[0], clamp_max.inputs[0])

    current_socket = clamp_max.outputs[0]

    if gamma != 1.0:
        gamma_node = nodes.new(type="CompositorNodeMath")
        gamma_node.operation = "POWER"
        gamma_node.inputs[1].default_value = gamma
        links.new(current_socket, gamma_node.inputs[0])
        current_socket = gamma_node.outputs[0]

    apply_valid_mask = nodes.new(type="CompositorNodeMath")
    apply_valid_mask.operation = "MULTIPLY"
    links.new(current_socket, apply_valid_mask.inputs[0])
    links.new(valid.outputs[0], apply_valid_mask.inputs[1])

    composite = nodes.new(type="CompositorNodeComposite")
    links.new(apply_valid_mask.outputs[0], composite.inputs["Image"])


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path al file json di configurazione"
    )

    parser.add_argument(
        "--run-index",
        type=int,
        default=0,
        help="Indice run (default: 0)"
    )

    return parser.parse_args(sys.argv[sys.argv.index("--") + 1:])

def main():
    args = parse_args()

    run_index = args.run_index

    with open(args.config, "r", encoding="utf-8") as f:
        config = json.load(f)

    scene = bpy.context.scene

    scene.render.engine = config["render_engine"]
    scene.use_nodes = True
    scene.render.use_compositing = True

    scene.frame_start = 1
    scene.frame_end = config["n_frames"]

    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "PERC_LOSSLESS"
    scene.render.ffmpeg.ffmpeg_preset = "BEST"
    scene.render.ffmpeg.gopsize = 1
    scene.render.ffmpeg.use_max_b_frames = False
    scene.render.fps = 25
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.use_sequencer = False

    hdri_path = os.path.abspath(
        os.path.join("hdri_data", "sunflowers_puresky_4k.hdr")
    )
    apply_hdr(hdri_path, scene)

    city_plane = bpy.data.objects.get("City_Generator_2.0_Object")
    if city_plane is None:
        raise RuntimeError(
            "Object 'City_Generator_2.0_Object' not found in the scene"
        )

    camera = scene.camera
    if camera is None:
        camera_data = bpy.data.cameras.new(name="Camera")
        camera = bpy.data.objects.new(name="Camera", object_data=camera_data)
        scene.collection.objects.link(camera)
        scene.camera = camera

    print("Renders output path:", config["output_folder"])

    # -------------------------------------------------
    # CAMERA FISSA PER TUTTA L'ANIMAZIONE
    # -------------------------------------------------
    if camera.animation_data is not None:
        camera.animation_data_clear()

    for constraint in list(camera.constraints):
        camera.constraints.remove(constraint)

    scene.frame_set(scene.frame_start)

    cam2world = add_random_street_camera(
        city_plane=city_plane,
        seed=4,  #1,2
    )

    if cam2world is None:
        raise RuntimeError("Impossibile generare una camera valida")

    camera.matrix_world = cam2world
    scene.camera = camera

    tree = scene.node_tree
    nodes = tree.nodes
    links = tree.links

    # -------------------------------------------------
    # RENDER RGB MP4
    # -------------------------------------------------
    rgb_dir = os.path.abspath(
        os.path.join(config["output_folder"], "rgb")
    )
    os.makedirs(rgb_dir, exist_ok=True)

    scene.render.filepath = os.path.join(
        rgb_dir,
        f"run_{run_index:03d}.mp4"
    )

    nodes.clear()

    rl = nodes.new(type="CompositorNodeRLayers")
    rl.layer = bpy.context.view_layer.name

    comp_node = nodes.new(type="CompositorNodeComposite")
    links.new(rl.outputs["Image"], comp_node.inputs["Image"])

    bpy.ops.render.render(animation=True)

    # -------------------------------------------------
    # RENDER WORLD SCENARIO MAP MP4
    # -------------------------------------------------
    if config.get("render_wsm", False):
        wsm_config = config.get("wsm")
        if wsm_config is None:
            raise ValueError(
                "render_wsm e' true ma la sezione 'wsm' non esiste"
            )

        wsm_dir = os.path.abspath(
            os.path.join(config["output_folder"], "wsm")
        )
        os.makedirs(wsm_dir, exist_ok=True)

        wsm_render_state = {
            "filepath": scene.render.filepath,
            "file_format": scene.render.image_settings.file_format,
            "color_mode": scene.render.image_settings.color_mode,
            "frame": scene.frame_current,
        }
        wsm_state = None

        try:
            wsm_state = enter_wsm_mode(scene, wsm_config)

            nodes.clear()
            rl = nodes.new(type="CompositorNodeRLayers")
            rl.layer = bpy.context.view_layer.name
            comp_node = nodes.new(type="CompositorNodeComposite")
            links.new(rl.outputs["Image"], comp_node.inputs["Image"])

            scene.frame_set(scene.frame_start)
            scene.render.image_settings.file_format = "FFMPEG"
            scene.render.image_settings.color_mode = "RGB"
            scene.render.ffmpeg.format = "MPEG4"
            scene.render.ffmpeg.codec = "H264"
            scene.render.ffmpeg.constant_rate_factor = "PERC_LOSSLESS"
            scene.render.ffmpeg.ffmpeg_preset = "BEST"
            scene.render.ffmpeg.gopsize = 1
            scene.render.ffmpeg.use_max_b_frames = False
            scene.render.filepath = os.path.join(
                wsm_dir,
                f"run_{run_index:03d}.mp4",
            )

            print("Rendering WSM:", scene.render.filepath)
            bpy.ops.render.render(animation=True)

        finally:
            if wsm_state is not None:
                exit_wsm_mode(scene, wsm_state)

            scene.render.filepath = wsm_render_state["filepath"]
            scene.render.image_settings.file_format = (
                wsm_render_state["file_format"]
            )
            scene.render.image_settings.color_mode = (
                wsm_render_state["color_mode"]
            )
            scene.frame_set(wsm_render_state["frame"])

    # -------------------------------------------------
    # RENDER DEPTH DIRETTAMENTE IN MP4
    # -------------------------------------------------
    if config.get("render_depthmap", False):
        depth_mp4_dir = os.path.abspath(
            os.path.join(config["output_folder"], "depth")
        )

        os.makedirs(depth_mp4_dir, exist_ok=True)

        depth_cfg = config.get("depth_normalization", {})
        depth_gamma = float(depth_cfg.get("gamma", 0.65))
        if depth_gamma <= 0.0:
            raise ValueError("depth_normalization.gamma deve essere > 0")

        depth_mode = depth_cfg.get("mode", "auto")

        if depth_mode == "auto":
            try:
                depth_near, depth_far = estimate_dynamic_depth_range(
                    scene,
                    camera,
                    depth_cfg,
                )
            except RuntimeError as error:
                if "near" not in depth_cfg or "far" not in depth_cfg:
                    raise

                depth_near = float(depth_cfg["near"])
                depth_far = float(depth_cfg["far"])
                print(
                    "ATTENZIONE: auto-range depth fallito; "
                    f"uso fallback near={depth_near}, far={depth_far}. "
                    f"Motivo: {error}"
                )
        elif depth_mode == "fixed":
            depth_near = float(depth_cfg.get("near", 15.0))
            depth_far = float(depth_cfg.get("far", 110.0))
        else:
            raise ValueError(
                "depth_normalization.mode deve essere 'auto' oppure 'fixed'"
            )

        if depth_near <= 0.0:
            raise ValueError("depth_normalization.near deve essere > 0")
        if depth_far <= depth_near:
            raise ValueError(
                "depth_normalization.far deve essere maggiore di near"
            )

        bpy.context.view_layer.use_pass_z = True

        nodes.clear()

        rl = nodes.new(type="CompositorNodeRLayers")
        rl.layer = bpy.context.view_layer.name

        build_depth_compositor(
            nodes,
            links,
            rl,
            near=depth_near,
            far=depth_far,
            gamma=depth_gamma,
        )

        depth_mp4_path = os.path.join(
            depth_mp4_dir,
            f"run_{run_index:03d}.mp4"
        )

        scene.render.filepath = depth_mp4_path

        previous_crf = scene.render.ffmpeg.constant_rate_factor

        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.image_settings.color_mode = "RGB"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "LOSSLESS"
        scene.render.ffmpeg.ffmpeg_preset = "BEST"
        scene.render.ffmpeg.gopsize = 1
        scene.render.ffmpeg.use_max_b_frames = False
        scene.render.fps = 25

        color_state = {
            "view_transform": scene.view_settings.view_transform,
            "look": scene.view_settings.look,
            "exposure": scene.view_settings.exposure,
            "gamma": scene.view_settings.gamma,
        }

        print(
            "Rendering DEPTH MP4 diretto "
            f"(inverse depth, near={depth_near}, far={depth_far}, "
            f"gamma={depth_gamma})..."
        )

        try:
            scene.view_settings.view_transform = "Raw"
            scene.view_settings.look = "None"
            scene.view_settings.exposure = 0.0
            scene.view_settings.gamma = 1.0
            scene.render.use_sequencer = False
            scene.frame_set(scene.frame_start)
            bpy.ops.render.render(animation=True)
        finally:
            scene.view_settings.view_transform = color_state["view_transform"]
            scene.view_settings.look = color_state["look"]
            scene.view_settings.exposure = color_state["exposure"]
            scene.view_settings.gamma = color_state["gamma"]
            scene.render.ffmpeg.constant_rate_factor = previous_crf

        scene.render.use_compositing = True

    # -------------------------------------------------
    # RENDER SEGMENTAZIONI MP4
    # -------------------------------------------------
    if config.get("segmentation") is not None:
        for seg_name, seg_cfg in config["segmentation"].items():

            seg_dir = os.path.abspath(
                os.path.join(config["output_folder"], seg_name)
            )
            os.makedirs(seg_dir, exist_ok=True)

            scene.render.filepath = os.path.join(
                seg_dir,
                f"run_{run_index:03d}.mp4"
            )

            seg_render_state = enter_fast_segmentation_render_mode(scene)
            result = apply_segmentation(seg_cfg, scene)

            try:
                nodes.clear()

                rl = nodes.new(type="CompositorNodeRLayers")
                rl.layer = bpy.context.view_layer.name

                comp_node = nodes.new(type="CompositorNodeComposite")
                links.new(rl.outputs["Image"], comp_node.inputs["Image"])

                bpy.ops.render.render(animation=True)

            finally:
                restore_material_assignments(scene, result["material_snapshot"])
                restore_geometry_node_material_assignments(
                    result["geometry_node_material_snapshot"]
                )
                restore_geometry_modifier_material_assignments(
                    result["geometry_modifier_material_snapshot"]
                )
                restore_material_id_remaps(result["material_id_remaps"])
                reset_object_segmentation_state(scene)
                exit_fast_segmentation_render_mode(scene, seg_render_state)




if __name__ == "__main__":
    main()
