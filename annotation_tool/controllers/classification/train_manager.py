import os
import sys
import json
import uuid
import yaml
import copy
import re
import io
import contextlib
from PyQt6.QtCore import QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import QMessageBox

# Assume the model invocation style is the same as inference
from opensportslib import model

class TrainWorker(QThread):
    """
    Background training thread.
    Supports printing checkpoint-save related information to the terminal
    every fixed number of steps.
    """
    # Signal for appending plain log text to the UI console
    log_signal = pyqtSignal(str)
    # Signal for updating the progress bar percentage
    progress_signal = pyqtSignal(int)
    # Signal for updating the short training status label
    status_msg_signal = pyqtSignal(str)
    # Signal emitted when training ends: (success_flag, message)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, config_path, train_params):
        super().__init__()
        # Path to the base YAML config template
        self.config_path = config_path
        # Training parameters collected from the UI
        self.params = train_params
        # Regex used to capture progress-style outputs such as "12/100 ["
        self.progress_re = re.compile(r'(\d+)/(\d+)\s+\[') 

    def run(self):
        # Create a hidden workspace under the user's home directory
        # to store temporary runtime config files
        temp_workspace = os.path.join(os.path.expanduser("~"), ".soccernet_workspace")
        os.makedirs(temp_workspace, exist_ok=True)
        
        # Generate a unique temporary config filename for this training run
        unique_id = uuid.uuid4().hex[:6]
        temp_config_path = os.path.join(temp_workspace, f"temp_train_config_{unique_id}.yaml")

        try:
            # Load the original YAML config template
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            # 1. Path setup
            # Infer dataset root from the directory of the training annotation JSON
            dataset_root = os.path.dirname(self.params['train_json'])
            config['DATA']['data_dir'] = str(dataset_root).replace('\\', '/')

            # Create a checkpoint directory inside the dataset root
            checkpoint_dir = os.path.join(dataset_root, "checkpoints")
            os.makedirs(checkpoint_dir, exist_ok=True)
            config['TRAIN']['save_dir'] = str(checkpoint_dir).replace('\\', '/')

            log_dir = os.path.join(dataset_root, "logs")
            os.makedirs(log_dir, exist_ok=True)
            
            if 'SYSTEM' not in config:
                config['SYSTEM'] = {}
            config['SYSTEM']['log_dir'] = str(log_dir).replace('\\', '/')

            # 2. Structure adjustment
            # Inject annotation paths into a custom annotations block
            config['DATA']['annotations'] = {
                'train': str(self.params['train_json']),
                'valid': str(self.params['valid_json'])
            }

            # 3. Update training hyperparameters from UI inputs
            config['TRAIN']['epochs'] = int(self.params['epochs'])
            config['TRAIN']['optimizer']['lr'] = float(self.params['lr'])
            config['TRAIN']['save_every'] = 1  # Save by epoch

            # [NEW] Try to inject step-based checkpoint save options
            # These keys depend on whether opensportslib supports them internally
            config['TRAIN']['save_step'] = 500
            config['TRAIN']['checkpoint_interval'] = 500  # Fallback compatibility key
            
            # Explicitly enable training mode
            config['TRAIN']['enabled'] = True
            # Set the device selected from the UI, e.g. "cpu" or "cuda"
            config['SYSTEM']['device'] = str(self.params['device'])
            
            # Ensure the train block exists before modifying dataloader settings
            if 'train' not in config['DATA']:
                config['DATA']['train'] = {}

            # Ensure the nested dataloader block exists
            config['DATA']['train']['dataloader'] = config['DATA'].get('train', {}).get('dataloader', {})
            # Update batch size and number of workers from UI
            config['DATA']['train']['dataloader']['batch_size'] = int(self.params['batch'])
            config['DATA']['train']['dataloader']['num_workers'] = int(self.params['workers'])

            # Write the runtime YAML config to a temporary file
            with open(temp_config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config, f)

            # Notify UI that training initialization has started
            self.log_signal.emit(f"🚀 Initializing Training on {self.params['device']}...")

            # --- 4. Enhanced log interceptor ---
            # This stream captures stdout/stderr from training, parses progress,
            # forwards readable logs to the UI, and prints special checkpoint info
            # directly to the VSCode terminal.
            class UILogStream(io.TextIOBase):
                def __init__(self, outer_instance, cp_dir):
                    # Reference back to the outer TrainWorker instance
                    self.outer = outer_instance
                    # Directory where checkpoints are stored
                    self.cp_dir = cp_dir
                    # Best-effort current epoch string for UI status display
                    self.current_epoch_str = "Epoch ?/?"
                    # Internal line buffer for partial writes
                    self.line_buffer = ""

                def write(self, s):
                    # Accumulate incoming text because stdout/stderr may write in chunks
                    self.line_buffer += s

                    # Process buffered content whenever a newline or carriage return appears
                    while '\n' in self.line_buffer or '\r' in self.line_buffer:
                        idx_n = self.line_buffer.find('\n')
                        idx_r = self.line_buffer.find('\r')

                        # Split on the earliest line boundary
                        if idx_n != -1 and (idx_r == -1 or idx_n < idx_r):
                            line, self.line_buffer = self.line_buffer.split('\n', 1)
                        else:
                            line, self.line_buffer = self.line_buffer.split('\r', 1)

                        # Remove leading/trailing spaces
                        clean_line = line.strip()
                        if not clean_line:
                            continue

                        # Detect epoch lines and forward them to the UI log console
                        if "Epoch" in clean_line:
                            epoch_match = re.search(r'Epoch\s+\d+/\d+', clean_line)
                            if epoch_match:
                                self.current_epoch_str = epoch_match.group(0)
                            self.outer.log_signal.emit(clean_line)

                        # Detect progress lines like "123/500 ["
                        match = self.outer.progress_re.search(clean_line)
                        if match:
                            curr_step = int(match.group(1))
                            total_step = int(match.group(2))

                            # Compute percentage for the progress bar
                            percent = int((curr_step / total_step) * 100)
                            self.outer.progress_signal.emit(percent)

                            # Update short status text in the UI
                            self.outer.status_msg_signal.emit(
                                f"{self.current_epoch_str} | Step: {curr_step}/{total_step}"
                            )
                            
                            # [NEW] Every 500 steps, print an explicit message to the real terminal
                            # using sys.__stdout__ so it bypasses the redirection
                            if curr_step > 0 and curr_step % 500 == 0:
                                msg = (
                                    f"\n[VSCODE INFO] Iteration {curr_step} reached. "
                                    f"Checkpoint auto-save triggered to: {self.cp_dir}\n"
                                )
                                sys.__stdout__.write(msg)
                                sys.__stdout__.flush()
                        else:
                            # Forward non-progress, non-noisy lines to the UI log panel
                            if "Training:" not in clean_line and "|" not in clean_line:
                                self.outer.log_signal.emit(clean_line)

                    return len(s)

            # 5. Start training
            # Build the classification model using the temporary runtime config
            myModel = model.classification(config=temp_config_path)
            
            # Redirect stdout and stderr from the training process into the custom UI stream
            log_stream = UILogStream(self, checkpoint_dir)
            with contextlib.ExitStack() as stack:
                stack.enter_context(contextlib.redirect_stdout(log_stream))
                stack.enter_context(contextlib.redirect_stderr(log_stream))
                # Launch training
                myModel.train()

            # Notify UI that training completed successfully
            self.finished_signal.emit(True, f"Training Completed Successfully.\nCheckpoints: {checkpoint_dir}")

        except Exception as e:
            # Print traceback to the real console for debugging
            import traceback
            traceback.print_exc()
            # Notify UI that training failed
            self.finished_signal.emit(False, str(e))
        finally:
            # Always try to remove the temporary config file after training ends
            if os.path.exists(temp_config_path):
                try:
                    os.remove(temp_config_path)
                except:
                    pass

