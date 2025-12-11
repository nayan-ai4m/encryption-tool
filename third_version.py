import sys
import os
import subprocess
import glob
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QFileDialog, 
                             QListWidget, QLineEdit, QMessageBox, QTextEdit, 
                             QGroupBox, QFormLayout, QComboBox, QTabWidget,
                             QCheckBox, QFrame, QScrollArea, QRadioButton,
                             QButtonGroup, QDialog, QDialogButtonBox, QProgressBar)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont

# SSH Support
try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False
    print("Warning: paramiko not installed. SSH functionality will be disabled.")
    print("Install with: pip install paramiko")


# =============================================================================
# SSH CONNECTION & EXECUTOR ABSTRACTION
# =============================================================================

class SSHConnection:
    """Manages SSH connection to remote system."""
    
    def __init__(self):
        self.client = None
        self.sftp = None
        self.host = None
        self.username = None
        self._connected = False
    
    def connect(self, host, username, password, port=22):
        """Establish SSH connection."""
        if not SSH_AVAILABLE:
            raise RuntimeError("paramiko not installed. Run: pip install paramiko")
        
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            self.client.connect(host, port=port, username=username, password=password, timeout=10)
            self.sftp = self.client.open_sftp()
            self.host = host
            self.username = username
            self._connected = True
            return True
        except Exception as e:
            self._connected = False
            raise e
    
    def disconnect(self):
        """Close SSH connection."""
        if self.sftp:
            self.sftp.close()
            self.sftp = None
        if self.client:
            self.client.close()
            self.client = None
        self._connected = False
        self.host = None
        self.username = None
    
    def is_connected(self):
        """Check if connection is active."""
        return self._connected and self.client is not None
    
    def exec_command(self, cmd, get_pty=False):
        """Execute command on remote system. Returns (success, stdout, stderr).
        
        Note: SSH non-interactive shells don't load .bashrc, so we explicitly
        add ~/.local/bin to PATH for user-installed packages like pyarmor.
        """
        if not self.is_connected():
            return False, "", "Not connected to SSH"
        
        # Prepend PATH with common user bin directories to ensure user-installed
        # packages (pip --user) are found in non-interactive SSH sessions
        path_prefix = 'export PATH="$HOME/.local/bin:$HOME/bin:/usr/local/bin:$PATH" && '
        full_cmd = path_prefix + cmd
        
        try:
            stdin, stdout, stderr = self.client.exec_command(full_cmd, get_pty=get_pty)
            out = stdout.read().decode('utf-8')
            err = stderr.read().decode('utf-8')
            exit_code = stdout.channel.recv_exit_status()
            return exit_code == 0, out, err
        except Exception as e:
            return False, "", str(e)
    
    def exec_sudo_command(self, cmd, sudo_pass):
        """Execute command with sudo on remote system."""
        full_cmd = f"echo {sudo_pass} | sudo -S {cmd}"
        return self.exec_command(full_cmd, get_pty=True)
    
    def read_file(self, remote_path):
        """Read file content from remote system."""
        if not self.is_connected():
            return None
        
        try:
            with self.sftp.open(remote_path, 'r') as f:
                return f.read().decode('utf-8')
        except Exception:
            return None
    
    def write_file(self, remote_path, content):
        """Write content to file on remote system."""
        if not self.is_connected():
            return False
        
        try:
            with self.sftp.open(remote_path, 'w') as f:
                f.write(content)
            return True
        except Exception:
            return False
    
    def file_exists(self, remote_path):
        """Check if file exists on remote system."""
        if not self.is_connected():
            return False
        
        try:
            self.sftp.stat(remote_path)
            return True
        except:
            return False
    
    def list_dir(self, remote_path):
        """List directory contents on remote system."""
        if not self.is_connected():
            return []
        
        try:
            return self.sftp.listdir(remote_path)
        except:
            return []
    
    def is_dir(self, remote_path):
        """Check if path is a directory on remote system."""
        if not self.is_connected():
            return False
        
        try:
            import stat
            return stat.S_ISDIR(self.sftp.stat(remote_path).st_mode)
        except:
            return False


