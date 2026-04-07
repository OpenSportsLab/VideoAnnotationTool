import os
import copy
from enum import Enum, auto


class CmdType(Enum):
    """Command types recorded in the undo/redo history."""

    # --- Classification commands ---
    ANNOTATION_CONFIRM = auto()  # Persist a user-confirmed annotation to the model
    BATCH_ANNOTATION_CONFIRM = auto() # [NEW] Persist a batch of annotations as a single action
    UI_CHANGE = auto()           # Fine-grained UI toggle (radio/checkbox changes)

    # [NEW] Smart Annotation commands for Undo/Redo
    SMART_ANNOTATION_RUN = auto()
    BATCH_SMART_ANNOTATION_RUN = auto()

    # --- Shared schema commands (used by both modes) ---
    SCHEMA_ADD_CAT = auto()      # Add a category/head
    SCHEMA_DEL_CAT = auto()      # Delete a category/head
    SCHEMA_REN_CAT = auto()      # Rename a category/head

    SCHEMA_ADD_LBL = auto()      # Add a label option under a head
    SCHEMA_DEL_LBL = auto()      # Delete a label option under a head
    SCHEMA_REN_LBL = auto()      # Rename a label option under a head

    # --- Localization commands ---
    LOC_EVENT_ADD = auto()
    LOC_EVENT_DEL = auto()
    LOC_EVENT_MOD = auto()

    DESC_EDIT = auto()  # Records text changes in Description mode

    # --- Dense Description commands ---
    DENSE_EVENT_ADD = auto()
    DENSE_EVENT_DEL = auto()
    DENSE_EVENT_MOD = auto()


