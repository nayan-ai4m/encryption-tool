import sys
import os
import subprocess
import glob
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QListWidget, QLineEdit, QMessageBox, QTextEdit, 
                             QGroupBox, QFormLayout, QComboBox, QTabWidget,
                             QCheckBox, QFrame, QScrollArea)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont


# =============================================================================
# WORKER THREADS
# =============================================================================

class EncryptionWorker(QThread):
    """Worker thread for PyArmor encryption only."""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)  # success, dist_path

    def __init__(self, folder):
        super().__init__()
        self.folder = folder

    def run_command(self, cmd):
        """Executes shell commands."""
        self.log_signal.emit(f"Executing: {cmd}")
        try:
            process = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            stdout, stderr = process.communicate()
            if stdout:
                self.log_signal.emit(stdout)
            if stderr:
                self.log_signal.emit(f"STDERR: {stderr}")
            return process.returncode == 0
        except Exception as e:
            self.log_signal.emit(f"Error: {str(e)}")
            return False

    def run(self):
        self.log_signal.emit("--- Starting Encryption Process ---")
        
        # 1. Configure PyArmor to include data files
        if not self.run_command("pyarmor cfg data_files=*"):
            self.finished_signal.emit(False, "")
            return

        # 2. Clean existing dist folder
        dist_path = os.path.join(self.folder, "dist")
        if os.path.exists(dist_path):
            self.log_signal.emit(f"Cleaning existing dist folder: {dist_path}")
            self.run_command(f"rm -rf {dist_path}")

        # 3. Run PyArmor encryption
        self.log_signal.emit(f"Encrypting folder: {self.folder}")
        enc_cmd = f"pyarmor gen -O {dist_path} -r --exclude '*/.venv/**' --exclude '*/__pycache__/**' {self.folder}"
        if not self.run_command(enc_cmd):
            self.finished_signal.emit(False, "")
            return

        self.log_signal.emit("✅ Encryption completed successfully!")
        self.finished_signal.emit(True, dist_path)


class ServiceConfigWorker(QThread):
    """Worker thread for service configuration updates."""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, service_name, new_config, sudo_pass):
        super().__init__()
        self.service_name = service_name
        self.new_config = new_config
        self.sudo_pass = sudo_pass

    def run_command(self, cmd, sudo=False):
        """Executes shell commands, handling sudo if required."""
        if sudo:
            cmd = f"echo {self.sudo_pass} | sudo -S {cmd}"
        
        self.log_signal.emit(f"Executing: {cmd.replace(self.sudo_pass, '******')}")
        
        try:
            process = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            stdout, stderr = process.communicate()
            if stdout:
                self.log_signal.emit(stdout)
            if stderr:
                self.log_signal.emit(f"STDERR: {stderr}")
            return process.returncode == 0
        except Exception as e:
            self.log_signal.emit(f"Error: {str(e)}")
            return False

    def run(self):
        self.log_signal.emit("--- Updating Service Configuration ---")
        
        # 1. Write new service file to temp location
        temp_path = f"/tmp/{self.service_name}"
        with open(temp_path, "w") as f:
            f.write(self.new_config)
        self.log_signal.emit(f"Generated service file at: {temp_path}")

        # 2. Move to systemd directory
        target_path = f"/etc/systemd/system/{self.service_name}"
        if not self.run_command(f"mv {temp_path} {target_path}", sudo=True):
            self.finished_signal.emit(False)
            return

        # 3. Reload systemd daemon
        self.run_command("systemctl daemon-reload", sudo=True)
        
        # 4. Restart service
        self.run_command(f"systemctl restart {self.service_name}", sudo=True)

        self.log_signal.emit("✅ Service configuration updated successfully!")
        self.finished_signal.emit(True)


# =============================================================================
# TAB 1: ENCRYPTION TAB
# =============================================================================