class CommandExecutor:
    """Abstract base for command execution - local or remote."""
    
    def run_command(self, cmd):
        """Execute command. Returns (success, stdout, stderr)."""
        raise NotImplementedError
    
    def run_sudo_command(self, cmd, sudo_pass):
        """Execute command with sudo. Returns (success, stdout, stderr)."""
        raise NotImplementedError
    
    def read_file(self, path):
        """Read file content."""
        raise NotImplementedError
    
    def write_file(self, path, content):
        """Write content to file."""
        raise NotImplementedError
    
    def file_exists(self, path):
        """Check if file exists."""
        raise NotImplementedError
    
    def list_dir(self, path):
        """List directory contents."""
        raise NotImplementedError
    
    def is_dir(self, path):
        """Check if path is directory."""
        raise NotImplementedError
    
    def glob_files(self, pattern):
        """Find files matching glob pattern."""
        raise NotImplementedError
    
    def get_file_mtime(self, path):
        """Get file modification time."""
        raise NotImplementedError


class LocalExecutor(CommandExecutor):
    """Execute commands on local system using subprocess."""
    
    def run_command(self, cmd):
        try:
            process = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            stdout, stderr = process.communicate()
            return process.returncode == 0, stdout, stderr
        except Exception as e:
            return False, "", str(e)
    
    def run_sudo_command(self, cmd, sudo_pass):
        full_cmd = f"echo {sudo_pass} | sudo -S {cmd}"
        return self.run_command(full_cmd)
    
    def read_file(self, path):
        try:
            with open(path, 'r') as f:
                return f.read()
        except:
            return None
    
    def write_file(self, path, content):
        try:
            with open(path, 'w') as f:
                f.write(content)
            return True
        except:
            return False
    
    def file_exists(self, path):
        return os.path.exists(path)
    
    def list_dir(self, path):
        try:
            return os.listdir(path)
        except:
            return []
    
    def is_dir(self, path):
        return os.path.isdir(path)
    
    def glob_files(self, pattern):
        return glob.glob(pattern)
    
    def get_file_mtime(self, path):
        try:
            return os.path.getmtime(path)
        except:
            return None


class RemoteExecutor(CommandExecutor):
    """Execute commands on remote system via SSH."""
    
    def __init__(self, ssh_connection):
        self.ssh = ssh_connection
    
    def run_command(self, cmd):
        return self.ssh.exec_command(cmd)
    
    def run_sudo_command(self, cmd, sudo_pass):
        return self.ssh.exec_sudo_command(cmd, sudo_pass)
    
    def read_file(self, path):
        return self.ssh.read_file(path)
    
    def write_file(self, path, content):
        return self.ssh.write_file(path, content)
    
    def file_exists(self, path):
        return self.ssh.file_exists(path)
    
    def list_dir(self, path):
        return self.ssh.list_dir(path)
    
    def is_dir(self, path):
        return self.ssh.is_dir(path)
    
    def glob_files(self, pattern):
        """Remote glob using find command."""
        parent_dir = os.path.dirname(pattern)
        file_pattern = os.path.basename(pattern)
        # Use find command for remote glob
        success, stdout, _ = self.ssh.exec_command(f"find {parent_dir} -maxdepth 1 -name '{file_pattern}' 2>/dev/null")
        if success and stdout.strip():
            return stdout.strip().split('\n')
        return []
    
    def get_file_mtime(self, path):
        success, stdout, _ = self.ssh.exec_command(f"stat -c %Y {path} 2>/dev/null")
        if success and stdout.strip():
            try:
                return float(stdout.strip())
            except:
                pass
        return None


# =============================================================================
# SSH CONNECTION DIALOG
# =============================================================================

