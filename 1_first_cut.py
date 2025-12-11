import sys
import os
import subprocess
import configparser
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QListWidget, QLineEdit, QMessageBox, QTextEdit, 
                             QProgressBar, QGroupBox, QFormLayout, QComboBox)
from PyQt5.QtCore import QThread, pyqtSignal

# --- WORKER THREAD FOR LONG RUNNING TASKS ---
class DeploymentWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, folder, main_script, service_name, sudo_pass, user_name):
        super().__init__()
        self.folder = folder
        self.main_script = main_script
        self.service_name = service_name
        self.sudo_pass = sudo_pass
        self.user_name = user_name

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
            
            if stdout: self.log_signal.emit(stdout)
            if stderr: self.log_signal.emit(f"STDERR: {stderr}")
            
            return process.returncode == 0
        except Exception as e:
            self.log_signal.emit(f"Error: {str(e)}")
            return False

    def run(self):
        # --- PHASE 1 & 2: PREP AND ENCRYPTION [cite: 6, 19] ---
        self.log_signal.emit("--- Starting Phase 1: Preparation ---")
        
        # 1. Config Data Files 
        if not self.run_command("pyarmor cfg data_files=*"):
            self.finished_signal.emit(False)
            return

        # 2. Clean Output Folder [cite: 16, 17]
        dist_path = os.path.join(self.folder, "dist")
        if os.path.exists(dist_path):
            self.run_command(f"rm -rf {dist_path}")

        # 3. Run Encryption [cite: 20, 22]
        # Command: pyarmor gen -O dist -r <PROJECT_FOLDER>
        self.log_signal.emit(f"--- Starting Phase 2: Encryption of {self.folder} ---")
        enc_cmd = f"pyarmor gen -O {dist_path} -r --exclude '*/.venv/**' --exclude '*/__pycache__/**' {self.folder}"
        if not self.run_command(enc_cmd):
            self.finished_signal.emit(False)
            return

        # --- PHASE 3: SYSTEMD SERVICE CONFIGURATION [cite: 45] ---
        self.log_signal.emit("--- Starting Phase 3: Service Configuration ---")

        # Define Paths based on PDF Critical Fixes [cite: 65]
        # PYTHONPATH must be the 'dist' folder (parent of pyarmor_runtime) [cite: 67]
        python_path = dist_path
        
        # WorkingDirectory must be the script's folder inside dist [cite: 72]
        project_dir_name = os.path.basename(self.folder)
        working_dir = os.path.join(dist_path, project_dir_name)
        
        # ExecStart points to the encrypted script [cite: 57]
        exec_start = f"/usr/bin/python3 {os.path.join(working_dir, self.main_script)}"

        # Construct Service File Content [cite: 49-62]
        service_content = f"""[Unit]
Description=Service for PyArmor Protected Application {project_dir_name}
After=network.target

[Service]
User={self.user_name}
Group={self.user_name}
Environment="PYTHONPATH={python_path}"
Environment="PYTHONUNBUFFERED=1"
WorkingDirectory={working_dir}
ExecStart={exec_start}
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
        
        # Save service file locally first
        local_svc_path = os.path.join(os.getcwd(), self.service_name)
        with open(local_svc_path, "w") as f:
            f.write(service_content)
        
        self.log_signal.emit(f"Generated Service File at: {local_svc_path}")

        # Move to /etc/systemd/system/ [cite: 48]
        target_svc_path = f"/etc/systemd/system/{self.service_name}"
        if not self.run_command(f"mv {local_svc_path} {target_svc_path}", sudo=True):
            self.finished_signal.emit(False)
            return

        # --- PHASE 4: DEPLOYMENT [cite: 75] ---
        self.log_signal.emit("--- Starting Phase 4: Deployment ---")

        # Reload Daemon [cite: 77]
        self.run_command("systemctl daemon-reload", sudo=True)
        
        # Enable and Restart Service [cite: 93, 97]
        self.run_command(f"systemctl enable {self.service_name}", sudo=True)
        self.run_command(f"systemctl restart {self.service_name}", sudo=True)

        self.log_signal.emit("SUCCESS: Deployment Complete.")
        self.finished_signal.emit(True)


# --- MAIN GUI APPLICATION ---
class PyArmorDeployApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyArmor & Systemd Auto-Deployer")
        self.setGeometry(100, 100, 900, 700)
        
        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # 1. Project Selection Section
        grp_project = QGroupBox("1. Select Project")
        layout_proj = QHBoxLayout()
        
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Select the root folder of your python project")
        btn_browse = QPushButton("Browse Folder")
        btn_browse.clicked.connect(self.select_folder)
        
        layout_proj.addWidget(self.path_input)
        layout_proj.addWidget(btn_browse)
        grp_project.setLayout(layout_proj)
        layout.addWidget(grp_project)

        # 2. File & Service Config Section
        grp_config = QGroupBox("2. Configuration")
        layout_config = QFormLayout()

        self.list_files = QListWidget()
        self.list_files.setFixedHeight(100)
        self.list_files.itemClicked.connect(self.auto_fill_service_name)
        
        self.input_main_script = QLineEdit()
        self.input_main_script.setPlaceholderText("Click a file above to select main script (e.g., file1.py)")
        
        # Service name dropdown with refresh button
        service_layout = QHBoxLayout()
        self.input_service_name = QComboBox()
        self.input_service_name.setEditable(True)  # Allow typing new service names
        self.input_service_name.setPlaceholderText("Select or type service name")
        self.load_system_services()  # Populate on startup
        
        btn_refresh_services = QPushButton("🔄")
        btn_refresh_services.setFixedWidth(40)
        btn_refresh_services.setToolTip("Refresh service list")
        btn_refresh_services.clicked.connect(self.load_system_services)
        
        service_layout.addWidget(self.input_service_name)
        service_layout.addWidget(btn_refresh_services)
        
        self.input_user = QLineEdit()
        self.input_user.setText(os.getlogin()) # Default to current user
        
        self.input_sudo = QLineEdit()
        self.input_sudo.setEchoMode(QLineEdit.Password)
        self.input_sudo.setPlaceholderText("Enter Sudo Password for Systemd operations")

        layout_config.addRow("Detected Python Files:", self.list_files)
        layout_config.addRow("Main Script:", self.input_main_script)
        layout_config.addRow("Service Name (.service):", service_layout)
        layout_config.addRow("System User:", self.input_user)
        layout_config.addRow("Sudo Password:", self.input_sudo)
        
        grp_config.setLayout(layout_config)
        layout.addWidget(grp_config)

        # 3. Action Section
        self.btn_deploy = QPushButton("ENCRYPT & UPDATE SERVICE (One-Click)")
        self.btn_deploy.setFixedHeight(50)
        self.btn_deploy.setStyleSheet("background-color: #2E8B57; color: white; font-weight: bold; font-size: 14px;")
        self.btn_deploy.clicked.connect(self.start_deployment)
        layout.addWidget(self.btn_deploy)

        # 4. Logs
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: #1e1e1e; color: #00ff00; font-family: monospace;")
        layout.addWidget(QLabel("Process Logs:"))
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
            for file in files:
                if file.endswith(".py"):
                    # relative path logic if needed, currently storing filename
                    py_files.append(file)
        
        self.list_files.addItems(py_files)
        if not py_files:
            self.log("No Python files found in selected folder.")

    def load_system_services(self):
        """Load all systemd services into the dropdown."""
        try:
            result = subprocess.run(
                ['systemctl', 'list-units', '--type=service', '--all', '--plain', '--no-legend'],
                capture_output=True, text=True
            )
            services = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    # First column is the service name
                    service_name = line.split()[0] if line.split() else None
                    if service_name and service_name.endswith('.service'):
                        services.append(service_name)
            
            # Remember current selection
            current = self.input_service_name.currentText()
            
            self.input_service_name.clear()
            self.input_service_name.addItems(sorted(services))
            
            # Restore selection if it existed
            if current:
                idx = self.input_service_name.findText(current)
                if idx >= 0:
                    self.input_service_name.setCurrentIndex(idx)
                else:
                    self.input_service_name.setCurrentText(current)
                    
        except Exception as e:
            self.log(f"Error loading services: {str(e)}")

    def auto_fill_service_name(self, item):
        filename = item.text()
        self.input_main_script.setText(filename)
        # Suggest a service name based on file name (minus extension)
        service_name = filename.replace(".py", "") + ".service"
        self.input_service_name.setCurrentText(service_name)

    def log(self, message):
        self.log_output.append(message)
        # Scroll to bottom
        sb = self.log_output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def start_deployment(self):
        folder = self.path_input.text()
        script = self.input_main_script.text()
        svc = self.input_service_name.currentText()  # Use currentText for QComboBox
        user = self.input_user.text()
        pwd = self.input_sudo.text()

        if not all([folder, script, svc, user, pwd]):
            QMessageBox.warning(self, "Missing Info", "Please fill all fields and select a main script.")
            return

        self.btn_deploy.setEnabled(False)
        self.log_output.clear()
        
        # Start Worker Thread
        self.worker = DeploymentWorker(folder, script, svc, pwd, user)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, success):
        self.btn_deploy.setEnabled(True)
        if success:
            QMessageBox.information(self, "Success", "Encryption and Service Update Completed Successfully!")
        else:
            QMessageBox.critical(self, "Failed", "The deployment encountered errors. Check the logs.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PyArmorDeployApp()
    window.show()
    sys.exit(app.exec_())