import os
import numpy as np
import bpy


def process_depth_to_png(exr_path, output_png_path, p_min=7, p_max=92):
    if not os.path.exists(exr_path):
        print(f"File non trovato: {exr_path}")
        return False

    img = None
    new_img = None

    try:
        img = bpy.data.images.load(exr_path)
        width, height = img.size

        pixels = np.array(img.pixels[:], dtype=np.float32)

        if img.channels >= 4:
            pixels = pixels.reshape((height, width, img.channels))
            depth = pixels[:, :, 0]
        else:
            depth = pixels.reshape((height, width))

        is_finite = np.isfinite(depth)

        if not np.any(is_finite):
            print("ATTENZIONE: nessun valore finito!")
            return False

        finite_depth = depth[is_finite]

        low, high = np.percentile(finite_depth, [p_min, p_max])

        eps = 1e-8
        if high - low < eps:
            print("Range troppo piccolo → immagine piatta")
            depth_norm = np.zeros_like(depth, dtype=np.float32)
            depth_norm[~is_finite] = 1.0
        else:
            depth_clipped = np.copy(depth)
            depth_clipped[is_finite] = np.clip(depth[is_finite], low, high)

            depth_norm = np.zeros_like(depth, dtype=np.float32)
            depth_norm[is_finite] = (
                depth_clipped[is_finite] - low
            ) / (high - low)

            depth_norm[~is_finite] = 1.0

            gamma = 0.4
            depth_norm = np.power(depth_norm, gamma)

        depth_out = 1.0 - depth_norm
        depth_out = np.clip(depth_out, 0.0, 1.0)

        gray = depth_out.astype(np.float32)

        rgba = np.zeros((height, width, 4), dtype=np.float32)
        rgba[:, :, 0] = gray
        rgba[:, :, 1] = gray
        rgba[:, :, 2] = gray
        rgba[:, :, 3] = 1.0

        os.makedirs(os.path.dirname(output_png_path), exist_ok=True)

        name = "TempDepthPNG"

        if name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[name])

        new_img = bpy.data.images.new(name, width=width, height=height)
        new_img.pixels = rgba.flatten().tolist()
        new_img.filepath_raw = output_png_path
        new_img.file_format = "PNG"
        new_img.save()

        print(f"Salvato PNG depth: {output_png_path}")
        return True

    except Exception as e:
        print("Errore process_depth_to_png:", e)
        return False

    finally:
        if img and img.name in bpy.data.images:
            bpy.data.images.remove(img)

        if new_img and new_img.name in bpy.data.images:
            bpy.data.images.remove(new_img)