import copy

from PyQt6.QtCore import QModelIndex, QObject, pyqtSignal

from controllers.command_types import CmdType


class HistoryManager(QObject):
    """
    Canonical history + mutation engine.
    - Executes forward dataset mutations for scoped editor/explorer flows.
    - Executes undo/redo state transitions.
    """

    allItemStatusRefreshRequested = pyqtSignal()
    saveStateRefreshRequested = pyqtSignal()
    refreshUiAfterUndoRedoRequested = pyqtSignal(str, str)
    filterRefreshRequested = pyqtSignal(int, str)
    statusMessageRequested = pyqtSignal(str, str, int)
    classificationSetupRequested = pyqtSignal()
    localizationSchemaRefreshRequested = pyqtSignal()
    localizationClipEventsRefreshRequested = pyqtSignal()
    denseDisplayRequested = pyqtSignal(str)
    itemStatusRefreshRequested = pyqtSignal(str)
    datasetRestoreRequested = pyqtSignal(object, str, object, object)

    def __init__(
        self,
        model,
        tree_model,
        current_tab_index_provider,
        current_action_path_provider,
        dense_current_video_path_provider,
        current_filter_index_provider,
    ):
        super().__init__()
        self.model = model
        self.tree_model = tree_model
        self._get_current_tab_index = current_tab_index_provider
        self._get_current_action_path = current_action_path_provider
        self._get_dense_current_video_path = dense_current_video_path_provider
        self._get_current_filter_index = current_filter_index_provider
        self._is_undoing_redoing = False

    # ------------------------------------------------------------------
    # Public undo/redo
    # ------------------------------------------------------------------
    def perform_undo(self):
        if not self.model.undo_stack:
            return
        self._is_undoing_redoing = True

        cmd = self.model.undo_stack.pop()
        self.model.redo_stack.append(cmd)

        self._apply_state_change(cmd, is_undo=True)
        self.allItemStatusRefreshRequested.emit()
        self.saveStateRefreshRequested.emit()
        self._is_undoing_redoing = False

    def perform_redo(self):
        if not self.model.redo_stack:
            return
        self._is_undoing_redoing = True

        cmd = self.model.redo_stack.pop()
        self.model.undo_stack.append(cmd)

        self._apply_state_change(cmd, is_undo=False)
        self.allItemStatusRefreshRequested.emit()
        self.saveStateRefreshRequested.emit()
        self._is_undoing_redoing = False

    # ------------------------------------------------------------------
    # Forward mutation slots (editor + explorer)
    # ------------------------------------------------------------------
    def execute_classification_manual_annotation(self, sample_id: str, cleaned, show_feedback: bool = True):
        path = self._path_for_sample(sample_id)
        if not path:
            return

        old_data = copy.deepcopy(self.model.manual_annotations.get(path))
        normalized_old = old_data if old_data else None
        normalized_new = copy.deepcopy(cleaned) if cleaned else None
        if normalized_old == normalized_new:
            return

        self.model.push_undo(
            CmdType.ANNOTATION_CONFIRM,
            path=path,
            old_data=old_data,
            new_data=normalized_new,
        )

        if normalized_new:
            self.model.manual_annotations[path] = normalized_new
        else:
            self.model.manual_annotations.pop(path, None)

        title = ""
        msg = ""
        if show_feedback:
            if normalized_new:
                title, msg = "Saved", "Annotation saved."
            else:
                title, msg = "Cleared", "Annotation cleared."

        self._emit_post_mutation(
            touched_paths=[path],
            refresh_filter=True,
            status_title=title,
            status_msg=msg,
            status_duration=1000,
        )

    def execute_classification_schema_add_head(self, head: str, definition: dict):
        clean = str(head or "").strip()
        if not clean or clean in self.model.label_definitions:
            return

        self.model.push_undo(CmdType.SCHEMA_ADD_CAT, head=clean, definition=copy.deepcopy(definition))
        self.model.label_definitions[clean] = copy.deepcopy(definition)
        self._emit_post_mutation(
            refresh_schema=True,
            status_title="Head Added",
            status_msg=f"Created '{clean}'.",
        )

    def execute_classification_schema_remove_head(self, head: str):
        if not head or head not in self.model.label_definitions:
            return

        affected = {}
        for key, value in self.model.manual_annotations.items():
            if head in value:
                affected[key] = copy.deepcopy(value[head])

        self.model.push_undo(
            CmdType.SCHEMA_DEL_CAT,
            head=head,
            definition=copy.deepcopy(self.model.label_definitions[head]),
            affected_data=affected,
        )

        del self.model.label_definitions[head]
        touched_paths = []
        for key in list(affected.keys()):
            if head in self.model.manual_annotations.get(key, {}):
                del self.model.manual_annotations[key][head]
                if not self.model.manual_annotations[key]:
                    del self.model.manual_annotations[key]
            touched_paths.append(key)

        self._emit_post_mutation(
            touched_paths=touched_paths,
            refresh_schema=True,
            status_title="Head Deleted",
            status_msg=f"Removed '{head}'.",
        )

    def execute_classification_schema_add_label(self, head: str, label: str):
        if not head or head not in self.model.label_definitions:
            return

        text = str(label or "").strip()
        if not text:
            return

        labels = self.model.label_definitions[head].get("labels", [])
        if any(existing.lower() == text.lower() for existing in labels):
            return

        self.model.push_undo(CmdType.SCHEMA_ADD_LBL, head=head, label=text)
        labels.append(text)
        labels.sort()
        self._emit_post_mutation(
            refresh_schema=True,
            status_title="Label Added",
            status_msg=f"Added '{text}' to '{head}'.",
        )

    def execute_classification_schema_remove_label(self, head: str, label: str):
        if not head or head not in self.model.label_definitions:
            return

        definition = self.model.label_definitions[head]
        labels = definition.get("labels", [])
        if len(labels) <= 1 or label not in labels:
            return

        affected = {}
        for key, value in self.model.manual_annotations.items():
            if definition["type"] == "single_label" and value.get(head) == label:
                affected[key] = label
            elif definition["type"] == "multi_label" and label in value.get(head, []):
                affected[key] = copy.deepcopy(value[head])

        label_index = labels.index(label)
        self.model.push_undo(
            CmdType.SCHEMA_DEL_LBL,
            head=head,
            label=label,
            label_index=label_index,
            affected_data=affected,
        )

        labels.remove(label)
        touched_paths = []
        for key, value in self.model.manual_annotations.items():
            if definition["type"] == "single_label" and value.get(head) == label:
                value[head] = None
                touched_paths.append(key)
            elif definition["type"] == "multi_label" and label in value.get(head, []):
                current_values = [entry for entry in list(value.get(head, [])) if entry != label]
                value[head] = current_values if current_values else None
                touched_paths.append(key)

        self._emit_post_mutation(
            touched_paths=touched_paths,
            refresh_schema=True,
            status_title="Label Deleted",
            status_msg=f"Removed '{label}' from '{head}'.",
        )

    def execute_localization_head_add(self, head_name: str):
        if any(h.lower() == head_name.lower() for h in self.model.label_definitions):
            return

        definition = {"type": "single_label", "labels": []}
        self.model.push_undo(CmdType.SCHEMA_ADD_CAT, head=head_name, definition=definition)
        self.model.label_definitions[head_name] = definition
        self._emit_post_mutation(
            refresh_schema=True,
            status_title="Head Added",
            status_msg=f"Created '{head_name}'.",
        )

    def execute_localization_head_rename(self, old_name: str, new_name: str):
        if old_name == new_name:
            return
        if old_name not in self.model.label_definitions:
            return
        if any(h.lower() == new_name.lower() for h in self.model.label_definitions):
            return

        self.model.push_undo(CmdType.SCHEMA_REN_CAT, old_name=old_name, new_name=new_name)
        self.model.label_definitions[new_name] = self.model.label_definitions.pop(old_name)
        for _, events in self.model.localization_events.items():
            for evt in events:
                if evt.get("head") == old_name:
                    evt["head"] = new_name

        self._emit_post_mutation(
            refresh_schema=True,
            status_title="Head Renamed",
            status_msg="Updated events.",
        )

    def execute_localization_head_delete(self, head_name: str):
        if head_name not in self.model.label_definitions:
            return

        loc_affected = {}
        for vid_path, events in self.model.localization_events.items():
            affected_evts = [copy.deepcopy(e) for e in events if e.get("head") == head_name]
            if affected_evts:
                loc_affected[vid_path] = affected_evts

        definition = copy.deepcopy(self.model.label_definitions.get(head_name))
        self.model.push_undo(
            CmdType.SCHEMA_DEL_CAT,
            head=head_name,
            definition=definition,
            loc_affected_events=loc_affected,
        )

        if head_name in self.model.label_definitions:
            del self.model.label_definitions[head_name]
        for vid_path in list(self.model.localization_events.keys()):
            self.model.localization_events[vid_path] = [
                e for e in self.model.localization_events[vid_path] if e.get("head") != head_name
            ]

        self._emit_post_mutation(
            refresh_schema=True,
            status_title="Head Deleted",
            status_msg="Removed.",
        )

    def execute_localization_label_add(
        self,
        sample_id: str,
        head: str,
        label_name: str,
        event_position_ms: int,
        create_event: bool,
    ):
        if head not in self.model.label_definitions:
            return

        labels_list = self.model.label_definitions[head].get("labels", [])
        if any(existing.lower() == label_name.lower() for existing in labels_list):
            return

        before_json = self.model.snapshot_dataset_json()
        labels_list.append(label_name)

        touched_path = ""
        if create_event:
            touched_path = self._path_for_sample(sample_id) or ""
            if touched_path:
                new_event = {"head": head, "label": label_name, "position_ms": int(event_position_ms)}
                if touched_path not in self.model.localization_events:
                    self.model.localization_events[touched_path] = []
                self.model.localization_events[touched_path].append(new_event)

        if not self.model.push_dataset_json_replace_undo_if_changed(before_json):
            return

        self._emit_post_mutation(
            touched_paths=[touched_path] if touched_path else None,
            refresh_schema=True,
            status_title="Added",
            status_msg=f"{head}: {label_name}",
        )

    def execute_localization_label_rename(self, head: str, old_label: str, new_label: str):
        labels_list = self.model.label_definitions.get(head, {}).get("labels", [])
        if old_label not in labels_list:
            return
        if any(lbl.lower() == new_label.lower() for lbl in labels_list if lbl != old_label):
            return

        self.model.push_undo(CmdType.SCHEMA_REN_LBL, head=head, old_lbl=old_label, new_lbl=new_label)
        index = labels_list.index(old_label)
        labels_list[index] = new_label

        for _, events in self.model.localization_events.items():
            for evt in events:
                if evt.get("head") == head and evt.get("label") == old_label:
                    evt["label"] = new_label

        self._emit_post_mutation(refresh_schema=True)

    def execute_localization_label_delete(self, head: str, label: str):
        if head not in self.model.label_definitions:
            return

        loc_affected = {}
        for vid_path, events in self.model.localization_events.items():
            affected = [copy.deepcopy(e) for e in events if e.get("head") == head and e.get("label") == label]
            if affected:
                loc_affected[vid_path] = affected

        labels_list = self.model.label_definitions.get(head, {}).get("labels", [])
        label_index = labels_list.index(label) if label in labels_list else -1
        self.model.push_undo(
            CmdType.SCHEMA_DEL_LBL,
            head=head,
            label=label,
            label_index=label_index,
            loc_affected_events=loc_affected,
        )

        if label in labels_list:
            labels_list.remove(label)

        for vid_path in list(self.model.localization_events.keys()):
            events = self.model.localization_events[vid_path]
            self.model.localization_events[vid_path] = [
                e for e in events if not (e.get("head") == head and e.get("label") == label)
            ]

        self._emit_post_mutation(refresh_schema=True)

    def execute_localization_event_add(self, sample_id: str, new_event: dict):
        video_path = self._path_for_sample(sample_id)
        if not video_path:
            return

        event_copy = copy.deepcopy(new_event)
        self.model.push_undo(CmdType.LOC_EVENT_ADD, video_path=video_path, event=copy.deepcopy(event_copy))
        if video_path not in self.model.localization_events:
            self.model.localization_events[video_path] = []
        self.model.localization_events[video_path].append(event_copy)

        self._emit_post_mutation(
            touched_paths=[video_path],
            status_title="Event Created",
            status_msg=f"{event_copy.get('head')}: {event_copy.get('label')}",
        )

    def execute_localization_event_mod(self, sample_id: str, old_event: dict, new_event: dict):
        video_path = self._path_for_sample(sample_id)
        if not video_path or old_event == new_event:
            return

        events = self.model.localization_events.get(video_path, [])
        index = self._find_loc_event_index(events, old_event)
        if index < 0:
            return

        self.model.push_undo(
            CmdType.LOC_EVENT_MOD,
            video_path=video_path,
            old_event=copy.deepcopy(old_event),
            new_event=copy.deepcopy(new_event),
        )

        new_head = new_event.get("head")
        new_label = new_event.get("label")
        schema_changed = False

        if new_head and new_head not in self.model.label_definitions:
            self.model.label_definitions[new_head] = {"type": "single_label", "labels": []}
            schema_changed = True
        if new_head and new_label and new_label != "???":
            labels_list = self.model.label_definitions[new_head]["labels"]
            if not any(lbl.lower() == new_label.lower() for lbl in labels_list):
                labels_list.append(new_label)
                schema_changed = True

        events[index] = copy.deepcopy(new_event)
        self._emit_post_mutation(
            touched_paths=[video_path],
            refresh_schema=schema_changed,
            status_title="Event Updated",
            status_msg="Modified",
        )

    def execute_localization_event_delete(self, sample_id: str, _item_data: dict, event_index: int):
        video_path = self._path_for_sample(sample_id)
        if not video_path:
            return

        events = self.model.localization_events.get(video_path, [])
        if event_index < 0 or event_index >= len(events):
            return

        self.model.push_undo(
            CmdType.LOC_EVENT_DEL,
            video_path=video_path,
            event=copy.deepcopy(events[event_index]),
            event_index=event_index,
        )
        events.pop(event_index)
        self._emit_post_mutation(touched_paths=[video_path])

    def execute_sample_field_update(self, sample_id: str, field_name: str, new_value):
        if not sample_id or not field_name:
            return

        sample = self.model.get_sample(sample_id)
        if not isinstance(sample, dict):
            return

        path = self._path_for_sample(sample_id) or ""
        old_value = copy.deepcopy(sample.get(field_name))
        normalized_new = copy.deepcopy(new_value)
        if old_value == normalized_new:
            return

        self.model.push_undo(
            CmdType.SAMPLE_FIELD_EDIT,
            path=path,
            sample_id=sample_id,
            field_name=field_name,
            old_data=copy.deepcopy(old_value),
            new_data=copy.deepcopy(normalized_new),
        )
        self._set_sample_field(sample_id, field_name, normalized_new)

        self._emit_post_mutation(
            touched_paths=[path] if path else None,
            status_title="Saved",
            status_msg="Sample updated.",
        )

    def execute_sample_captions_update(self, sample_id: str, captions):
        self.execute_sample_field_update(sample_id, "captions", captions)

    def execute_dense_event_add(self, sample_id: str, new_event: dict):
        video_path = self._path_for_sample(sample_id)
        if not video_path:
            return

        event_copy = copy.deepcopy(new_event)
        self.model.push_undo(
            CmdType.DENSE_EVENT_ADD,
            video_path=video_path,
            event=copy.deepcopy(event_copy),
        )
        if video_path not in self.model.dense_description_events:
            self.model.dense_description_events[video_path] = []
        self.model.dense_description_events[video_path].append(event_copy)

        self._emit_post_mutation(
            touched_paths=[video_path],
            status_title="Added",
            status_msg="Dense description added.",
        )

    def execute_dense_event_mod(self, sample_id: str, old_event: dict, new_event: dict):
        video_path = self._path_for_sample(sample_id)
        if not video_path or old_event == new_event:
            return

        events = self.model.dense_description_events.get(video_path, [])
        try:
            idx = events.index(old_event)
        except ValueError:
            return

        self.model.push_undo(
            CmdType.DENSE_EVENT_MOD,
            video_path=video_path,
            old_event=copy.deepcopy(old_event),
            new_event=copy.deepcopy(new_event),
        )
        events[idx] = copy.deepcopy(new_event)

        self._emit_post_mutation(
            touched_paths=[video_path],
            status_title="Updated",
            status_msg="Description modified.",
        )

    def execute_dense_event_del(self, sample_id: str, item_data: dict, event_index: int):
        video_path = self._path_for_sample(sample_id)
        if not video_path:
            return

        events = self.model.dense_description_events.get(video_path, [])
        if event_index < 0 or event_index >= len(events):
            return

        self.model.push_undo(
            CmdType.DENSE_EVENT_DEL,
            video_path=video_path,
            event=copy.deepcopy(item_data),
            event_index=event_index,
        )
        events.pop(event_index)
        self._emit_post_mutation(touched_paths=[video_path])

    def execute_header_draft_update(self, draft: dict):
        if not self.model.json_loaded or not isinstance(draft, dict):
            return

        before_json = self.model.snapshot_dataset_json()
        changed = False
        for key, value in draft.items():
            if key in self.model.HEADER_EDITABLE_KEYS:
                current_value = self.model.dataset_json.get(key)
                if current_value != value:
                    self.model.dataset_json[key] = copy.deepcopy(value)
                    changed = True

        if not changed:
            return
        if not self.model.push_dataset_json_replace_undo_if_changed(before_json):
            return

        self.model._refresh_header_panel()
        self._emit_schema_refresh()
        self.saveStateRefreshRequested.emit()

    def execute_sample_id_rename(self, old_sample_id: str, requested_id: str):
        old_sample_id = str(old_sample_id or "").strip()
        requested_id = str(requested_id or "").strip()
        if not old_sample_id or not requested_id:
            return

        sample = self.model.get_sample(old_sample_id)
        if not isinstance(sample, dict):
            return

        reserved = {
            str(item.get("id"))
            for item in self.model.get_samples()
            if isinstance(item, dict) and str(item.get("id")) != old_sample_id
        }
        final_id = self.model._make_unique_sample_id(requested_id, reserved)
        if final_id == old_sample_id:
            return

        before_json = self.model.snapshot_dataset_json()
        sample["id"] = final_id
        self.model._rebuild_runtime_index()
        if not self.model.push_dataset_json_replace_undo_if_changed(before_json):
            return

        if self.model.current_selected_sample_id == old_sample_id:
            self.model.current_selected_sample_id = final_id

        self.model.populate_tree()
        entry = self.model.sample_id_to_entry.get(final_id)
        item = self.model.action_item_map.get(entry["path"]) if entry else None
        if item is not None:
            self.model.panel.tree.setCurrentIndex(item.index())

        self.model._refresh_json_preview()
        self.saveStateRefreshRequested.emit()
        self.statusMessageRequested.emit("Renamed", f"Sample id set to '{final_id}'.", 1500)

    def execute_add_samples(self, files: list):
        if not self.model.json_loaded:
            self.statusMessageRequested.emit("Warning", "Please create or load a dataset first.", 1500)
            return

        file_list = [str(path) for path in (files or []) if path]
        if not file_list:
            return

        if not self.model.current_working_directory:
            import os
            self.model.current_working_directory = os.path.dirname(file_list[0])

        before_json = self.model.snapshot_dataset_json()
        added_count = 0
        first_sample_id = None

        for source_group in self.model._group_selected_files(file_list):
            sample = self.model._build_new_sample(source_group)
            self.model.get_samples().append(sample)
            added_count += 1
            if first_sample_id is None:
                first_sample_id = sample["id"]

        if added_count <= 0:
            return

        if not self.model.push_dataset_json_replace_undo_if_changed(before_json):
            return
        self.model.populate_tree()
        self.saveStateRefreshRequested.emit()
        self.statusMessageRequested.emit("Added", f"Added {added_count} samples.", 1500)

        if first_sample_id:
            entry = self.model.sample_id_to_entry.get(first_sample_id)
            item = self.model.action_item_map.get(entry["path"]) if entry else None
            if item is not None:
                self.model.panel.tree.setCurrentIndex(item.index())
                self.model.panel.tree.setFocus()

    def execute_clear_workspace(self):
        if not self.model.json_loaded:
            return

        before_json = self.model.snapshot_dataset_json()
        self.model.mediaStopRequested.emit()
        self.model.dataset_json["data"] = []
        if not self.model.push_dataset_json_replace_undo_if_changed(before_json):
            return

        self.model._rebuild_runtime_index()
        self.model.resetEditorsRequested.emit()
        self.model.workspaceViewRequested.emit()
        self._emit_schema_refresh()
        self.model.populate_tree()
        self.saveStateRefreshRequested.emit()
        self.statusMessageRequested.emit("Cleared", "Workspace reset.", 1500)

    def execute_remove_item(self, sample_id: str, input_path: str):
        if not sample_id:
            return

        pre_remove_expanded_sample_ids = self.model._expanded_sample_ids_in_tree()
        parent_idx = self.model._top_level_index_for_sample(sample_id)
        removed_parent_row = parent_idx.row() if parent_idx.isValid() else -1

        before_json = self.model.snapshot_dataset_json()
        removed = False
        sample_removed = False
        removed_path = ""

        if input_path:
            removed, sample_removed = self.model._remove_sample_input_by_path(sample_id, input_path)
            removed_path = input_path
        else:
            sample_path = self.model.get_path_by_id(sample_id)
            removed = self.model._remove_sample_by_id(sample_id)
            sample_removed = removed
            removed_path = sample_path or ""

        if not removed:
            return

        if not self.model.push_dataset_json_replace_undo_if_changed(before_json):
            return
        removed_selected = (
            sample_id == self.model.current_selected_sample_id
            if sample_removed
            else self.model._fs_path_key(removed_path) == self.model._fs_path_key(self.model.current_selected_input_path)
        )

        self.model.populate_tree()

        post_remove_selection = QModelIndex()
        if sample_removed:
            post_remove_selection = self.model._first_visible_top_level_index(removed_parent_row - 1)
        else:
            parent_idx = self.model._top_level_index_for_sample(sample_id)
            if parent_idx.isValid():
                child_idx = self.model._first_child_index_for_parent(parent_idx)
                post_remove_selection = child_idx if child_idx.isValid() else parent_idx

        if post_remove_selection.isValid():
            self.model.panel.tree.setCurrentIndex(post_remove_selection)
            self.model.panel.tree.scrollTo(post_remove_selection)
        self.model._reapply_expanded_samples(pre_remove_expanded_sample_ids)

        self.saveStateRefreshRequested.emit()
        self.statusMessageRequested.emit(
            "Removed",
            "Sample removed." if sample_removed else "Input removed.",
            1500,
        )

        if removed_selected and self.tree_model.rowCount() == 0:
            self.model._reset_panels_after_removed_path(removed_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _path_for_sample(self, sample_id: str):
        if not sample_id:
            return None
        return self.model.get_path_by_id(sample_id)

    def _set_sample_field(self, sample_id: str, field_name: str, value):
        sample = self.model.get_sample(sample_id)
        if not isinstance(sample, dict):
            return

        if field_name == "captions":
            self.model.set_sample_captions(sample_id, copy.deepcopy(value) if value is not None else [])
            return

        if value is None:
            sample.pop(field_name, None)
            return

        sample[field_name] = copy.deepcopy(value)

    def _emit_schema_refresh(self):
        self.classificationSetupRequested.emit()
        self.localizationSchemaRefreshRequested.emit()

    def _emit_post_mutation(
        self,
        touched_paths=None,
        refresh_filter: bool = False,
        refresh_schema: bool = False,
        status_title: str = "",
        status_msg: str = "",
        status_duration: int = 1500,
    ):
        if refresh_schema:
            self._emit_schema_refresh()

        if touched_paths:
            for path in touched_paths:
                if path:
                    self.itemStatusRefreshRequested.emit(path)

        if refresh_filter:
            self.filterRefreshRequested.emit(int(self._get_current_filter_index()), "first_visible")

        self.saveStateRefreshRequested.emit()
        if status_title or status_msg:
            self.statusMessageRequested.emit(status_title, status_msg, status_duration)

    def _find_loc_event_index(self, events, event):
        try:
            return events.index(event)
        except ValueError:
            pass

        target_head = event.get("head")
        target_label = event.get("label")
        target_pos = event.get("position_ms")
        for idx, candidate in enumerate(events):
            if (
                candidate.get("head") == target_head
                and candidate.get("label") == target_label
                and candidate.get("position_ms") == target_pos
            ):
                return idx
        return -1

    def _refresh_active_view(self):
        """
        Refreshes the currently active UI tab after a state change.
        Uses the tab index logic to call the appropriate manager's refresh method.
        """
        tab_idx = int(self._get_current_tab_index())

        # 0: Classification Mode
        if tab_idx == 0:
            self.classificationSetupRequested.emit()
            self.refreshUiAfterUndoRedoRequested.emit(
                self._get_current_action_path() or "",
                "clear_selection",
            )

        # 1: Localization Mode
        elif tab_idx == 1:
            self.localizationSchemaRefreshRequested.emit()
            self.localizationClipEventsRefreshRequested.emit()
            self.refreshUiAfterUndoRedoRequested.emit(
                self._get_current_action_path() or "",
                "clear_selection",
            )

        # 2: Description Mode
        elif tab_idx == 2:
            self.refreshUiAfterUndoRedoRequested.emit(
                self._get_current_action_path() or "",
                "clear_selection",
            )

        # 3: Dense Description Mode
        elif tab_idx == 3:
            path = self._get_dense_current_video_path()
            if path:
                self.denseDisplayRequested.emit(path)

    def _apply_state_change(self, cmd, is_undo):
        ctype = cmd["type"]

        if ctype == CmdType.DATASET_JSON_REPLACE:
            snapshot = cmd["old_data"] if is_undo else cmd["new_data"]
            expanded_sample_ids = self.model._expanded_sample_ids_in_tree()
            preferred_sample_id = self.model.current_selected_sample_id
            preferred_input_path = self.model.current_selected_input_path

            self.datasetRestoreRequested.emit(
                copy.deepcopy(snapshot),
                preferred_sample_id or "",
                preferred_input_path,
                expanded_sample_ids,
            )
            self.refreshUiAfterUndoRedoRequested.emit(
                self._get_current_action_path() or "",
                "clear_selection",
            )
            return

        # 1. Classification Specific
        if ctype == CmdType.ANNOTATION_CONFIRM:
            path = cmd["path"]
            data = cmd["old_data"] if is_undo else cmd["new_data"]
            sample = self.model.get_sample_by_path(path)
            if not isinstance(sample, dict):
                return

            if data is None:
                sample.pop("labels", None)
            elif isinstance(data, dict):
                sample["labels"] = {}
                record = self.model.manual_annotations[path]
                for head, value in data.items():
                    record[head] = copy.deepcopy(value)
            else:
                self.model.manual_annotations[path] = copy.deepcopy(data)
            self.refreshUiAfterUndoRedoRequested.emit(path or "", "clear_selection")

        elif ctype == CmdType.BATCH_ANNOTATION_CONFIRM:
            batch_changes = cmd["batch_changes"]
            for path, changes in batch_changes.items():
                data = changes["old_data"] if is_undo else changes["new_data"]
                if data:
                    self.model.manual_annotations[path] = copy.deepcopy(data)
                else:
                    if path in self.model.manual_annotations:
                        del self.model.manual_annotations[path]
                self.itemStatusRefreshRequested.emit(path)
            self._refresh_active_view()

        elif ctype == CmdType.SMART_ANNOTATION_RUN:
            path = cmd["path"]
            data = cmd["old_data"] if is_undo else cmd["new_data"]
            if data:
                self.model.smart_annotations[path] = copy.deepcopy(data)
            else:
                if path in self.model.smart_annotations:
                    del self.model.smart_annotations[path]
            self._refresh_active_view()

        elif ctype == CmdType.BATCH_SMART_ANNOTATION_RUN:
            batch_data = cmd["old_data"] if is_undo else cmd["new_data"]
            for path, data in batch_data.items():
                if data:
                    self.model.smart_annotations[path] = copy.deepcopy(data)
                else:
                    if path in self.model.smart_annotations:
                        del self.model.smart_annotations[path]
            self._refresh_active_view()

        elif ctype == CmdType.LOC_EVENT_ADD:
            path = cmd["video_path"]
            evt = cmd["event"]
            events = self.model.localization_events.get(path, [])
            if is_undo:
                if evt in events:
                    events.remove(evt)
            else:
                events.append(evt)
            self.model.localization_events[path] = events
            self._refresh_active_view()

        elif ctype == CmdType.LOC_EVENT_DEL:
            path = cmd["video_path"]
            evt = cmd["event"]
            events = self.model.localization_events.get(path, [])

            if is_undo:
                event_index = cmd.get("event_index")
                if isinstance(event_index, int) and 0 <= event_index <= len(events):
                    events.insert(event_index, evt)
                else:
                    events.append(evt)
                if path not in self.model.localization_events:
                    self.model.localization_events[path] = events
            else:
                event_index = cmd.get("event_index")
                if isinstance(event_index, int) and 0 <= event_index < len(events) and events[event_index] == evt:
                    events.pop(event_index)
                elif evt in events:
                    events.remove(evt)

            self._refresh_active_view()

        elif ctype == CmdType.LOC_EVENT_MOD:
            path = cmd["video_path"]
            old_e = cmd["old_event"]
            new_e = cmd["new_event"]
            events = self.model.localization_events.get(path, [])

            target = new_e if is_undo else old_e
            replacement = old_e if is_undo else new_e

            try:
                idx = events.index(target)
                events[idx] = replacement
            except ValueError:
                pass

            self._refresh_active_view()

        elif ctype == CmdType.SAMPLE_FIELD_EDIT:
            path = cmd["path"]
            sample_id = cmd.get("sample_id") or self.model.get_data_id_by_path(path)
            field_name = cmd.get("field_name") or "captions"
            data_to_apply = cmd["old_data"] if is_undo else cmd["new_data"]

            if sample_id:
                self._set_sample_field(sample_id, field_name, copy.deepcopy(data_to_apply))
                if path:
                    self.itemStatusRefreshRequested.emit(path)

            self._refresh_active_view()

        elif ctype == CmdType.DENSE_EVENT_ADD:
            path = cmd["video_path"]
            evt = cmd["event"]
            events = self.model.dense_description_events.get(path, [])

            if is_undo:
                if evt in events:
                    events.remove(evt)
            else:
                events.append(evt)

            self.model.dense_description_events[path] = events
            self._refresh_active_view()

        elif ctype == CmdType.DENSE_EVENT_DEL:
            path = cmd["video_path"]
            evt = cmd["event"]
            events = self.model.dense_description_events.get(path, [])

            if is_undo:
                event_index = cmd.get("event_index")
                if isinstance(event_index, int) and 0 <= event_index <= len(events):
                    events.insert(event_index, evt)
                else:
                    events.append(evt)
                if path not in self.model.dense_description_events:
                    self.model.dense_description_events[path] = events
            else:
                event_index = cmd.get("event_index")
                if isinstance(event_index, int) and 0 <= event_index < len(events) and events[event_index] == evt:
                    events.pop(event_index)
                elif evt in events:
                    events.remove(evt)

            self._refresh_active_view()

        elif ctype == CmdType.DENSE_EVENT_MOD:
            path = cmd["video_path"]
            old_e = cmd["old_event"]
            new_e = cmd["new_event"]
            events = self.model.dense_description_events.get(path, [])

            target = new_e if is_undo else old_e
            replacement = old_e if is_undo else new_e

            try:
                idx = events.index(target)
                events[idx] = replacement
            except ValueError:
                pass

            self._refresh_active_view()

        elif ctype == CmdType.SCHEMA_ADD_CAT:
            head = cmd["head"]
            if is_undo:
                if head in self.model.label_definitions:
                    del self.model.label_definitions[head]
            else:
                self.model.label_definitions[head] = cmd["definition"]
            self._refresh_active_view()

        elif ctype == CmdType.SCHEMA_DEL_CAT:
            head = cmd["head"]
            if is_undo:
                self.model.label_definitions[head] = cmd["definition"]

                if "affected_data" in cmd:
                    for key, value in cmd["affected_data"].items():
                        if key not in self.model.manual_annotations:
                            self.model.manual_annotations[key] = {}
                        self.model.manual_annotations[key][head] = value

                if "loc_affected_events" in cmd:
                    for vid, events_list in cmd["loc_affected_events"].items():
                        if vid not in self.model.localization_events:
                            self.model.localization_events[vid] = []
                        self.model.localization_events[vid].extend(events_list)
            else:
                if head in self.model.label_definitions:
                    del self.model.label_definitions[head]

                if "affected_data" in cmd:
                    for key in cmd["affected_data"]:
                        if head in self.model.manual_annotations.get(key, {}):
                            del self.model.manual_annotations[key][head]

                if "loc_affected_events" in cmd:
                    for vid in self.model.localization_events:
                        self.model.localization_events[vid] = [
                            e for e in self.model.localization_events[vid] if e.get("head") != head
                        ]

            self._refresh_active_view()

        elif ctype == CmdType.SCHEMA_REN_CAT:
            old_n = cmd["old_name"]
            new_n = cmd["new_name"]

            src = new_n if is_undo else old_n
            dst = old_n if is_undo else new_n

            if src in self.model.label_definitions:
                self.model.label_definitions[dst] = self.model.label_definitions.pop(src)

            for anno in self.model.manual_annotations.values():
                if src in anno:
                    anno[dst] = anno.pop(src)

            for events in self.model.localization_events.values():
                for evt in events:
                    if evt.get("head") == src:
                        evt["head"] = dst

            self._refresh_active_view()

        elif ctype == CmdType.SCHEMA_ADD_LBL:
            head = cmd["head"]
            lbl = cmd["label"]
            if head in self.model.label_definitions:
                labels = self.model.label_definitions[head]["labels"]
                if is_undo:
                    if lbl in labels:
                        labels.remove(lbl)
                else:
                    if lbl not in labels:
                        labels.append(lbl)
                        labels.sort()

            self._refresh_active_view()

        elif ctype == CmdType.SCHEMA_DEL_LBL:
            head = cmd["head"]
            lbl = cmd["label"]
            if head in self.model.label_definitions:
                labels = self.model.label_definitions[head]["labels"]
                label_index = cmd.get("label_index")

                if is_undo:
                    if lbl not in labels:
                        if isinstance(label_index, int) and 0 <= label_index <= len(labels):
                            labels.insert(label_index, lbl)
                        else:
                            labels.append(lbl)
                    if "affected_data" in cmd:
                        for key, value in cmd["affected_data"].items():
                            if key not in self.model.manual_annotations:
                                self.model.manual_annotations[key] = {}
                            if self.model.label_definitions[head]["type"] == "single_label":
                                self.model.manual_annotations[key][head] = value
                            else:
                                cur = self.model.manual_annotations[key].get(head, [])
                                if lbl not in cur:
                                    cur.append(lbl)
                                self.model.manual_annotations[key][head] = cur

                    if "loc_affected_events" in cmd:
                        for vid, events_list in cmd["loc_affected_events"].items():
                            if vid not in self.model.localization_events:
                                self.model.localization_events[vid] = []
                            self.model.localization_events[vid].extend(events_list)

                else:
                    if isinstance(label_index, int) and 0 <= label_index < len(labels) and labels[label_index] == lbl:
                        labels.pop(label_index)
                    elif lbl in labels:
                        labels.remove(lbl)

                    if "affected_data" in cmd:
                        for key in cmd["affected_data"]:
                            anno = self.model.manual_annotations.get(key, {})
                            if self.model.label_definitions[head]["type"] == "single_label":
                                if anno.get(head) == lbl:
                                    anno[head] = None
                            else:
                                if lbl in anno.get(head, []):
                                    anno[head].remove(lbl)

                    if "loc_affected_events" in cmd:
                        for vid in self.model.localization_events:
                            self.model.localization_events[vid] = [
                                e
                                for e in self.model.localization_events[vid]
                                if not (e.get("head") == head and e.get("label") == lbl)
                            ]

            self._refresh_active_view()

        elif ctype == CmdType.SCHEMA_REN_LBL:
            head = cmd["head"]
            old_l = cmd["old_lbl"]
            new_l = cmd["new_lbl"]

            src = new_l if is_undo else old_l
            dst = old_l if is_undo else new_l

            if head in self.model.label_definitions:
                labels = self.model.label_definitions[head]["labels"]
                if src in labels:
                    idx = labels.index(src)
                    labels[idx] = dst

            for anno in self.model.manual_annotations.values():
                val = anno.get(head)
                if isinstance(val, str) and val == src:
                    anno[head] = dst
                elif isinstance(val, list) and src in val:
                    val[val.index(src)] = dst

            for events in self.model.localization_events.values():
                for evt in events:
                    if evt.get("head") == head and evt.get("label") == src:
                        evt["label"] = dst

            self._refresh_active_view()