class TrainManager(QObject):
    def __init__(self, main_window):
        super().__init__()
        # Reference to the main window
        self.main = main_window
        # Background worker thread instance
        self.worker = None

        # Resolve base directory differently for bundled app vs source execution
        if hasattr(sys, '_MEIPASS'):
            self.base_dir = sys._MEIPASS
        else:
            self.base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            
        # Path to the base classification config file
        self.config_path = os.path.join(self.base_dir, "config.yaml")

        # Connect UI buttons to start/stop handlers
        self.main.classification_panel.btn_start_train.clicked.connect(self.start_training)
        self.main.classification_panel.btn_stop_train.clicked.connect(self.stop_training)

    def start_training(self):
        # Prevent launching a second training job while one is already running
        if self.worker and self.worker.isRunning():
            return

        # Get the currently loaded JSON annotation file from the main model
        train_json = self.main.model.current_json_path

        # Require that the currently loaded file is the training annotation file
        if not train_json or "annotations_train" not in train_json:
            QMessageBox.critical(self.main, "Error", "Please load 'annotations_train.json' first.")
            return

        # Collect training parameters from the UI controls
        params = {
            "epochs": self.main.classification_panel.spin_epochs.currentText(),
            "lr": self.main.classification_panel.edit_lr.text(),
            "batch": self.main.classification_panel.spin_batch.currentText(),
            # Extract only the raw device token from combo text, e.g. "cuda (GPU)" -> "cuda"
            "device": self.main.classification_panel.combo_device.currentText().split(" ")[0],
            "workers": self.main.classification_panel.spin_workers.currentText(),
            "train_json": train_json,
            # Infer the validation annotation path by filename replacement
            "valid_json": train_json.replace("annotations_train.json", "annotations_valid.json")
        }

        # Prepare UI state for an active training session
        self.main.classification_panel.btn_start_train.setEnabled(False)
        self.main.classification_panel.btn_stop_train.setEnabled(True)
        self.main.classification_panel.train_progress.setVisible(True)
        self.main.classification_panel.train_progress.setValue(0)
        self.main.classification_panel.lbl_train_status.setVisible(True)
        self.main.classification_panel.lbl_train_status.setText("🚀 Starting Training Loop...")
        self.main.classification_panel.train_console.clear()

        # Create and wire up the training worker thread
        self.worker = TrainWorker(self.config_path, params)
        self.worker.log_signal.connect(self._append_log)
        self.worker.progress_signal.connect(self.main.classification_panel.train_progress.setValue)
        self.worker.status_msg_signal.connect(self.main.classification_panel.lbl_train_status.setText)
        self.worker.finished_signal.connect(self._on_train_finished)

        # Start background training
        self.worker.start()

    def _append_log(self, text):
        # Append a line of log text to the training console widget
        self.main.classification_panel.train_console.append(text)

    def stop_training(self):
        """Force-stop the training thread."""
        if self.worker and self.worker.isRunning():
            # Ask for user confirmation before aborting training
            reply = QMessageBox.question(
                self.main, "Confirm Stop",
                "Are you sure you want to abort training?\nUnsaved progress in the current epoch will be lost.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Update UI to reflect aborting state
                self.main.classification_panel.btn_stop_train.setEnabled(False)
                self.main.classification_panel.lbl_train_status.setText("🛑 Aborting...")
                
                # Forcefully terminate the worker thread
                self.worker.terminate()
                self.worker.wait()
                
                # Reuse the finish handler with a manual-abort message
                self._on_train_finished(False, "Training was manually aborted by user.")

    def _on_train_finished(self, success, message):
        # Restore UI controls after training ends
        self.main.classification_panel.btn_start_train.setEnabled(True)
        self.main.classification_panel.btn_stop_train.setEnabled(False)
        self.main.classification_panel.train_progress.setVisible(False)
        self.main.classification_panel.lbl_train_status.setVisible(False)

        # Show result feedback and append a final log line
        if success:
            QMessageBox.information(self.main, "Success", message)
            self._append_log(f"\n✅ [SUCCESS] {message}")
        else:
            QMessageBox.critical(self.main, "Train Error", message)
            self._append_log(f"\n❌ [ERROR] {message}")