class EncryptionTab(QWidget):
    """Tab for encrypting Python projects with PyArmor."""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.worker = None

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # --- Folder Selection ---
        grp_folder = QGroupBox("📁 Select Project Folder")
        layout_folder = QVBoxLayout()
        
        folder_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Select the root folder of your Python project")
        self.path_input.textChanged.connect(self.check_encryption_status)
        
        btn_browse = QPushButton("Browse Folder")
        btn_browse.clicked.connect(self.select_folder)
        
        folder_row.addWidget(self.path_input)
        folder_row.addWidget(btn_browse)
        layout_folder.addLayout(folder_row)
        
        grp_folder.setLayout(layout_folder)
        layout.addWidget(grp_folder)

        # --- Encryption Status ---
        grp_status = QGroupBox("🔍 Encryption Status")
        layout_status = QVBoxLayout()
        
        self.status_label = QLabel("No folder selected")
        self.status_label.setStyleSheet("font-size: 14px; padding: 10px;")
        layout_status.addWidget(self.status_label)
        
        # Python files list
        self.list_files = QListWidget()
        self.list_files.setFixedHeight(100)
        layout_status.addWidget(QLabel("Detected Python Files:"))
        layout_status.addWidget(self.list_files)
        
        grp_status.setLayout(layout_status)
        layout.addWidget(grp_status)

        # --- Encryption Options ---
        grp_options = QGroupBox("⚙️ Encryption Options")
        layout_options = QVBoxLayout()
        
        self.chk_reencrypt = QCheckBox("Force re-encryption (overwrites existing dist folder)")
        layout_options.addWidget(self.chk_reencrypt)
        
        grp_options.setLayout(layout_options)
        layout.addWidget(grp_options)

        # --- Encrypt Button ---
        self.btn_encrypt = QPushButton("🔐 ENCRYPT FOLDER")
        self.btn_encrypt.setFixedHeight(50)
        self.btn_encrypt.setStyleSheet("""
            QPushButton {
                background-color: #2E8B57;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #3CB371;
            }
            QPushButton:disabled {
                background-color: #666666;
            }
        """)
        self.btn_encrypt.clicked.connect(self.start_encryption)
        layout.addWidget(self.btn_encrypt)

        # --- Logs ---
        layout.addWidget(QLabel("📋 Encryption Logs:"))
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: monospace;")
        layout.addWidget(self.log_output)

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder")
        if folder:
            self.path_input.setText(folder)
            self.scan_files(folder)

    def scan_files(self, folder):
        self.list_files.clear()
        py_files = []
        for root, dirs, files in os.walk(folder):
            # Skip venv and __pycache__
            dirs[:] = [d for d in dirs if d not in ['.venv', 'venv', '__pycache__', 'dist']]
            for file in files:
                if file.endswith(".py"):
                    rel_path = os.path.relpath(os.path.join(root, file), folder)
                    py_files.append(rel_path)
        
        self.list_files.addItems(py_files)
        if not py_files:
            self.log("No Python files found in selected folder.")

    def check_encryption_status(self):
        folder = self.path_input.text()
        if not folder or not os.path.isdir(folder):
            self.status_label.setText("No folder selected")
            self.status_label.setStyleSheet("font-size: 14px; padding: 10px; color: gray;")
            return

        dist_path = os.path.join(folder, "dist")
        
        # Check for pyarmor_runtime_* folder inside dist
        if os.path.exists(dist_path):
            runtime_folders = glob.glob(os.path.join(dist_path, "pyarmor_runtime_*"))
            if runtime_folders:
                # Get modification time
                mtime = os.path.getmtime(runtime_folders[0])
                from datetime import datetime
                mod_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                
                self.status_label.setText(f"✅ Already Encrypted (Last: {mod_time})")
                self.status_label.setStyleSheet("font-size: 14px; padding: 10px; color: #2E8B57; font-weight: bold;")
                self.btn_encrypt.setText("🔐 RE-ENCRYPT FOLDER")
                return

        self.status_label.setText("❌ Not Encrypted")
        self.status_label.setStyleSheet("font-size: 14px; padding: 10px; color: #CC0000; font-weight: bold;")
        self.btn_encrypt.setText("🔐 ENCRYPT FOLDER")

    def log(self, message):
        self.log_output.append(message)
        sb = self.log_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_encryption(self):
        folder = self.path_input.text()
        
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "Missing Folder", "Please select a valid project folder.")
            return

        # Check if already encrypted and re-encrypt not checked
        dist_path = os.path.join(folder, "dist")
        if os.path.exists(dist_path):
            runtime_folders = glob.glob(os.path.join(dist_path, "pyarmor_runtime_*"))
            if runtime_folders and not self.chk_reencrypt.isChecked():
                reply = QMessageBox.question(
                    self, "Already Encrypted",
                    "This folder is already encrypted. Do you want to re-encrypt?",
                    QMessageBox.Yes | QMessageBox.No
                )
                if reply == QMessageBox.No:
                    return

        self.btn_encrypt.setEnabled(False)
        self.log_output.clear()
        
        self.worker = EncryptionWorker(folder)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_encryption_finished)
        self.worker.start()

    def on_encryption_finished(self, success, dist_path):
        self.btn_encrypt.setEnabled(True)
        self.check_encryption_status()
        
        if success:
            QMessageBox.information(self, "Success", f"Encryption completed!\n\nOutput: {dist_path}")
        else:
            QMessageBox.critical(self, "Failed", "Encryption failed. Check the logs for details.")