class AppStateModel:
    """
    Centralized application state container.
    - Owns project metadata, schema, annotations/events, and undo/redo stacks.
    - Does not touch UI widgets (UI is managed elsewhere).
    """

    def __init__(self):
        # --- Project metadata ---
        self.current_working_directory = None
        self.current_json_path = None
        self.json_loaded = False
        self.is_data_dirty = False
        self.project_description = ""  # Keep a default to avoid missing-field issues
        self.current_task_name = "Untitled Task"
        self.modalities = ["video"]

        self.is_multi_view = False

        # --- Schema / labels ---
        # Format: { head_name: { "type": "single|multi", "labels": [..] } }
        self.label_definitions = {}

        # --- Classification data ---
        # Format: { video_path: { "Head": "Label", "Head2": ["L1", "L2"] } }
        self.manual_annotations = {}

        # [NEW] Store AI inference results to persist the Donut Chart state
        # Format: { video_path: { "action": { "label": "Dive", "conf_dict": {...} } } }
        self.smart_annotations = {}

        # Classification import metadata (kept for backward compatibility)
        self.imported_input_metadata = {}   # key: (action_id, filename)
        self.imported_action_metadata = {}  # key: action_id

        # --- Localization / action spotting data ---
        # Format: { video_path: [ { "head": ..., "label": ..., "position_ms": ... }, ... ] }
        self.localization_events = {}


        # localization-smart annotation
        self.smart_localization_events = {}

        # --- Common clip list ---
        # Each item: { "name": "...", "path": "...", "source_files": [...] }
        # This is the shared source of truth for the Project Tree
        self.action_item_data = []
        self.action_item_map = {}      # path -> QStandardItem (populated by UI layer)
        self.action_path_to_name = {}  # path -> name

        # --- Dense Description data ---
        # Format: { video_path: [ { "position_ms": ..., "lang": "en", "text": "..." }, ... ] }
        self.dense_description_events = {}

        # --- Undo/redo stacks ---
        self.undo_stack = []
        self.redo_stack = []

    def reset(self, full_reset: bool = False):
        """Reset runtime state. If full_reset is True, also clears schema and project metadata."""
        self.current_json_path = None
        self.json_loaded = False
        self.is_data_dirty = False

        self.is_multi_view = False

        self.manual_annotations = {}
        # [NEW] Clear smart annotations on reset
        self.smart_annotations = {}
        self.localization_events = {}
        self.smart_localization_events = {}

        self.imported_input_metadata = {}
        self.imported_action_metadata = {}

        self.action_item_data = []
        self.action_item_map = {}
        self.action_path_to_name = {}
        self.dense_description_events = {}

        self.undo_stack = []
        self.redo_stack = []

        if full_reset:
            self.label_definitions = {}
            self.current_working_directory = None
            self.current_task_name = "Untitled Task"
            self.project_description = ""

    def push_undo(self, cmd_type: CmdType, **kwargs):
        """Push a command onto the undo stack and clear the redo stack."""
        command = {"type": cmd_type, **kwargs}
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self.is_data_dirty = True

    # ------------------------------------------------------------
    # Shared State Helpers (used by controllers)
    # ------------------------------------------------------------
    def detect_json_type(self, data):
        """Detect supported project type from top-level task and sample fields."""
        task = str(data.get("task", "")).lower()

        if "dense" in task:
            return "dense_description"
        if "caption" in task or "description" in task:
            return "description"
        if "spotting" in task or "localization" in task:
            return "localization"
        if "classification" in task:
            return "classification"

        if "labels" in data and isinstance(data["labels"], dict):
            return "localization"

        items = data.get("data", [])
        if not items:
            return "unknown"

        first = items[0] if isinstance(items[0], dict) else {}
        if "dense_captions" in first:
            return "dense_description"

        if "events" in first:
            events = first.get("events", [])
            if events and isinstance(events, list) and isinstance(events[0], dict):
                if "text" in events[0]:
                    return "dense_description"
                if "label" in events[0]:
                    return "localization"

        if "captions" in first:
            return "description"
        if "labels" in first:
            return "classification"

        return "unknown"

    def has_action_path(self, path: str) -> bool:
        return any(d.get("path") == path for d in self.action_item_data)

    def has_action_name(self, name: str) -> bool:
        return any(d.get("name") == name for d in self.action_item_data)

    def has_description_path(self, path: str) -> bool:
        return any(
            d.get("path") == path or d.get("metadata", {}).get("path") == path
            for d in self.action_item_data
        )

    def add_action_item(self, name: str, path: str, source_files=None, **extra_fields):
        """Append a normalized action entry and update path-name lookup."""
        if source_files is None:
            normalized_sources = [path]
        else:
            normalized_sources = list(source_files)
        entry = {
            "name": name,
            "path": path,
            "source_files": normalized_sources,
        }
        entry.update(extra_fields)
        self.action_item_data.append(entry)
        self.action_path_to_name[path] = name
        return entry

    def remove_action_item_by_path(self, path: str) -> bool:
        """Remove a standard action entry keyed by path."""
        before = len(self.action_item_data)
        self.action_item_data = [d for d in self.action_item_data if d.get("path") != path]
        removed = len(self.action_item_data) != before
        self.action_path_to_name.pop(path, None)
        self.action_item_map.pop(path, None)
        self.clear_annotations_for_path(path)
        return removed

    def remove_description_action_by_path(self, path: str):
        """Remove description entry that may be keyed by path or metadata.path."""
        removed_items = []
        kept_items = []
        for item in self.action_item_data:
            item_path = item.get("path") or item.get("metadata", {}).get("path")
            if item_path == path:
                removed_items.append(item)
            else:
                kept_items.append(item)
        self.action_item_data = kept_items

        for item in removed_items:
            item_id = item.get("id") or item.get("name")
            if item_id:
                self.imported_action_metadata.pop(item_id, None)

        self.action_path_to_name.pop(path, None)
        self.action_item_map.pop(path, None)
        self.clear_annotations_for_path(path)
        return removed_items

    def clear_annotations_for_path(self, path: str):
        for store_name in (
            "manual_annotations",
            "smart_annotations",
            "localization_events",
            "smart_localization_events",
            "dense_description_events",
        ):
            store = getattr(self, store_name, None)
            if isinstance(store, dict):
                store.pop(path, None)

    def is_action_done(self, action_path: str) -> bool:
        """Return True when path has any annotation payload across modes."""
        if self.localization_events.get(action_path):
            return True
        if self.manual_annotations.get(action_path):
            return True
        if self.dense_description_events.get(action_path):
            return True

        for data in self.action_item_data:
            if data.get("path") != action_path:
                continue
            captions = data.get("captions", [])
            if any(c.get("text", "").strip() for c in captions if isinstance(c, dict)):
                return True
            break

        return False

    # ------------------------------------------------------------
    # Validation: Classification (Action Classification)
    # ------------------------------------------------------------
    def validate_gac_json(self, data):
        """
        Strict validation for Classification JSON.
        Returns: (is_valid, error_msg, warning_msg)
        """
        errors = []
        warnings = []

        # --- Top-level Structure Checks ---
        if not isinstance(data, dict):
            return False, "Root JSON must be a dictionary.", ""

        # 1. Modalities Check
        if "modalities" not in data:
            errors.append("Critical: Missing top-level key 'modalities'.")
        else:
            mods = data["modalities"]
            if not isinstance(mods, list):
                errors.append(f"Critical: 'modalities' must be a list. Found: {type(mods).__name__}")
            elif len(mods) == 0:
                errors.append("Critical: 'modalities' list is empty.")

        # 2. Labels Schema Check
        if "labels" not in data:
            errors.append("Critical: Missing top-level key 'labels'.")
        else:
            lbls_def = data["labels"]
            if not isinstance(lbls_def, dict):
                errors.append("Critical: Top-level 'labels' must be a dictionary.")
            else:
                # Check individual heads
                for head, content in lbls_def.items():
                    if not isinstance(content, dict):
                        errors.append(f"Label definition for '{head}' must be a dictionary.")
                        continue
                    
                    # Check Type
                    if "type" not in content:
                        errors.append(f"Label head '{head}' missing 'type' field.")
                    
                    # Check Labels list
                    if "labels" not in content:
                        errors.append(f"Label head '{head}' missing 'labels' list.")
                    elif not isinstance(content["labels"], list):
                        errors.append(f"Label head '{head}' 'labels' must be a list.")
                    elif len(content["labels"]) == 0:
                        # Depending on policy, an empty label list might be useless/invalid
                        errors.append(f"Label head '{head}' has an empty 'labels' list.")

        # 3. Data Items Check
        if "data" not in data:
            errors.append("Critical: Missing top-level key 'data'.")
        elif not isinstance(data["data"], list):
            errors.append("Critical: Top-level 'data' must be a list.")
        else:
            # Per-item Validation
            err_inputs_missing = []
            err_inputs_not_list = []
            err_inputs_empty = []
            err_input_path_missing = []
            err_input_type_wrong = []
            
            for i, item in enumerate(data["data"]):
                if not isinstance(item, dict):
                    errors.append(f"Item #{i} is not a dictionary.")
                    continue

                # Inputs check
                if "inputs" not in item:
                    err_inputs_missing.append(f"Item #{i}")
                    continue
                
                inputs = item["inputs"]
                if not isinstance(inputs, list):
                    err_inputs_not_list.append(f"Item #{i}")
                    continue
                
                if not inputs:
                    err_inputs_empty.append(f"Item #{i}")
                    continue

                # Check first input (Classification usually assumes 1 main video/clip)
                inp0 = inputs[0]
                if isinstance(inp0, dict):
                    if "path" not in inp0:
                        err_input_path_missing.append(f"Item #{i}")
                    if inp0.get("type") != "video":
                        err_input_type_wrong.append(f"Item #{i} type='{inp0.get('type')}'")
                else:
                    err_inputs_not_list.append(f"Item #{i} (inputs[0] not dict)")

            def _fmt(title, lst):
                if not lst: return None
                preview = "\n  ".join(lst[:5]) + ("\n  ..." if len(lst) > 5 else "")
                return f"{title} ({len(lst)}):\n  {preview}"

            crit_item_errors = [
                _fmt("Items missing 'inputs'", err_inputs_missing),
                _fmt("Items 'inputs' not a list", err_inputs_not_list),
                _fmt("Items 'inputs' empty", err_inputs_empty),
                _fmt("Items missing 'path' in input", err_input_path_missing),
                _fmt("Items input type not 'video'", err_input_type_wrong)
            ]
            
            errors.extend([e for e in crit_item_errors if e])

        if errors:
            return False, "\n\n".join(errors), ""

        return True, "", "\n".join(warnings)

    # ------------------------------------------------------------
    # Validation: Global Description / Video Captioning
    # ------------------------------------------------------------
    def validate_desc_json(self, data):
        """
        Validation for Description / Video Captioning JSON.
        Returns: (is_valid, error_msg, warning_msg)
        """
        errors = []

        # 1. Root Check
        if not isinstance(data, dict):
            return False, "Root must be a dictionary.", ""

        if "data" not in data:
            return False, "Critical: Missing top-level key 'data'.", ""

        items = data["data"]
        if not isinstance(items, list):
            return False, "Critical: 'data' must be a list.", ""

        # 2. Item Check
        err_inputs_missing = []

        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"Item #{i} is not a dictionary.")
                continue

            # Check inputs (Videos)
            if "inputs" not in item:
                err_inputs_missing.append(f"Item #{i}")
            elif not isinstance(item["inputs"], list):
                errors.append(f"Item #{i} 'inputs' must be a list.")

            # Check captions existence (soft check)
            if "captions" not in item and "labels" not in item:
                # Not hard-failing here, depends on your app policy.
                pass

        if err_inputs_missing:
            errors.append(f"Items missing 'inputs': {', '.join(err_inputs_missing[:5])}...")

        if errors:
            return False, "\n".join(errors), ""

        return True, "", f"Validated {len(items)} items for Description."

    # ------------------------------------------------------------
    # Validation: Localization / Action Spotting
    # ------------------------------------------------------------
    def validate_loc_json(self, data):
        """
        Strict validation for Localization / Action Spotting JSON.

        Returns:
            (is_valid, error_msg, warning_msg)
        """
        errors = []
        warnings = []

        # --- Top-level checks ---
        if not isinstance(data, dict):
            return False, "Root JSON must be a dictionary.", ""

        if "data" not in data:
            return False, "Critical: Missing top-level key 'data'.", ""

        if not isinstance(data["data"], list):
            return False, "Critical: Top-level 'data' must be a list.", ""

        if "labels" not in data:
            return False, "Critical: Missing top-level key 'labels'.", ""

        labels_def = data["labels"]
        if not isinstance(labels_def, dict):
            return False, "Critical: Top-level 'labels' must be a dictionary.", ""

        # --- Schema checks ---
        valid_heads = set()
        head_label_map = {}

        for head, content in labels_def.items():
            if not isinstance(content, dict):
                errors.append(f"Label definition for '{head}' must be a dictionary.")
                continue

            lbls = content.get("labels")
            if not isinstance(lbls, list):
                errors.append(f"Critical: 'labels' field for head '{head}' must be a list.")
                continue

            valid_heads.add(head)
            head_label_map[head] = set(lbls)

        if errors:
            return False, "\n".join(errors), ""

        # --- Per-item checks ---
        err_inputs_missing = []
        err_inputs_not_list = []
        err_inputs_empty = []
        err_input_type = []
        err_input_path = []
        err_input_fps = []

        err_events_missing = []
        err_events_not_list = []

        err_evt_missing_fields = []
        err_evt_unknown_head = []
        err_evt_unknown_label = []
        err_evt_pos_format = []
        err_evt_pos_neg = []

        warn_duplicates = []

        items_list = data["data"]

        for i, item in enumerate(items_list):
            if not isinstance(item, dict):
                errors.append(f"Item #{i} is not a dictionary.")
                continue

            # Inputs
            if "inputs" not in item:
                err_inputs_missing.append(f"Item #{i}")
                continue

            inputs = item["inputs"]
            if not isinstance(inputs, list):
                err_inputs_not_list.append(f"Item #{i}")
                continue

            if len(inputs) == 0:
                err_inputs_empty.append(f"Item #{i}")
                continue

            first_inp = inputs[0]
            if not isinstance(first_inp, dict):
                err_inputs_not_list.append(f"Item #{i} (inputs[0] is not a dict)")
                continue

            if first_inp.get("type") != "video":
                err_input_type.append(f"Item #{i} type='{first_inp.get('type')}'")

            if "path" not in first_inp:
                err_input_path.append(f"Item #{i}")

            fps = first_inp.get("fps")
            if fps is None or not isinstance(fps, (int, float)) or fps <= 0:
                err_input_fps.append(f"Item #{i} fps={fps}")

            # Events
            if "events" not in item:
                err_events_missing.append(f"Item #{i}")
                continue

            events = item["events"]
            if not isinstance(events, list):
                err_events_not_list.append(f"Item #{i}")
                continue

            seen_events = set()
            for j, evt in enumerate(events):
                if not isinstance(evt, dict):
                    continue

                missing_fields = []
                if "head" not in evt:
                    missing_fields.append("head")
                if "label" not in evt:
                    missing_fields.append("label")
                if "position_ms" not in evt:
                    missing_fields.append("position_ms")

                if missing_fields:
                    err_evt_missing_fields.append(f"Item #{i} Evt #{j} missing {missing_fields}")
                    continue

                head = evt["head"]
                label = evt["label"]
                pos_val = evt["position_ms"]

                if head not in valid_heads:
                    err_evt_unknown_head.append(f"Item #{i} Evt #{j} head='{head}'")
                    continue

                allowed_labels = head_label_map[head]
                if label not in allowed_labels:
                    err_evt_unknown_label.append(
                        f"Item #{i} Evt #{j} label='{label}' not in head '{head}'"
                    )
                    continue

                try:
                    pos_int = int(pos_val)
                    if pos_int < 0:
                        err_evt_pos_neg.append(f"Item #{i} Evt #{j} pos={pos_int}")
                except (ValueError, TypeError):
                    err_evt_pos_format.append(f"Item #{i} Evt #{j} pos='{pos_val}'")
                    continue

                sig = (head, label, pos_int)
                if sig in seen_events:
                    warn_duplicates.append(f"Item #{i} ({head}, {label}, {pos_val})")
                else:
                    seen_events.add(sig)

        def _fmt(title, lst):
            if not lst:
                return None
            preview = "\n  ".join(lst[:5]) + ("\n  ..." if len(lst) > 5 else "")
            return f"{title} ({len(lst)}):\n  {preview}"

        crit_errors = [
            _fmt("Data items missing 'inputs'", err_inputs_missing),
            _fmt("Data items 'inputs' is not a list", err_inputs_not_list),
            _fmt("Data items 'inputs' is empty", err_inputs_empty),
            _fmt("Inputs type is not 'video'", err_input_type),
            _fmt("Inputs missing 'path'", err_input_path),
            _fmt("Inputs FPS invalid (<= 0)", err_input_fps),
            _fmt("Data items missing 'events'", err_events_missing),
            _fmt("Data items 'events' is not a list", err_events_not_list),
            _fmt("Events missing keys (head/label/position_ms)", err_evt_missing_fields),
            _fmt("Unknown event head (not in labels)", err_evt_unknown_head),
            _fmt("Unknown event label (not in schema)", err_evt_unknown_label),
            _fmt("Position invalid format (not int)", err_evt_pos_format),
            _fmt("Position is negative", err_evt_pos_neg),
        ]

        final_errors = [e for e in crit_errors if e] + errors
        if final_errors:
            return False, "\n\n".join(final_errors), ""

        if warn_duplicates:
            warnings.append(_fmt("Duplicate events found", warn_duplicates))

        return True, "", "\n\n".join(warnings)




    # ------------------------------------------------------------
    # Validation: Global Description / Video Captioning (Strict)
    # ------------------------------------------------------------
    def validate_desc_json(self, data):
        """
        Strict validation for Description / Video Captioning JSON.
        Matches strict criteria:
        - Top level: version, date (YYYY-MM-DD), task (must be captioning), dataset_name, data (list).
        - Per Item: unique id, inputs (video), captions (list of {text/description, lang}).
        
        Returns: (is_valid, error_msg, warning_msg)
        """
        import re
        errors = []
        warnings = []

        # --- Top-level Checks ---
        if not isinstance(data, dict):
            return False, "Root JSON must be a dictionary.", ""

        # 1. Missing Task / Wrong Task
        if "task" not in data:
            errors.append("Critical: Missing top-level key 'task'.")
        else:
            task_str = str(data["task"]).lower()
            if "caption" not in task_str and "description" not in task_str:
                errors.append(f"Critical: Task '{data['task']}' is not a valid Description/Captioning task.")

        # 2. Missing Dataset Name
        if "dataset_name" not in data:
            errors.append("Critical: Missing top-level key 'dataset_name'.")

        # 3. Bad Date Format (YYYY-MM-DD)
        if "date" in data:
            date_str = str(data["date"])
            # Simple regex for YYYY-MM-DD
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                errors.append(f"Critical: Date '{date_str}' is not in YYYY-MM-DD format.")
        else:
            errors.append("Critical: Missing top-level key 'date'.")

        # 4. Data Not Array
        if "data" not in data:
            errors.append("Critical: Missing top-level key 'data'.")
        elif not isinstance(data["data"], list):
            errors.append(f"Critical: 'data' must be a list. Found: {type(data['data']).__name__}")
            return False, "\n".join(errors), "" # Stop here if data structure is wrong

        # --- Item-level Checks ---
        items = data["data"]
        
        seen_ids = set()
        err_dup_ids = []
        
        err_inputs_missing = []
        err_inputs_not_list = []
        err_input_type = []
        
        err_captions_missing = []
        err_captions_not_list = []
        
        err_cap_missing_text = []
        err_cap_empty_text = []

        for i, item in enumerate(items):
            if not isinstance(item, dict):
                errors.append(f"Item #{i} is not a dictionary.")
                continue

            # 5. Duplicate Sample ID
            # Assuming 'id' is required for strict projects, though some legacy might not have it.
            # If ID exists, check duplicates.
            if "id" in item:
                aid = str(item["id"])
                if aid in seen_ids:
                    err_dup_ids.append(aid)
                else:
                    seen_ids.add(aid)

            # 6. Missing Inputs / Not Array
            if "inputs" not in item:
                err_inputs_missing.append(f"Item #{i}")
            elif not isinstance(item["inputs"], list):
                err_inputs_not_list.append(f"Item #{i}")
            elif len(item["inputs"]) > 0:
                # 7. Input Type Not Video
                inp0 = item["inputs"][0]
                if isinstance(inp0, dict):
                    if inp0.get("type") != "video":
                        err_input_type.append(f"Item #{i} (type='{inp0.get('type')}')")
                else:
                    err_inputs_not_list.append(f"Item #{i} input[0]")

            # 8. Missing Captions / Not Array
            # Supports key "captions" (standard) or legacy keys if needed, focusing on "captions" based on your files.
            if "captions" not in item:
                err_captions_missing.append(f"Item #{i}")
            elif not isinstance(item["captions"], list):
                err_captions_not_list.append(f"Item #{i}")
            else:
                # 9. Caption Content Checks
                for c_idx, cap in enumerate(item["captions"]):
                    if not isinstance(cap, dict):
                        continue
                    
                    # Accept 'text' or 'description' or 'sentence'
                    text_val = cap.get("text", cap.get("description", cap.get("sentence")))
                    
                    if text_val is None:
                        err_cap_missing_text.append(f"Item #{i} Cap #{c_idx}")
                    elif not str(text_val).strip():
                        err_cap_empty_text.append(f"Item #{i} Cap #{c_idx}")

        # Formatting Errors
        def _fmt(title, lst):
            if not lst: return None
            preview = ", ".join(lst[:5]) + (", ..." if len(lst) > 5 else "")
            return f"{title} ({len(lst)}): {preview}"

        crit_errors = [
            _fmt("Duplicate IDs found", err_dup_ids),
            _fmt("Items missing 'inputs'", err_inputs_missing),
            _fmt("Items 'inputs' not list", err_inputs_not_list),
            _fmt("Inputs not type 'video'", err_input_type),
            _fmt("Items missing 'captions'", err_captions_missing),
            _fmt("Items 'captions' not list", err_captions_not_list),
            _fmt("Captions missing 'text' field", err_cap_missing_text),
            _fmt("Captions have empty text", err_cap_empty_text),
        ]

        final_errors = [e for e in crit_errors if e] + errors
        
        if final_errors:
            return False, "\n\n".join(final_errors), ""
            
        return True, "", "\n".join(warnings)
    
    # ------------------------------------------------------------
    # Validation: Dense Description / Dense Video Captioning
    # ------------------------------------------------------------
    def validate_dense_json(self, data):
        """
        Strict validation for Dense Description JSON (dense_video_captioning).
        Returns: (is_valid, error_msg, warning_msg)
        """
        errors = []
        warnings = []

        # --- Top-level checks ---
        if not isinstance(data, dict):
            return False, "Root JSON must be a dictionary.", ""

        if "data" not in data:
            return False, "Critical: Missing top-level key 'data'.", ""

        items = data["data"]
        if not isinstance(items, list):
            return False, "Critical: Top-level 'data' must be a list.", ""

        # --- Per-item checks ---
        err_item_not_dict = []

        err_inputs_missing = []
        err_inputs_not_list = []
        err_inputs_empty = []
        err_input0_not_dict = []
        err_input0_type = []
        err_input0_path = []
        err_input0_fps = []

        err_dense_missing = []
        err_dense_not_list = []
        err_dense_item_not_dict = []

        err_cap_missing_fields = []
        err_cap_pos_format = []
        err_cap_pos_neg = []
        err_cap_lang_missing = []
        err_cap_lang_empty = []
        err_cap_text_missing = []
        err_cap_text_empty = []

        warn_duplicates = []

        for i, item in enumerate(items):
            if not isinstance(item, dict):
                err_item_not_dict.append(f"Item #{i}")
                continue

            # inputs
            if "inputs" not in item:
                err_inputs_missing.append(f"Item #{i}")
                continue

            inputs = item["inputs"]
            if not isinstance(inputs, list):
                err_inputs_not_list.append(f"Item #{i}")
                continue

            if len(inputs) == 0:
                err_inputs_empty.append(f"Item #{i}")
                continue

            inp0 = inputs[0]
            if not isinstance(inp0, dict):
                err_input0_not_dict.append(f"Item #{i}")
                continue

            if inp0.get("type") != "video":
                err_input0_type.append(f"Item #{i} type='{inp0.get('type')}'")

            if "path" not in inp0:
                err_input0_path.append(f"Item #{i}")

            fps = inp0.get("fps")
            if fps is None or not isinstance(fps, (int, float)) or fps <= 0:
                err_input0_fps.append(f"Item #{i} fps={fps}")

            # dense_captions (required)
            if "dense_captions" not in item:
                err_dense_missing.append(f"Item #{i}")
                continue

            dense_caps = item["dense_captions"]
            if not isinstance(dense_caps, list):
                err_dense_not_list.append(f"Item #{i}")
                continue

            # Allow empty dense_captions? depends on your policy.
            # Here: empty is allowed (unannotated), but structure must be correct.
            seen = set()
            for j, cap in enumerate(dense_caps):
                if not isinstance(cap, dict):
                    err_dense_item_not_dict.append(f"Item #{i} Cap #{j}")
                    continue

                missing = []
                if "position_ms" not in cap:
                    missing.append("position_ms")
                if "lang" not in cap:
                    missing.append("lang")
                if "text" not in cap:
                    missing.append("text")

                if missing:
                    err_cap_missing_fields.append(f"Item #{i} Cap #{j} missing {missing}")
                    continue

                # position_ms
                pos_val = cap.get("position_ms")
                try:
                    pos_int = int(pos_val)
                except (ValueError, TypeError):
                    err_cap_pos_format.append(f"Item #{i} Cap #{j} pos='{pos_val}'")
                    continue

                if pos_int < 0:
                    err_cap_pos_neg.append(f"Item #{i} Cap #{j} pos={pos_int}")
                    continue

                # lang
                lang = cap.get("lang")
                if lang is None:
                    err_cap_lang_missing.append(f"Item #{i} Cap #{j}")
                elif not isinstance(lang, str):
                    err_cap_lang_missing.append(f"Item #{i} Cap #{j} lang_type={type(lang).__name__}")
                elif lang.strip() == "":
                    err_cap_lang_empty.append(f"Item #{i} Cap #{j}")

                # text
                text = cap.get("text")
                if text is None:
                    err_cap_text_missing.append(f"Item #{i} Cap #{j}")
                elif not isinstance(text, str):
                    err_cap_text_missing.append(f"Item #{i} Cap #{j} text_type={type(text).__name__}")
                elif text.strip() == "":
                    err_cap_text_empty.append(f"Item #{i} Cap #{j}")

                # duplicate warning
                sig = (pos_int, str(lang), str(text))
                if sig in seen:
                    warn_duplicates.append(f"Item #{i} duplicate (pos={pos_int}, lang={lang})")
                else:
                    seen.add(sig)

        def _fmt(title, lst):
            if not lst:
                return None
            preview = "\n  ".join(lst[:5]) + ("\n  ..." if len(lst) > 5 else "")
            return f"{title} ({len(lst)}):\n  {preview}"

        crit_errors = [
            _fmt("Data items are not dict", err_item_not_dict),

            _fmt("Data items missing 'inputs'", err_inputs_missing),
            _fmt("Data items 'inputs' is not a list", err_inputs_not_list),
            _fmt("Data items 'inputs' is empty", err_inputs_empty),
            _fmt("inputs[0] is not a dict", err_input0_not_dict),
            _fmt("inputs[0].type is not 'video'", err_input0_type),
            _fmt("inputs[0] missing 'path'", err_input0_path),
            _fmt("inputs[0] fps invalid (<= 0 or not number)", err_input0_fps),

            _fmt("Data items missing 'dense_captions'", err_dense_missing),
            _fmt("Data items 'dense_captions' is not a list", err_dense_not_list),
            _fmt("dense_captions entries not dict", err_dense_item_not_dict),

            _fmt("dense caption missing keys (position_ms/lang/text)", err_cap_missing_fields),
            _fmt("dense caption position_ms invalid format (not int)", err_cap_pos_format),
            _fmt("dense caption position_ms is negative", err_cap_pos_neg),
            _fmt("dense caption lang missing/invalid type", err_cap_lang_missing),
            _fmt("dense caption lang empty string", err_cap_lang_empty),
            _fmt("dense caption text missing/invalid type", err_cap_text_missing),
            _fmt("dense caption text empty string", err_cap_text_empty),
        ]

        final_errors = [e for e in crit_errors if e] + errors
        if final_errors:
            return False, "\n\n".join(final_errors), ""

        if warn_duplicates:
            warnings.append(_fmt("Duplicate dense captions found", warn_duplicates))

        return True, "", "\n\n".join(warnings)
