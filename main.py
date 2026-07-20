import argparse
import json
import os
import sys

script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

import bpy
from camera_utils import add_random_street_camera
from hdr import apply_hdr
from segmentation_utils import (
    apply_segmentation,
    restore_material_assignments,
    reset_object_segmentation_state,
    enter_fast_segmentation_render_mode,
    exit_fast_segmentation_render_mode,
)
from depth_utils import process_depth_to_png


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
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.resolution_percentage = 100

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
        seed=2,  #1,2
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
    # RENDER DEPTH EXR FRAME-BY-FRAME
    # -------------------------------------------------
    if config["render_depthmap"]:
        depth_exr_dir = os.path.abspath(
            os.path.join(config["output_folder"], "depth_exr", f"run_{run_index:03d}")
        )
        depth_png_dir = os.path.abspath(
            os.path.join(config["output_folder"], "depth_png", f"run_{run_index:03d}")
        )
        depth_mp4_dir = os.path.abspath(
            os.path.join(config["output_folder"], "depth")
        )

        os.makedirs(depth_exr_dir, exist_ok=True)
        os.makedirs(depth_png_dir, exist_ok=True)
        os.makedirs(depth_mp4_dir, exist_ok=True)

        bpy.context.view_layer.use_pass_z = True

        nodes.clear()

        rl = nodes.new(type="CompositorNodeRLayers")
        rl.layer = bpy.context.view_layer.name

        out_depth = nodes.new(type="CompositorNodeOutputFile")
        out_depth.base_path = depth_exr_dir
        out_depth.format.file_format = "OPEN_EXR"
        out_depth.format.color_mode = "BW"
        out_depth.format.color_depth = "32"
        out_depth.format.exr_codec = "ZIP"
        out_depth.file_slots[0].path = "depth_"

        links.new(rl.outputs["Depth"], out_depth.inputs[0])

        print("Rendering DEPTH EXR + conversione PNG...")

        total_frames = scene.frame_end - scene.frame_start + 1

        for frame_number, frame in enumerate(
            range(scene.frame_start, scene.frame_end + 1),
            start=1,
        ):
            print(
                f"[depth] frame {frame_number}/{total_frames}",
                flush=True,
            )
            scene.frame_set(frame)

            bpy.ops.render.render(write_still=False)

            exr_path = os.path.join(
                depth_exr_dir,
                f"depth_{frame:04d}.exr"
            )

            png_path = os.path.join(
                depth_png_dir,
                f"depth_{frame:04d}.png"
            )

            process_depth_to_png(
                exr_path,
                png_path,
                p_min=7,
                p_max=92
            )

        # -------------------------------------------------
        # CREA MP4 DEPTH DA PNG USANDO BLENDER, NON FFMPEG ESTERNO
        # -------------------------------------------------
        print("Creazione DEPTH MP4 da sequenza PNG tramite Blender VSE...")

        if scene.sequence_editor is not None:
            scene.sequence_editor_clear()

        seq_editor = scene.sequence_editor_create()

        if seq_editor is None:
            raise RuntimeError("Impossibile creare il Sequence Editor")

        first_png = os.path.join(
            depth_png_dir,
            f"depth_{scene.frame_start:04d}.png"
        )

        if not os.path.exists(first_png):
            raise FileNotFoundError(f"Frame depth iniziale mancante: {first_png}")

        strip = seq_editor.sequences.new_image(
            name="DepthSequence",
            filepath=first_png,
            channel=1,
            frame_start=scene.frame_start
        )

        for frame in range(scene.frame_start + 1, scene.frame_end + 1):
            filename = f"depth_{frame:04d}.png"
            png_path = os.path.join(depth_png_dir, filename)

            if not os.path.exists(png_path):
                raise FileNotFoundError(f"Frame depth mancante: {png_path}")

            # IMPORTANTE: qui solo filename, NON path completo
            strip.elements.append(filename)

        strip.frame_final_duration = scene.frame_end - scene.frame_start + 1

        depth_mp4_path = os.path.join(
            depth_mp4_dir,
            f"run_{run_index:03d}.mp4"
        )

        scene.render.filepath = depth_mp4_path

        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.image_settings.color_mode = "RGB"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "PERC_LOSSLESS"
        scene.render.ffmpeg.ffmpeg_preset = "BEST"
        scene.render.ffmpeg.gopsize = 1
        scene.render.ffmpeg.use_max_b_frames = False
        scene.render.fps = 25

        scene.use_nodes = False
        scene.render.use_compositing = False
        scene.render.use_sequencer = True

        bpy.context.scene.frame_set(scene.frame_start)

        bpy.ops.render.render(animation=True)

        scene.sequence_editor_clear()

        scene.use_nodes = True
        scene.render.use_sequencer = False
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
                reset_object_segmentation_state(scene)
                exit_fast_segmentation_render_mode(scene, seg_render_state)




if __name__ == "__main__":
    main()