class SSHConnectionDialog(QDialog):
    """Dialog for SSH connection settings."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🌐 Connect to Remote System")
        self.setMinimumWidth(400)
        self.ssh_connection = None
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Connection type selection
        grp_type = QGroupBox("Connection Type")
        layout_type = QVBoxLayout()
        
        self.btn_group = QButtonGroup(self)
        self.radio_local = QRadioButton("🖥️ Local System")
        self.radio_remote = QRadioButton("🌐 Remote System (SSH)")
        self.radio_local.setChecked(True)
        
        self.btn_group.addButton(self.radio_local, 0)
        self.btn_group.addButton(self.radio_remote, 1)
        
        layout_type.addWidget(self.radio_local)
        layout_type.addWidget(self.radio_remote)
        grp_type.setLayout(layout_type)
        layout.addWidget(grp_type)
        
        # SSH Settings (shown when remote selected)
        self.grp_ssh = QGroupBox("🔐 SSH Connection Settings")
        layout_ssh = QFormLayout()
        
        self.input_host = QLineEdit()
        self.input_host.setPlaceholderText("e.g., 192.168.1.100 or hostname.local")
        layout_ssh.addRow("Host/IP:", self.input_host)
        
        self.input_port = QLineEdit()
        self.input_port.setText("22")
        self.input_port.setMaximumWidth(80)
        layout_ssh.addRow("Port:", self.input_port)
        
        self.input_username = QLineEdit()
        self.input_username.setPlaceholderText("SSH username")
        layout_ssh.addRow("Username:", self.input_username)
        
        self.input_password = QLineEdit()
        self.input_password.setEchoMode(QLineEdit.Password)
        self.input_password.setPlaceholderText("SSH password")
        layout_ssh.addRow("Password:", self.input_password)
        
        self.grp_ssh.setLayout(layout_ssh)
        self.grp_ssh.setEnabled(False)
        layout.addWidget(self.grp_ssh)
        
        # Test connection button
        self.btn_test = QPushButton("🔗 Test Connection")
        self.btn_test.clicked.connect(self.test_connection)
        self.btn_test.setEnabled(False)
        layout.addWidget(self.btn_test)
        
        # Status label
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("padding: 10px;")
        layout.addWidget(self.lbl_status)
        
        # Dialog buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        
        # Connect signals
        self.radio_remote.toggled.connect(self.on_remote_toggled)
    
    def on_remote_toggled(self, checked):
        self.grp_ssh.setEnabled(checked)
        self.btn_test.setEnabled(checked)
        if not checked:
            self.lbl_status.setText("")
    
    def test_connection(self):
        if not SSH_AVAILABLE:
            self.lbl_status.setText("❌ paramiko not installed. Run: pip install paramiko")
            self.lbl_status.setStyleSheet("color: red; padding: 10px;")
            return
        
        host = self.input_host.text().strip()
        port = int(self.input_port.text() or "22")
        username = self.input_username.text().strip()
        password = self.input_password.text()
        
        if not all([host, username, password]):
            self.lbl_status.setText("❌ Please fill all fields")
            self.lbl_status.setStyleSheet("color: red; padding: 10px;")
            return
        
        self.lbl_status.setText("🔄 Connecting...")
        self.lbl_status.setStyleSheet("color: blue; padding: 10px;")
        QApplication.processEvents()
        
        try:
            ssh = SSHConnection()
            ssh.connect(host, username, password, port)
            ssh.disconnect()
            self.lbl_status.setText("✅ Connection successful!")
            self.lbl_status.setStyleSheet("color: green; padding: 10px; font-weight: bold;")
        except Exception as e:
            self.lbl_status.setText(f"❌ Failed: {str(e)}")
            self.lbl_status.setStyleSheet("color: red; padding: 10px;")
    
    def get_connection_info(self):
        """Returns (is_remote, host, port, username, password)"""
        is_remote = self.radio_remote.isChecked()
        if is_remote:
            return (
                True,
                self.input_host.text().strip(),
                int(self.input_port.text() or "22"),
                self.input_username.text().strip(),
                self.input_password.text()
            )
        return (False, None, None, None, None)


# =============================================================================
# REMOTE FOLDER BROWSER DIALOG
# =============================================================================

class RemoteFolderBrowser(QDialog):
    """Dialog for browsing folders on remote system via SFTP."""
    
    def __init__(self, executor, parent=None, start_path="/home"):
        super().__init__(parent)
        self.executor = executor
        self.current_path = start_path
        self.selected_path = None
        self.setWindowTitle("🌐 Browse Remote Folder")
        self.setMinimumSize(500, 400)
        self.init_ui()
        self.load_directory(start_path)
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Current path display
        path_layout = QHBoxLayout()
        self.lbl_path = QLabel("Path:")
        self.input_path = QLineEdit()
        self.input_path.returnPressed.connect(self.on_path_entered)
        btn_go = QPushButton("Go")
        btn_go.clicked.connect(self.on_path_entered)
        btn_go.setMaximumWidth(50)
        
        path_layout.addWidget(self.lbl_path)
        path_layout.addWidget(self.input_path)
        path_layout.addWidget(btn_go)
        layout.addLayout(path_layout)
        
        # Navigation buttons
        nav_layout = QHBoxLayout()
        btn_up = QPushButton("⬆️ Parent Folder")
        btn_up.clicked.connect(self.go_up)
        btn_home = QPushButton("🏠 Home")
        btn_home.clicked.connect(self.go_home)
        btn_refresh = QPushButton("🔄 Refresh")
        btn_refresh.clicked.connect(self.refresh)
        
        nav_layout.addWidget(btn_up)
        nav_layout.addWidget(btn_home)
        nav_layout.addWidget(btn_refresh)
        nav_layout.addStretch()
        layout.addLayout(nav_layout)
        
        # Folder list
        self.list_folders = QListWidget()
        self.list_folders.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.list_folders.itemClicked.connect(self.on_item_clicked)
        self.list_folders.setStyleSheet("""
            QListWidget::item {
                padding: 5px;
            }
            QListWidget::item:selected {
                background-color: #0066CC;
                color: white;
            }
        """)
        layout.addWidget(self.list_folders)
        
        # Status
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(self.lbl_status)
        
        # Dialog buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        btn_select = QPushButton("✅ Select This Folder")
        btn_select.clicked.connect(self.select_current_folder)
        btn_select.setStyleSheet("background-color: #2E8B57; color: white; padding: 8px 16px;")
        
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addWidget(btn_select)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
    
    def load_directory(self, path):
        """Load directory contents from remote system."""
        self.list_folders.clear()
        self.current_path = path
        self.input_path.setText(path)
        
        self.lbl_status.setText("Loading...")
        QApplication.processEvents()
        
        try:
            # Get directory listing using ls command
            success, stdout, stderr = self.executor.run_command(
                f"ls -la {path} 2>/dev/null | tail -n +2"
            )
            
            if not success:
                self.lbl_status.setText(f"Error: Cannot access {path}")
                return
            
            folders = []
            files = []
            
            for line in stdout.strip().split('\n'):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 9:
                    perms = parts[0]
                    name = ' '.join(parts[8:])  # Handle names with spaces
                    
                    if name in ['.', '..']:
                        continue
                    
                    if perms.startswith('d'):
                        folders.append(f"📁 {name}")
                    else:
                        files.append(f"📄 {name}")
            
            # Add folders first, then files
            for folder in sorted(folders):
                self.list_folders.addItem(folder)
            for file in sorted(files):
                item = self.list_folders.addItem(file)
            
            self.lbl_status.setText(f"{len(folders)} folders, {len(files)} files")
            
        except Exception as e:
            self.lbl_status.setText(f"Error: {str(e)}")
    
    def on_item_double_clicked(self, item):
        """Navigate into folder on double-click."""
        text = item.text()
        if text.startswith("📁 "):
            folder_name = text[2:]  # Remove emoji prefix (📁 = 2 chars)
            new_path = os.path.join(self.current_path, folder_name)
            self.load_directory(new_path)
    
    def on_item_clicked(self, item):
        """Update path when item is clicked."""
        text = item.text()
        if text.startswith("📁 "):
            folder_name = text[2:]
            self.input_path.setText(os.path.join(self.current_path, folder_name))
    
    def on_path_entered(self):
        """Navigate to manually entered path."""
        path = self.input_path.text().strip()
        if path:
            # Check if path exists
            success, stdout, _ = self.executor.run_command(f"test -d {path} && echo 'exists'")
            if success and 'exists' in stdout:
                self.load_directory(path)
            else:
                self.lbl_status.setText(f"Path not found: {path}")
    
    def go_up(self):
        """Go to parent directory."""
        parent = os.path.dirname(self.current_path)
        if parent:
            self.load_directory(parent)
    
    def go_home(self):
        """Go to home directory."""
        success, stdout, _ = self.executor.run_command("echo $HOME")
        if success and stdout.strip():
            self.load_directory(stdout.strip())
        else:
            self.load_directory("/home")
    
    def refresh(self):
        """Refresh current directory."""
        self.load_directory(self.current_path)
    
    def select_current_folder(self):
        """Select the current folder and close dialog."""
        # Check if an item is selected
        selected = self.list_folders.currentItem()
        if selected and selected.text().startswith("📁 "):
            folder_name = selected.text()[2:]
            self.selected_path = os.path.join(self.current_path, folder_name)
        else:
            self.selected_path = self.current_path
        self.accept()
    
    def get_selected_path(self):
        """Return the selected path."""
        return self.selected_path


# =============================================================================
# WORKER THREADS
# =============================================================================

class EncryptionWorker(QThread):
    """Worker thread for PyArmor encryption - supports local and remote."""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)  # success, dist_path

    def __init__(self, folder, executor):
        super().__init__()
        self.folder = folder
        self.executor = executor

    def log(self, msg):
        self.log_signal.emit(msg)

    def run(self):
        self.log("--- Starting Encryption Process ---")
        
        # 1. Configure PyArmor to include data files
        self.log("Executing: pyarmor cfg data_files=*")
        success, stdout, stderr = self.executor.run_command("pyarmor cfg data_files=*")
        if stdout:
            self.log(stdout)
        if stderr:
            self.log(f"STDERR: {stderr}")
        if not success:
            self.log("❌ Failed to configure PyArmor")
            self.finished_signal.emit(False, "")
            return

        # 2. Clean existing dist folder
        dist_path = os.path.join(self.folder, "dist")
        if self.executor.file_exists(dist_path):
            self.log(f"Cleaning existing dist folder: {dist_path}")
            self.executor.run_command(f"rm -rf {dist_path}")

        # 3. Run PyArmor encryption
        self.log(f"Encrypting folder: {self.folder}")
        enc_cmd = f"pyarmor gen -O {dist_path} -r --exclude '*/.venv/**' --exclude '*/__pycache__/**' {self.folder}"
        self.log(f"Executing: {enc_cmd}")
        success, stdout, stderr = self.executor.run_command(enc_cmd)
        if stdout:
            self.log(stdout)
        if stderr:
            self.log(f"STDERR: {stderr}")
        if not success:
            self.log("❌ Encryption failed!")
            self.finished_signal.emit(False, "")
            return

        self.log("✅ Encryption completed successfully!")
        self.finished_signal.emit(True, dist_path)


class ServiceConfigWorker(QThread):
    """Worker thread for service configuration updates - supports local and remote."""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)

    def __init__(self, service_name, new_config, sudo_pass, executor):
        super().__init__()
        self.service_name = service_name
        self.new_config = new_config
        self.sudo_pass = sudo_pass
        self.executor = executor

    def log(self, msg):
        self.log_signal.emit(msg)

    def run(self):
        self.log("--- Updating Service Configuration ---")
        
        # 1. Write new service file to temp location
        temp_path = f"/tmp/{self.service_name}"
        self.log(f"Writing service file to: {temp_path}")
        if not self.executor.write_file(temp_path, self.new_config):
            self.log("❌ Failed to write temp service file")
            self.finished_signal.emit(False)
            return
        self.log(f"Generated service file at: {temp_path}")

        # 2. Move to systemd directory
        target_path = f"/etc/systemd/system/{self.service_name}"
        self.log(f"Moving to: {target_path}")
        success, stdout, stderr = self.executor.run_sudo_command(f"mv {temp_path} {target_path}", self.sudo_pass)
        if stdout:
            self.log(stdout)
        if not success:
            self.log(f"❌ Failed to move service file: {stderr}")
            self.finished_signal.emit(False)
            return

        # 3. Reload systemd daemon
        self.log("Reloading systemd daemon...")
        self.executor.run_sudo_command("systemctl daemon-reload", self.sudo_pass)
        
        # 4. Restart service
        self.log(f"Restarting {self.service_name}...")
        success, stdout, stderr = self.executor.run_sudo_command(f"systemctl restart {self.service_name}", self.sudo_pass)
        if stdout:
            self.log(stdout)

        self.log("✅ Service configuration updated successfully!")
        self.finished_signal.emit(True)


# =============================================================================
# TAB 1: ENCRYPTION TAB
# =============================================================================

class EncryptionTab(QWidget):
    """Tab for encrypting Python projects with PyArmor."""
    
    def __init__(self, executor):
        super().__init__()
        self.executor = executor
        self.init_ui()
        self.worker = None

    def set_executor(self, executor):
        """Update the executor (when connection changes)."""
        self.executor = executor
        self.check_encryption_status()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        # --- Folder Selection ---
        grp_folder = QGroupBox("📁 Select Project Folder")
        layout_folder = QVBoxLayout()
        
        folder_row = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Enter the path to your Python project (on target system)")
        self.path_input.textChanged.connect(self.check_encryption_status)
        
        self.btn_browse = QPushButton("📂 Browse")
        self.btn_browse.clicked.connect(self.select_folder)
        
        folder_row.addWidget(self.path_input)
        folder_row.addWidget(self.btn_browse)
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
        """Open folder browser - local or remote based on executor type."""
        if isinstance(self.executor, RemoteExecutor):
            # Use remote folder browser
            dialog = RemoteFolderBrowser(self.executor, self)
            if dialog.exec_() == QDialog.Accepted:
                folder = dialog.get_selected_path()
                if folder:
                    self.path_input.setText(folder)
                    self.scan_files(folder)
        else:
            # Use local file dialog
            folder = QFileDialog.getExistingDirectory(self, "Select Project Folder")
            if folder:
                self.path_input.setText(folder)
                self.scan_files(folder)

    def scan_files(self, folder):
        """Scan for Python files (works for local only, shows message for remote)."""
        self.list_files.clear()
        
        if isinstance(self.executor, RemoteExecutor):
            # For remote, use find command
            success, stdout, _ = self.executor.run_command(
                f"find {folder} -name '*.py' -not -path '*/.venv/*' -not -path '*/__pycache__/*' -not -path '*/dist/*' 2>/dev/null | head -20"
            )
            if success and stdout.strip():
                files = stdout.strip().split('\n')
                for f in files:
                    rel_path = os.path.relpath(f, folder) if f.startswith(folder) else f
                    self.list_files.addItem(rel_path)
                if len(files) >= 20:
                    self.list_files.addItem("... (showing first 20 files)")
            else:
                self.log("No Python files found or cannot access remote folder.")
        else:
            # Local scanning
            py_files = []
            for root, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if d not in ['.venv', 'venv', '__pycache__', 'dist']]
                for file in files:
                    if file.endswith(".py"):
                        rel_path = os.path.relpath(os.path.join(root, file), folder)
                        py_files.append(rel_path)
            
            self.list_files.addItems(py_files[:20])
            if len(py_files) > 20:
                self.list_files.addItem(f"... and {len(py_files) - 20} more files")
            if not py_files:
                self.log("No Python files found in selected folder.")

    def check_encryption_status(self):
        folder = self.path_input.text()
        if not folder:
            self.status_label.setText("No folder selected")
            self.status_label.setStyleSheet("font-size: 14px; padding: 10px; color: gray;")
            return

        # Check if folder exists
        if not self.executor.is_dir(folder):
            self.status_label.setText("❌ Folder not found")
            self.status_label.setStyleSheet("font-size: 14px; padding: 10px; color: red;")
            return

        dist_path = os.path.join(folder, "dist")
        
        # Check for pyarmor_runtime_* folder inside dist
        runtime_folders = self.executor.glob_files(os.path.join(dist_path, "pyarmor_runtime_*"))
        if runtime_folders:
            mtime = self.executor.get_file_mtime(runtime_folders[0])
            if mtime:
                from datetime import datetime
                mod_time = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                self.status_label.setText(f"✅ Already Encrypted (Last: {mod_time})")
            else:
                self.status_label.setText("✅ Already Encrypted")
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
        
        if not folder:
            QMessageBox.warning(self, "Missing Folder", "Please enter a valid project folder path.")
            return

        # Check if folder exists
        if not self.executor.is_dir(folder):
            QMessageBox.warning(self, "Invalid Folder", "The specified folder does not exist on the target system.")
            return

        # Check if already encrypted and re-encrypt not checked
        dist_path = os.path.join(folder, "dist")
        runtime_folders = self.executor.glob_files(os.path.join(dist_path, "pyarmor_runtime_*"))
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
        
        self.worker = EncryptionWorker(folder, self.executor)
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
    
    def __init__(self, executor):
        super().__init__()
        self.executor = executor
        self.current_service_config = {}
        self.init_ui()
        self.worker = None

    def set_executor(self, executor):
        """Update the executor (when connection changes)."""
        self.executor = executor
        self.load_services()

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
        self.input_encrypted_folder.setPlaceholderText("Enter path to 'dist' folder on target system")
        self.input_encrypted_folder.textChanged.connect(self.update_changes_preview)
        
        self.btn_browse_enc = QPushButton("📂 Browse")
        self.btn_browse_enc.clicked.connect(self.select_encrypted_folder)
        
        enc_folder_row.addWidget(self.input_encrypted_folder)
        enc_folder_row.addWidget(self.btn_browse_enc)
        
        layout_encrypted.addRow("Dist Folder:", enc_folder_row)
        
        # User field
        self.input_user = QLineEdit()
        try:
            self.input_user.setText(os.getlogin())
        except:
            self.input_user.setText("")
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
            success, stdout, stderr = self.executor.run_command(
                "systemctl list-unit-files --type=service --plain --no-legend"
            )
            services = []
            if success:
                for line in stdout.strip().split('\n'):
                    if line:
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
        content = self.executor.read_file(service_path)
        if content is None:
            # Try with sudo via cat command
            success, content, stderr = self.executor.run_command(f"cat {service_path}")
            if not success:
                success, content, stderr = self.executor.run_sudo_command(f"cat {service_path}", "")
        
        if content:
            self.txt_current_config.setText(content)
            self.parse_service_content(content)
            self.log(f"✅ Parsed service: {service_name}")
        else:
            self.txt_current_config.setText(f"Could not read service file: {service_path}")
            self.log(f"❌ Failed to parse service")

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
        """Open folder browser for encrypted dist folder - local or remote based on executor type."""
        if isinstance(self.executor, RemoteExecutor):
            # Use remote folder browser
            dialog = RemoteFolderBrowser(self.executor, self)
            if dialog.exec_() == QDialog.Accepted:
                folder = dialog.get_selected_path()
                if folder:
                    self.input_encrypted_folder.setText(folder)
        else:
            # Use local file dialog
            folder = QFileDialog.getExistingDirectory(self, "Select Encrypted Folder (dist/)")
            if folder:
                self.input_encrypted_folder.setText(folder)

    def _detect_project_folder(self, dist_folder):
        """Auto-detect the project folder inside dist/ (excludes pyarmor_runtime_*)."""
        items = self.executor.list_dir(dist_folder)
        for item in items:
            item_path = os.path.join(dist_folder, item)
            if self.executor.is_dir(item_path) and not item.startswith('pyarmor_runtime'):
                return item
        return None

    def _calculate_new_working_dir(self, dist_folder):
        """Calculate the new WorkingDirectory by preserving subdirectory structure."""
        project_folder = self._detect_project_folder(dist_folder)
        if not project_folder:
            return dist_folder
        
        base_path = os.path.join(dist_folder, project_folder)
        
        original_wd = self.current_service_config.get('WorkingDirectory', '')
        if not original_wd:
            return base_path
        
        original_parts = original_wd.replace('\\', '/').split('/')
        
        try:
            project_idx = None
            for i, part in enumerate(original_parts):
                if part == project_folder:
                    project_idx = i
                    break
            
            if project_idx is not None and project_idx < len(original_parts) - 1:
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

        python_path = dist_folder
        new_working_dir = self._calculate_new_working_dir(dist_folder)

        changes_text = "=" * 60 + "\n"
        changes_text += "  REQUIRED CHANGES FOR PYARMOR ENCRYPTION\n"
        changes_text += "=" * 60 + "\n\n"

        old_wd = self.current_service_config.get('WorkingDirectory', '<not set>')
        changes_text += f"📁 WorkingDirectory:\n"
        changes_text += f"   OLD: {old_wd}\n"
        changes_text += f"   NEW: {new_working_dir}\n\n"

        old_exec = self.current_service_config.get('ExecStart', '<not set>')
        changes_text += f"▶️ ExecStart:\n"
        changes_text += f"   ✅ PRESERVED (no change needed)\n"
        changes_text += f"   {old_exec}\n\n"

        old_pypath = '<not set>'
        for env in self.current_service_config.get('Environment', []):
            if 'PYTHONPATH' in env:
                old_pypath = env
                break
        new_pypath = f'PYTHONPATH={python_path}'
        changes_text += f"🐍 PYTHONPATH Environment:\n"
        changes_text += f"   OLD: {old_pypath}\n"
        changes_text += f"   NEW: {new_pypath}\n\n"

        old_user = self.current_service_config.get('User', '<not set>')
        changes_text += f"👤 User:\n"
        changes_text += f"   OLD: {old_user}\n"
        changes_text += f"   NEW: {user}\n"

        self.txt_changes.setText(changes_text)

    def generate_new_service_content(self):
        """Generate the new service file content by modifying the original."""
        dist_folder = self.input_encrypted_folder.text()
        user = self.input_user.text()

        new_working_dir = self._calculate_new_working_dir(dist_folder)
        python_path = dist_folder

        original_content = self.txt_current_config.toPlainText()
        if not original_content or original_content.startswith('Could not read') or original_content.startswith('Error'):
            return self._generate_fallback_service_content(new_working_dir, python_path, user)

        new_lines = []
        pythonpath_added = False
        in_service_section = False
        
        for line in original_content.split('\n'):
            stripped = line.strip()
            
            if stripped == '[Service]':
                in_service_section = True
                new_lines.append(line)
                continue
            elif stripped.startswith('[') and stripped.endswith(']'):
                if in_service_section and not pythonpath_added:
                    new_lines.append(f'Environment="PYTHONPATH={python_path}"')
                    pythonpath_added = True
                in_service_section = False
                new_lines.append(line)
                continue
            
            if stripped.startswith('WorkingDirectory='):
                new_lines.append(f'WorkingDirectory={new_working_dir}')
                continue
            
            if stripped.startswith('User=') and user:
                new_lines.append(f'User={user}')
                continue
            
            if stripped.startswith('Group=') and user:
                new_lines.append(f'Group={user}')
                continue
            
            if stripped.startswith('Environment=') and 'PYTHONPATH' in stripped:
                new_lines.append(f'Environment="PYTHONPATH={python_path}"')
                pythonpath_added = True
                continue
            
            new_lines.append(line)
        
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

        # Validate encrypted folder exists
        if not self.executor.file_exists(dist_folder):
            QMessageBox.warning(self, "Invalid Folder", "The encrypted folder does not exist on target system.")
            return

        new_config = self.generate_new_service_content()
        
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

        self.worker = ServiceConfigWorker(service_name, new_config, sudo_pass, self.executor)
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
        self.setGeometry(100, 100, 900, 850)
        
        # Default to local executor
        self.executor = LocalExecutor()
        self.ssh_connection = None
        self.is_remote = False
        
        self.init_ui()
        
        # Show connection dialog on startup
        self.show_connection_dialog()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)

        # Connection Status Bar
        self.connection_bar = QFrame()
        self.connection_bar.setFrameShape(QFrame.StyledPanel)
        self.connection_bar.setStyleSheet("background-color: #e8f5e9; border-radius: 5px; padding: 5px;")
        conn_layout = QHBoxLayout(self.connection_bar)
        conn_layout.setContentsMargins(10, 5, 10, 5)
        
        self.lbl_connection = QLabel("🖥️ Connected to: Local System")
        self.lbl_connection.setStyleSheet("font-weight: bold;")
        conn_layout.addWidget(self.lbl_connection)
        
        conn_layout.addStretch()
        
        btn_change_conn = QPushButton("🔄 Change Connection")
        btn_change_conn.clicked.connect(self.show_connection_dialog)
        conn_layout.addWidget(btn_change_conn)
        
        layout.addWidget(self.connection_bar)

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
        self.encryption_tab = EncryptionTab(self.executor)
        self.service_tab = ServiceConfigTab(self.executor)

        self.tabs.addTab(self.encryption_tab, "🔐 Encrypt Folder")
        self.tabs.addTab(self.service_tab, "⚙️ Configure Service")

        layout.addWidget(self.tabs)

    def show_connection_dialog(self):
        dialog = SSHConnectionDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            is_remote, host, port, username, password = dialog.get_connection_info()
            
            if is_remote:
                if not SSH_AVAILABLE:
                    QMessageBox.critical(self, "Error", "paramiko is not installed.\nRun: pip install paramiko")
                    return
                
                try:
                    # Create SSH connection
                    self.ssh_connection = SSHConnection()
                    self.ssh_connection.connect(host, username, password, port)
                    self.executor = RemoteExecutor(self.ssh_connection)
                    self.is_remote = True
                    
                    # Update UI
                    self.lbl_connection.setText(f"🌐 Connected to: {username}@{host}")
                    self.connection_bar.setStyleSheet("background-color: #e3f2fd; border-radius: 5px; padding: 5px;")
                    
                except Exception as e:
                    QMessageBox.critical(self, "Connection Failed", f"Could not connect:\n{str(e)}")
                    return
            else:
                # Switch to local
                if self.ssh_connection:
                    self.ssh_connection.disconnect()
                    self.ssh_connection = None
                
                self.executor = LocalExecutor()
                self.is_remote = False
                self.lbl_connection.setText("🖥️ Connected to: Local System")
                self.connection_bar.setStyleSheet("background-color: #e8f5e9; border-radius: 5px; padding: 5px;")
            
            # Update tabs with new executor
            self.encryption_tab.set_executor(self.executor)
            self.service_tab.set_executor(self.executor)

    def closeEvent(self, event):
        """Clean up SSH connection on close."""
        if self.ssh_connection:
            self.ssh_connection.disconnect()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    window = PyArmorDeployApp()
    window.show()
    sys.exit(app.exec_())