# =============================================================================
# TAB 2: SERVICE CONFIGURATION TAB
# =============================================================================

class ServiceConfigTab(QWidget):
    """Tab for configuring systemd services for encrypted projects."""
    
    def __init__(self):
        super().__init__()
        self.current_service_config = {}
        self.init_ui()
        self.worker = None

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # --- Service Selection ---
        grp_service = QGroupBox("🔧 Select Service")
        layout_service = QFormLayout()
        
        service_row = QHBoxLayout()
        self.combo_service = QComboBox()
        self.combo_service.setEditable(True)
        self.combo_service.setPlaceholderText("Select or type service name")
        self.combo_service.currentTextChanged.connect(self.on_service_changed)
        
        btn_refresh = QPushButton("🔄")
        btn_refresh.setFixedWidth(40)
        btn_refresh.setToolTip("Refresh service list")
        btn_refresh.clicked.connect(self.load_services)
        
        btn_parse = QPushButton("📖 Parse Service")
        btn_parse.clicked.connect(self.parse_service)
        
        service_row.addWidget(self.combo_service)
        service_row.addWidget(btn_refresh)
        service_row.addWidget(btn_parse)
        
        layout_service.addRow("Service:", service_row)
        grp_service.setLayout(layout_service)
        layout.addWidget(grp_service)
        
        # Load services on init
        self.load_services()

        # --- Current Configuration ---
        grp_current = QGroupBox("📄 Current Service Configuration")
        layout_current = QVBoxLayout()
        
        self.txt_current_config = QTextEdit()
        self.txt_current_config.setReadOnly(True)
        self.txt_current_config.setMaximumHeight(150)
        self.txt_current_config.setStyleSheet("background-color: #2d2d2d; color: #ffffff; font-family: monospace;")
        self.txt_current_config.setPlaceholderText("Click 'Parse Service' to view current configuration...")
        layout_current.addWidget(self.txt_current_config)
        
        grp_current.setLayout(layout_current)
        layout.addWidget(grp_current)

        # --- Encrypted Folder Selection ---
        grp_encrypted = QGroupBox("📁 Select Encrypted Folder (dist/)")
        layout_encrypted = QFormLayout()
        
        enc_folder_row = QHBoxLayout()
        self.input_encrypted_folder = QLineEdit()
        self.input_encrypted_folder.setPlaceholderText("Select the 'dist' folder containing encrypted files")
        self.input_encrypted_folder.textChanged.connect(self.update_changes_preview)
        
        btn_browse_enc = QPushButton("Browse")
        btn_browse_enc.clicked.connect(self.select_encrypted_folder)
        
        enc_folder_row.addWidget(self.input_encrypted_folder)
        enc_folder_row.addWidget(btn_browse_enc)
        
        layout_encrypted.addRow("Dist Folder:", enc_folder_row)
        

        
        # User field
        self.input_user = QLineEdit()
        self.input_user.setText(os.getlogin())
        self.input_user.textChanged.connect(self.update_changes_preview)
        layout_encrypted.addRow("System User:", self.input_user)
        
        grp_encrypted.setLayout(layout_encrypted)
        layout.addWidget(grp_encrypted)

        # --- Required Changes Preview ---
        grp_changes = QGroupBox("🔄 Required Changes for Encryption")
        layout_changes = QVBoxLayout()
        
        self.txt_changes = QTextEdit()
        self.txt_changes.setReadOnly(True)
        self.txt_changes.setMaximumHeight(200)
        self.txt_changes.setStyleSheet("background-color: #1a1a2e; color: #00ff00; font-family: monospace;")
        self.txt_changes.setPlaceholderText("Select encrypted folder to see required changes...")
        layout_changes.addWidget(self.txt_changes)
        
        grp_changes.setLayout(layout_changes)
        layout.addWidget(grp_changes)

        # --- Sudo Password & Apply ---
        grp_apply = QGroupBox("🔑 Apply Changes")
        layout_apply = QFormLayout()
        
        self.input_sudo = QLineEdit()
        self.input_sudo.setEchoMode(QLineEdit.Password)
        self.input_sudo.setPlaceholderText("Enter sudo password for systemctl operations")
        layout_apply.addRow("Sudo Password:", self.input_sudo)
        
        grp_apply.setLayout(layout_apply)
        layout.addWidget(grp_apply)

        # Apply Button
        self.btn_apply = QPushButton("⚡ APPLY CHANGES TO SERVICE")
        self.btn_apply.setFixedHeight(50)
        self.btn_apply.setStyleSheet("""
            QPushButton {
                background-color: #0066CC;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #0080FF;
            }
            QPushButton:disabled {
                background-color: #666666;
            }
        """)
        self.btn_apply.clicked.connect(self.apply_changes)
        layout.addWidget(self.btn_apply)

        # --- Logs ---
        layout.addWidget(QLabel("📋 Service Configuration Logs:"))
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(120)
        self.log_output.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: monospace;")
        layout.addWidget(self.log_output)

    def load_services(self):
        """Load all systemd services into the dropdown."""
        try:
            # Use list-unit-files to get ALL installed services, not just loaded ones
            result = subprocess.run(
                ['systemctl', 'list-unit-files', '--type=service', '--plain', '--no-legend'],
                capture_output=True, text=True
            )
            services = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    # list-unit-files format: "<service_name> <state>"
                    parts = line.split()
                    service_name = parts[0] if parts else None
                    if service_name and service_name.endswith('.service'):
                        services.append(service_name)
            
            current = self.combo_service.currentText()
            self.combo_service.clear()
            self.combo_service.addItems(sorted(services))
            
            if current:
                idx = self.combo_service.findText(current)
                if idx >= 0:
                    self.combo_service.setCurrentIndex(idx)
                else:
                    self.combo_service.setCurrentText(current)
        except Exception as e:
            self.log(f"Error loading services: {str(e)}")

    def on_service_changed(self, service_name):
        """Clear config when service changes."""
        self.txt_current_config.clear()
        self.current_service_config = {}

    def parse_service(self):
        """Parse the selected service file and display its configuration."""
        service_name = self.combo_service.currentText()
        if not service_name:
            QMessageBox.warning(self, "No Service", "Please select a service first.")
            return

        service_path = f"/etc/systemd/system/{service_name}"
        
        # Try to read the service file
        try:
            result = subprocess.run(['cat', service_path], capture_output=True, text=True)
            if result.returncode != 0:
                # Try with sudo
                result = subprocess.run(['sudo', 'cat', service_path], capture_output=True, text=True)
            
            if result.returncode == 0:
                content = result.stdout
                self.txt_current_config.setText(content)
                self.parse_service_content(content)
                self.log(f"✅ Parsed service: {service_name}")
            else:
                self.txt_current_config.setText(f"Could not read service file: {service_path}\n{result.stderr}")
                self.log(f"❌ Failed to parse service: {result.stderr}")
        except Exception as e:
            self.txt_current_config.setText(f"Error: {str(e)}")
            self.log(f"❌ Error parsing service: {str(e)}")

    def parse_service_content(self, content):
        """Extract key configuration values from service file content."""
        self.current_service_config = {
            'WorkingDirectory': '',
            'ExecStart': '',
            'Environment': [],
            'User': '',
            'Group': ''
        }
        
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('WorkingDirectory='):
                self.current_service_config['WorkingDirectory'] = line.split('=', 1)[1]
            elif line.startswith('ExecStart='):
                self.current_service_config['ExecStart'] = line.split('=', 1)[1]
            elif line.startswith('Environment='):
                self.current_service_config['Environment'].append(line.split('=', 1)[1])
            elif line.startswith('User='):
                self.current_service_config['User'] = line.split('=', 1)[1]
            elif line.startswith('Group='):
                self.current_service_config['Group'] = line.split('=', 1)[1]

        self.update_changes_preview()

    def select_encrypted_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Encrypted Folder (dist/)")
        if folder:
            self.input_encrypted_folder.setText(folder)

    def _detect_project_folder(self, dist_folder):
        """Auto-detect the project folder inside dist/ (excludes pyarmor_runtime_*)."""
        if not dist_folder or not os.path.isdir(dist_folder):
            return None
        
        for item in os.listdir(dist_folder):
            item_path = os.path.join(dist_folder, item)
            if os.path.isdir(item_path) and not item.startswith('pyarmor_runtime'):
                return item
        return None

    def _calculate_new_working_dir(self, dist_folder):
        """Calculate the new WorkingDirectory by preserving subdirectory structure.
        
        Logic: If original WorkingDirectory ends with same folder name as detected project,
        append any additional subdirectories from the original path.
        
        Example:
          - Original: /home/ai4m/develop/HUL-Laminate-UI/backend
          - Dist: /path/to/dist
          - Project folder in dist: HUL-Laminate-UI
          - New: /path/to/dist/HUL-Laminate-UI/backend
        """
        project_folder = self._detect_project_folder(dist_folder)
        if not project_folder:
            return dist_folder
        
        base_path = os.path.join(dist_folder, project_folder)
        
        # Get original working directory to find subdirectory structure
        original_wd = self.current_service_config.get('WorkingDirectory', '')
        if not original_wd:
            return base_path
        
        # Find if there's a subdirectory after the project name in original
        # E.g., /path/HUL-Laminate-UI/backend -> extract 'backend'
        original_parts = original_wd.replace('\\', '/').split('/')
        
        # Find where project_folder appears in original path
        try:
            project_idx = None
            for i, part in enumerate(original_parts):
                if part == project_folder:
                    project_idx = i
                    break
            
            if project_idx is not None and project_idx < len(original_parts) - 1:
                # There are subdirectories after the project folder
                subdirs = '/'.join(original_parts[project_idx + 1:])
                return os.path.join(base_path, subdirs)
        except:
            pass
        
        return base_path

    def update_changes_preview(self):
        """Update the changes preview based on selected encrypted folder."""
        dist_folder = self.input_encrypted_folder.text()
        user = self.input_user.text()
        
        if not dist_folder:
            self.txt_changes.clear()
            return

        # Calculate new working directory preserving subdirectory structure
        python_path = dist_folder
        new_working_dir = self._calculate_new_working_dir(dist_folder)

        # Build diff display
        changes_text = "=" * 60 + "\n"
        changes_text += "  REQUIRED CHANGES FOR PYARMOR ENCRYPTION\n"
        changes_text += "=" * 60 + "\n\n"

        # WorkingDirectory
        old_wd = self.current_service_config.get('WorkingDirectory', '<not set>')
        changes_text += f"📁 WorkingDirectory:\n"
        changes_text += f"   OLD: {old_wd}\n"
        changes_text += f"   NEW: {new_working_dir}\n\n"

        # ExecStart - PRESERVED (only show, no change)
        old_exec = self.current_service_config.get('ExecStart', '<not set>')
        changes_text += f"▶️ ExecStart:\n"
        changes_text += f"   ✅ PRESERVED (no change needed)\n"
        changes_text += f"   {old_exec}\n\n"

        # PYTHONPATH
        old_pypath = '<not set>'
        for env in self.current_service_config.get('Environment', []):
            if 'PYTHONPATH' in env:
                old_pypath = env
                break
        new_pypath = f'PYTHONPATH={python_path}'
        changes_text += f"🐍 PYTHONPATH Environment:\n"
        changes_text += f"   OLD: {old_pypath}\n"
        changes_text += f"   NEW: {new_pypath}\n\n"

        # User
        old_user = self.current_service_config.get('User', '<not set>')
        changes_text += f"👤 User:\n"
        changes_text += f"   OLD: {old_user}\n"
        changes_text += f"   NEW: {user}\n"

        self.txt_changes.setText(changes_text)

    def generate_new_service_content(self):
        """Generate the new service file content by modifying the original.
        
        Key principle: Preserve the original ExecStart command and only update:
        - WorkingDirectory: point to the encrypted dist folder
        - PYTHONPATH: add/update to include dist folder
        - User/Group: update if specified
        """
        dist_folder = self.input_encrypted_folder.text()
        user = self.input_user.text()

        # Calculate new working directory preserving subdirectory structure
        new_working_dir = self._calculate_new_working_dir(dist_folder)
        python_path = dist_folder

        # Get original service content
        original_content = self.txt_current_config.toPlainText()
        if not original_content or original_content.startswith('Could not read') or original_content.startswith('Error'):
            # Fallback: generate a basic service file if original couldn't be read
            return self._generate_fallback_service_content(new_working_dir, python_path, user)

        # Modify the original content line by line
        new_lines = []
        pythonpath_added = False
        in_service_section = False
        
        for line in original_content.split('\n'):
            stripped = line.strip()
            
            # Track which section we're in
            if stripped == '[Service]':
                in_service_section = True
                new_lines.append(line)
                continue
            elif stripped.startswith('[') and stripped.endswith(']'):
                # Add PYTHONPATH before leaving Service section if not added yet
                if in_service_section and not pythonpath_added:
                    new_lines.append(f'Environment="PYTHONPATH={python_path}"')
                    pythonpath_added = True
                in_service_section = False
                new_lines.append(line)
                continue
            
            # Modify WorkingDirectory
            if stripped.startswith('WorkingDirectory='):
                new_lines.append(f'WorkingDirectory={new_working_dir}')
                continue
            
            # Modify User
            if stripped.startswith('User=') and user:
                new_lines.append(f'User={user}')
                continue
            
            # Modify Group (set to same as User)
            if stripped.startswith('Group=') and user:
                new_lines.append(f'Group={user}')
                continue
            
            # Handle PYTHONPATH environment variable
            if stripped.startswith('Environment=') and 'PYTHONPATH' in stripped:
                new_lines.append(f'Environment="PYTHONPATH={python_path}"')
                pythonpath_added = True
                continue
            
            # Keep all other lines unchanged (including ExecStart!)
            new_lines.append(line)
        
        # If PYTHONPATH was never in the original file, add it after [Service]
        if not pythonpath_added:
            result_lines = []
            for line in new_lines:
                result_lines.append(line)
                if line.strip() == '[Service]':
                    result_lines.append(f'Environment="PYTHONPATH={python_path}"')
            new_lines = result_lines
        
        return '\n'.join(new_lines)

    def _generate_fallback_service_content(self, working_dir, python_path, user):
        """Generate a basic service file when original cannot be read."""
        service_name = self.combo_service.currentText().replace('.service', '')
        return f"""[Unit]
Description=Service for {service_name}
After=network.target

[Service]
User={user}
Group={user}
Environment="PYTHONPATH={python_path}"
Environment="PYTHONUNBUFFERED=1"
WorkingDirectory={working_dir}
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""

    def log(self, message):
        self.log_output.append(message)
        sb = self.log_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def apply_changes(self):
        """Apply the service configuration changes."""
        service_name = self.combo_service.currentText()
        dist_folder = self.input_encrypted_folder.text()
        sudo_pass = self.input_sudo.text()

        if not all([service_name, dist_folder, sudo_pass]):
            QMessageBox.warning(self, "Missing Info", "Please fill all fields.")
            return

        # Validate encrypted folder
        if not os.path.exists(dist_folder):
            QMessageBox.warning(self, "Invalid Folder", "The encrypted folder does not exist.")
            return

        new_config = self.generate_new_service_content()
        
        # Show confirmation
        reply = QMessageBox.question(
            self, "Confirm Changes",
            f"This will update the service '{service_name}' with the new configuration.\n\n"
            "The service will be restarted after the update.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.No:
            return

        self.btn_apply.setEnabled(False)
        self.log_output.clear()

        self.worker = ServiceConfigWorker(service_name, new_config, sudo_pass)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_apply_finished)
        self.worker.start()

    def on_apply_finished(self, success):
        self.btn_apply.setEnabled(True)
        if success:
            QMessageBox.information(self, "Success", "Service configuration updated successfully!")
        else:
            QMessageBox.critical(self, "Failed", "Failed to update service. Check the logs.")


# =============================================================================
# MAIN APPLICATION
# =============================================================================

class PyArmorDeployApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyArmor Encryption & Service Configuration Tool")
        self.setGeometry(100, 100, 900, 800)
        self.init_ui()

    def init_ui(self):
        # Create central widget with tab layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)

        # Header
        header = QLabel("🔐 PyArmor Encryption & Service Configuration Tool")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px; color: #2E8B57;")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #cccccc;
                border-radius: 5px;
            }
            QTabBar::tab {
                background: #e0e0e0;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
            }
            QTabBar::tab:selected {
                background: #2E8B57;
                color: white;
            }
            QTabBar::tab:hover:!selected {
                background: #c0c0c0;
            }
        """)

        # Add tabs
        self.encryption_tab = EncryptionTab()
        self.service_tab = ServiceConfigTab()

        self.tabs.addTab(self.encryption_tab, "🔐 Encrypt Folder")
        self.tabs.addTab(self.service_tab, "⚙️ Configure Service")

        layout.addWidget(self.tabs)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Set application-wide style
    app.setStyle('Fusion')
    
    window = PyArmorDeployApp()
    window.show()
    sys.exit(app.exec_())