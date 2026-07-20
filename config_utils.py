import json
from jsonschema import validate, ValidationError

CONFIG_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "n_frames",
        "output_folder",
        "render_engine",
        "blender_exe_path",
        "blend_input_file",
    ],
    "properties": {
        "blender_exe_path": {
            "type": "string",
            "minLength": 1
        },
        "blend_input_file": {
            "type": "string",
            "minLength": 1
        },
        "n_frames": {
            "type": "integer",
            "minimum": 1
        },
        "output_folder": {
            "type": "string",
            "minLength": 1
        },
        "render_engine": {
            "type": "string",
            "minLength": 1
        },
        "render_depthmap": {
            "type": "boolean",
            "default": False
        },
        "depth_normalization": {
            "$ref": "#/$defs/depth_normalization"
        },
        "segmentation": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "$ref": "#/$defs/segmentation_block"
            }
        }
    },

    "$defs": {

        # ---------------- DEPTH ----------------
        "depth_normalization": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["auto", "fixed"]
                },
                "near": {
                    "type": "number",
                    "exclusiveMinimum": 0
                },
                "far": {
                    "type": "number",
                    "exclusiveMinimum": 0
                },
                "gamma": {
                    "type": "number",
                    "exclusiveMinimum": 0
                },
                "near_percentile": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100
                },
                "far_percentile": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100
                },
                "sample_frames": {
                    "type": "integer",
                    "minimum": 1
                },
                "sample_width": {
                    "type": "integer",
                    "minimum": 2
                },
                "sample_height": {
                    "type": "integer",
                    "minimum": 2
                }
            },
            "additionalProperties": False
        },

        # ---------------- COLOR ----------------
        "color_rule": {
            "type": "object",
            "required": ["mode"],
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["fixed", "random", "random_instance"]
                },
                "value": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 3,
                    "items": {"type": "number"}
                }
            },
            "allOf": [
                {
                    "if": {
                        "properties": {"mode": {"const": "fixed"}}
                    },
                    "then": {
                        "required": ["value"]
                    }
                },
                {
                    "if": {
                        "properties": {
                            "mode": {
                                "enum": ["random", "random_instance"]
                            }
                        }
                    },
                    "then": {
                        "not": {"required": ["value"]}
                    }
                }
            ],
            "additionalProperties": False
        },

        # ---------------- MATCH ----------------
        "object_match": {
            "type": "object",
            "properties": {
                "object_name_exact": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "object_name_contains": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "additionalProperties": False
        },

        "material_match": {
            "type": "object",
            "properties": {
                "material_name_exact": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "material_name_contains": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "additionalProperties": False
        },

        # ---------------- OBJECT CLASS ----------------
        "object_class": {
            "type": "object",
            "required": ["mode", "class_id", "match"],
            "properties": {
                "mode": {
                    "const": "object"
                },
                "class_id": {
                    "type": "integer",
                    "minimum": 0
                },
                "match": {
                    "$ref": "#/$defs/object_match"
                },
                "color": {
                    "$ref": "#/$defs/color_rule"
                }
            },
            "additionalProperties": False
        },

        # ---------------- MATERIAL CLASS ----------------
        "material_class": {
            "type": "object",
            "required": ["mode", "match", "color"],
            "properties": {
                "mode": {
                    "const": "material"
                },
                "match": {
                    "$ref": "#/$defs/material_match"
                },
                "color": {
                    "$ref": "#/$defs/color_rule"
                }
            },
            "additionalProperties": False
        },

        # ---------------- CLASS UNION ----------------
        "class_rule": {
            "oneOf": [
                {"$ref": "#/$defs/object_class"},
                {"$ref": "#/$defs/material_class"}
            ]
        },

        # ---------------- SEGMENTATION BLOCK ----------------
        "segmentation_block": {
            "type": "object",
            "required": ["classes"],
            "properties": {
                "save_yolo_det_labels": {
                    "type": "boolean",
                    "default": False
                },
                "save_yolo_seg_labels": {
                    "type": "boolean",
                    "default": False
                },
                "ignore_materials": {
                    "$ref": "#/$defs/material_match"
                },
                "classes": {
                    "type": "object",
                    "required": ["background"],
                    "properties": {
                        "background": {
                            "type": "object",
                            "required": ["color"],
                            "properties": {
                                "color": {
                                    "$ref": "#/$defs/color_rule"
                                }
                            },
                            "additionalProperties": False
                        }
                    },
                    "additionalProperties": {
                        "$ref": "#/$defs/class_rule"
                    }
                }
            },
            "additionalProperties": False
        }
    },

    "additionalProperties": False
}


def load_validate_config(cfg_path: str):
    # 1. carica config json
    with open(cfg_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 2. valida contro lo schema python
    try:
        validate(instance=config, schema=CONFIG_SCHEMA)
    except ValidationError as e:
        path = " -> ".join(str(p) for p in e.absolute_path)
        raise ValueError(
            f"Invalid config.\n"
            f"Path: {path if path else '<root>'}\n"
            f"Error: {e.message}"
        )

    # 3. ritorna config valido
    return config
