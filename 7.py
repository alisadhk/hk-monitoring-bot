import asyncio
import os
import re
import logging
import sys
import json
from datetime import datetime
from cryptography.fernet import Fernet, InvalidToken
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QTextEdit, QLabel, QMessageBox, 
    QGridLayout, QComboBox, QInputDialog
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QPixmap, QPalette, QBrush, QColor, QPainter
from telegram import Bot
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import base64
from io import BytesIO


# Constants
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
CONFIG_FILE = "alarm_config.json"
KEY_FILE = "encryption.key"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('alarm_monitor.log', encoding='utf-8')]
)

class ConfigManager:
    @staticmethod
    def _get_or_create_key():
        """Generate or retrieve encryption key"""
        if not os.path.exists(KEY_FILE):
            key = Fernet.generate_key()
            with open(KEY_FILE, "wb") as f:
                f.write(key)
        return open(KEY_FILE, "rb").read()

    @staticmethod
    def save_config(config_name, data):
        """Save configuration with specified name"""
        try:
            key = ConfigManager._get_or_create_key()
            fernet = Fernet(key)
            
            all_configs = ConfigManager._load_all_configs()
            encrypted_data = fernet.encrypt(json.dumps(data).encode()).decode()
            all_configs["accounts"][config_name] = encrypted_data
            all_configs["last_used"] = config_name
            
            with open(CONFIG_FILE, "w") as f:
                json.dump(all_configs, f)
            return True
        except Exception as e:
            logging.error(f"Error saving config: {str(e)}")
            return False

    @staticmethod
    def load_config(config_name=None):
        """Load specific configuration"""
        try:
            all_configs = ConfigManager._load_all_configs()
            config_name = config_name or all_configs.get("last_used")
            
            if not config_name or config_name not in all_configs["accounts"]:
                return None
                
            key = ConfigManager._get_or_create_key()
            fernet = Fernet(key)
            encrypted_data = all_configs["accounts"][config_name].encode()
            return json.loads(fernet.decrypt(encrypted_data).decode())
        except InvalidToken:
            logging.error("Invalid encryption token - possible key mismatch")
            return None
        except Exception as e:
            logging.error(f"Error loading config: {str(e)}")
            return None

    @staticmethod
    def _load_all_configs():
        """Load all configurations"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r") as f:
                    return json.load(f)
            return {"accounts": {}, "last_used": None}
        except (FileNotFoundError, json.JSONDecodeError):
            return {"accounts": {}, "last_used": None}

    @staticmethod
    def get_all_accounts():
        """Get list of all saved accounts"""
        return list(ConfigManager._load_all_configs()["accounts"].keys())

    @staticmethod
    def delete_config(config_name):
        """Delete specific configuration"""
        try:
            all_configs = ConfigManager._load_all_configs()
            if config_name in all_configs["accounts"]:
                del all_configs["accounts"][config_name]
                if all_configs["last_used"] == config_name:
                    all_configs["last_used"] = None
                with open(CONFIG_FILE, "w") as f:
                    json.dump(all_configs, f)
                return True
            return False
        except Exception as e:
            logging.error(f"Error deleting config: {str(e)}")
            return False

class LogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        msg = self.format(record)
        self.signal.emit(msg)

class MonitorThread(QThread):
    log_signal = pyqtSignal(str)
    update_signal = pyqtSignal(dict)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = False
        self.monitor = None

    def run(self):
        self.running = True
        asyncio.run(self._monitor())

    async def _monitor(self):
        self.monitor = AlarmMonitor(self.config, self.log_signal)
        if not self.monitor.login():
            return

        while self.running:
            try:
                alarms = self.monitor.fetch_recent_alarms()
                for alarm in alarms:
                    await self.monitor.process_alarm(alarm)
                await asyncio.sleep(self.config["POLL_INTERVAL"])
            except Exception as e:
                self.log_signal.emit(f"Error: {str(e)}")
                await asyncio.sleep(30)

    def stop(self):
        self.running = False
        if self.monitor:
            self.monitor.cleanup()

class AlarmMonitor:
    def __init__(self, config, log_signal):
        self.config = config
        self.log_signal = log_signal
        self.alarm_states = {}
        self.bot = Bot(token=config["TELEGRAM_BOT_TOKEN"])
        self.driver = self._init_webdriver()
        self.wait = WebDriverWait(self.driver, 15)
        self.log_signal.emit("Monitoring system initialized")
        self.log_signal.emit(f"Notifications will be sent to: {config['TELEGRAM_CHANNEL']}")

    def _init_webdriver(self):
        options = Options()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        return webdriver.Chrome(options=options)

    def login(self):
        try:
            self.driver.get(self.config["LOGIN_URL"])
            username = self.wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='text']")))
            password = self.wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='password']")))
            submit = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']")))

            username.send_keys(self.config["WEB_USERNAME"])
            password.send_keys(self.config["WEB_PASSWORD"])
            submit.click()
            self.wait.until(EC.url_changes(self.config["LOGIN_URL"]))
            self.log_signal.emit("Login successful")
            return True
        except Exception as e:
            self.log_signal.emit(f"Login failed: {str(e)}")
            return False

    def fetch_recent_alarms(self):
        try:
            self.driver.get(self.config["ALARMS_URL"])
            self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "tbody.ui-selectable.selectable-initialized")
            ))

            table_elem = self.driver.find_element(By.CSS_SELECTOR, "tbody.ui-selectable.selectable-initialized")
            return [row.text.strip() for row in table_elem.find_elements(By.TAG_NAME, "tr") if row.text.strip()]
            
        except Exception as e:
            self.log_signal.emit(f"Error fetching alarms: {str(e)}")
            return []

    async def process_alarm(self, alarm_text):
        try:
            alarm_key = self.extract_alarm_key(alarm_text)
            current_status = self.extract_alarm_status(alarm_text)
            
            if not alarm_key or not current_status:
                return

            previous_status = self.alarm_states.get(alarm_key)
            
            if previous_status != current_status:
                emoji = "🟢" if current_status == "Up" else "🔴"
                status_change = f"{previous_status} → {current_status}" if previous_status else f"New → {current_status}"
                
                message = (
                    f"{emoji} **Alarm Status Change** {emoji}\n"
                    f"**Status:** {status_change}\n"
                    "────────────────────\n"
                    f"```\n{alarm_text}\n```"
                )
                
                await self.send_telegram(message)
                self.alarm_states[alarm_key] = current_status

        except Exception as e:
            self.log_signal.emit(f"Error processing alarm: {str(e)}")

    async def send_telegram(self, message):
        try:
            chat_id = self.config["TELEGRAM_CHANNEL"]
            
            # If it is a personal user ID (digits only), convert it to an integer
            if chat_id.isdigit():
                chat_id = int(chat_id)
                
            await self.bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='Markdown'
            )
            self.log_signal.emit(f"Notification sent to: {chat_id} - {message[:100]}...")
        except Exception as e:
            self.log_signal.emit(f"Failed to send message: {str(e)}")

    def extract_alarm_key(self, alarm_text):
        try:
            clean_text = re.sub(r'\d+\s*[smhd]|(Up|Down)', '', alarm_text, flags=re.IGNORECASE)
            clean_text = re.sub(r'\d+\.?\d*', '', clean_text)
            return clean_text.strip()
        except Exception as e:
            self.log_signal.emit(f"Error creating alarm key: {str(e)}")
            return alarm_text

    def extract_alarm_status(self, alarm_text):
        status_match = re.search(r'\b(Up|Down)\b', alarm_text, re.IGNORECASE)
        return status_match.group(1).capitalize() if status_match else None

    def cleanup(self):
        self.driver.quit()
        self.log_signal.emit("Monitoring stopped")

class MainWindow(QMainWindow):
    log_signal = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.monitor_thread = None
        self.current_account = None
        self.fields = {}
        self.init_ui()
        self.load_accounts()
        self.log_signal.connect(self.update_log)
        self.setup_styles()
        self.setWindowIcon(QIcon('icon.ico'))  # set the window icon here
        self.set_log_background()  # moved after the init_ui definition

    def set_log_background(self):
        """Set a semi-transparent background image for the log"""
        if os.path.exists("444.png"):
            pixmap = QPixmap("444.png")
            
            # create a 30% transparent image
            transparent_pixmap = QPixmap(pixmap.size())
            transparent_pixmap.fill(Qt.transparent)
            
            painter = QPainter(transparent_pixmap)
            painter.setOpacity(0.3)
            painter.drawPixmap(0, 0, pixmap)
            painter.end()
            
            # apply the background to the QTextEdit
            palette = self.log_area.palette()
            palette.setBrush(QPalette.Base, QBrush(transparent_pixmap))
            self.log_area.setPalette(palette)

    def setup_styles(self):
        self.setStyleSheet("""
        QMainWindow {
            background-color: #0c1a24;
            font-family: Arial;
        }
        QPushButton {
            background-color: #8b1e2d;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 6px;
            min-width: 80px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #a82338;
        }
        QLineEdit, QComboBox {
            background-color: #13232f;
            color: #e3f6ff;
            border: 1px solid #3a4f63;
            padding: 5px;
            border-radius: 4px;
        }
        QTextEdit {
            background-color: rgba(16, 30, 41, 150);
            color: #a8e4ff;
            font-family: Consolas;
            font-size: 12px;
            border: 1px solid #3a4f63;
            border-radius: 4px;
        }
        QLabel {
            color: #e0e0e0;
            font-weight: 500;
        }
        """)

    def init_ui(self):
        self.setWindowTitle("HK Monitoring bot")
        self.setGeometry(100, 100, 1000, 650)

        # Account Controls
        self.account_selector = QComboBox()
        self.account_selector.setFixedHeight(28)
        self.btn_add_account = QPushButton("Add")
        self.btn_delete_account = QPushButton("Del")
        self.btn_add_account.setFixedWidth(60)
        self.btn_delete_account.setFixedWidth(60)

        # Create Input Fields
        self.create_fields()

        # Control Buttons
        self.btn_save = QPushButton("Save")
        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_clear = QPushButton("Clear Log")
        self.btn_help = QPushButton("Help ?")
        self.btn_about = QPushButton("</About>")

        # Setup Layouts
        self.setup_layouts()

        # Connect Signals
        self.connect_signals()

        # Initial State
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_delete_account.setEnabled(False)

    def create_fields(self):
        """Create all input fields"""
        self.fields = {
            "WEB_USERNAME": QLineEdit(),
            "WEB_PASSWORD": QLineEdit(echoMode=QLineEdit.Password),
            "LOGIN_URL": QLineEdit(),
            "ALARMS_URL": QLineEdit(),
            "TELEGRAM_BOT_TOKEN": QLineEdit(),
            "TELEGRAM_CHANNEL": QLineEdit(),
            "POLL_INTERVAL": QLineEdit(),
            "ALARM_TIME_THRESHOLD": QLineEdit(),
            "SIMILARITY_THRESHOLD": QLineEdit()
        }

    def setup_layouts(self):
        """Setup all UI layouts"""
        # Main Grid Layout for input fields
        grid = QGridLayout()
        grid.setSpacing(12)
        
        # Row 0: WEB USERNAME | WEB PASSWORD
        grid.addWidget(QLabel("WEB USERNAME"), 0, 0)
        grid.addWidget(self.fields["WEB_USERNAME"], 0, 1, 1, 2)
        grid.addWidget(QLabel("WEB PASSWORD"), 0, 3)
        grid.addWidget(self.fields["WEB_PASSWORD"], 0, 4, 1, 2)

        # Row 1: LOGIN URL | ALARMS URL
        grid.addWidget(QLabel("LOGIN URL"), 1, 0)
        grid.addWidget(self.fields["LOGIN_URL"], 1, 1, 1, 2)
        grid.addWidget(QLabel("ALARMS URL"), 1, 3)
        grid.addWidget(self.fields["ALARMS_URL"], 1, 4, 1, 2)

        # Row 2: TELEGRAM BOT TOKEN | TELEGRAM CHANNEL
        grid.addWidget(QLabel("TELEGRAM BOT TOKEN"), 2, 0)
        grid.addWidget(self.fields["TELEGRAM_BOT_TOKEN"], 2, 1, 1, 2)
        grid.addWidget(QLabel("TELEGRAM CHANNEL"), 2, 3)
        grid.addWidget(self.fields["TELEGRAM_CHANNEL"], 2, 4, 1, 2)

        # Row 3: POLL INTERVAL | ALARM TIME THRESHOLD | SIMILARITY THRESHOLD
        grid.addWidget(QLabel("POLL INTERVAL"), 3, 0)
        grid.addWidget(self.fields["POLL_INTERVAL"], 3, 1)
        grid.addWidget(QLabel("ALARM TIME THRESHOLD"), 3, 2)
        grid.addWidget(self.fields["ALARM_TIME_THRESHOLD"], 3, 3)
        grid.addWidget(QLabel("SIMILARITY THRESHOLD"), 3, 4)
        grid.addWidget(self.fields["SIMILARITY_THRESHOLD"], 3, 5)

        # Control Buttons Layout
        control_layout = QHBoxLayout()
        control_layout.addWidget(self.btn_save)
        control_layout.addWidget(self.btn_start)
        control_layout.addWidget(self.btn_stop)
        control_layout.addWidget(self.btn_clear)
        control_layout.addWidget(self.btn_help)
        control_layout.addWidget(self.btn_about)
        control_layout.setSpacing(8)

        # Account Layout
        account_layout = QGridLayout()
        account_layout.addWidget(QLabel("Account:"), 0, 1)
        account_layout.addWidget(self.account_selector, 0, 2)
        account_layout.addWidget(self.btn_add_account, 0, 3)
        account_layout.addWidget(self.btn_delete_account, 0, 4)

        # Log Area
        self.log_area = QTextEdit(readOnly=True)
        self.log_area.setFixedHeight(200)

        # Main Layout
        main_layout = QVBoxLayout()
        main_layout.addLayout(account_layout)
        main_layout.addLayout(grid)
        main_layout.addLayout(control_layout)
        main_layout.addWidget(self.log_area)

        main_widget = QWidget()
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)

    def connect_signals(self):
        """Connect all UI signals"""
        self.btn_save.clicked.connect(self.save_config)
        self.btn_start.clicked.connect(self.start_monitoring)
        self.btn_stop.clicked.connect(self.stop_monitoring)
        self.btn_clear.clicked.connect(self.clear_log)
        self.btn_help.clicked.connect(self.show_help)
        self.btn_about.clicked.connect(self.show_about)
        self.btn_add_account.clicked.connect(self.add_account)
        self.btn_delete_account.clicked.connect(self.delete_account)
        self.account_selector.currentTextChanged.connect(self.account_changed)

    def clear_log(self):
        """Clear the log display"""
        self.log_area.clear()

    def load_accounts(self):
        """Load all available accounts"""
        self.account_selector.clear()
        accounts = ConfigManager.get_all_accounts()
        self.account_selector.addItems(accounts)
        
        if accounts:
            last_used = ConfigManager._load_all_configs().get("last_used")
            if last_used in accounts:
                self.account_selector.setCurrentText(last_used)
            self.btn_delete_account.setEnabled(True)
            self.btn_start.setEnabled(True)
        else:
            self.btn_delete_account.setEnabled(False)
            self.btn_start.setEnabled(False)

    def account_changed(self, account_name):
        """Handle account selection change"""
        if account_name:
            config = ConfigManager.load_config(account_name)
            if config:
                for key, field in self.fields.items():
                    field.setText(str(config.get(key, "")))
                self.current_account = account_name
                self.btn_start.setEnabled(True)

    def add_account(self):
        """Add new account"""
        account_name, ok = QInputDialog.getText(
            self, "New Account", "Enter account name:",
            QLineEdit.Normal, ""
        )
        
        if ok and account_name:
            if account_name in ConfigManager.get_all_accounts():
                QMessageBox.warning(self, "Warning", "Account name already exists!")
                return
                
            if self.save_current_settings(account_name, show_message=False):
                self.load_accounts()
                self.account_selector.setCurrentText(account_name)
                QMessageBox.information(self, "Success", f"Account '{account_name}' created successfully")

    def delete_account(self):
        """Delete current account"""
        account_name = self.account_selector.currentText()
        if account_name:
            reply = QMessageBox.question(
                self, "Confirm Delete",
                f"Are you sure you want to delete account '{account_name}'?",
                QMessageBox.Yes | QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                if ConfigManager.delete_config(account_name):
                    self.load_accounts()
                    QMessageBox.information(self, "Success", "Account deleted successfully")
                else:
                    QMessageBox.warning(self, "Error", "Failed to delete account")

    def save_config(self):
        """Save settings for current account"""
        account_name = self.account_selector.currentText()
        if account_name:
            if self.save_current_settings(account_name):
                self.load_accounts()
        else:
            self.add_account()

    def save_current_settings(self, account_name, show_message=True):
        """Save current settings under specified account name"""
        config = {}
        try:
            for key, field in self.fields.items():
                value = field.text().strip()
                if not value:
                    QMessageBox.critical(self, "Error", f"Field '{key.replace('_', ' ')}' is required")
                    return False
                
                if key == "TELEGRAM_CHANNEL":
                    if not (value.startswith('@') or value.startswith('-100') or value.isdigit()):
                        QMessageBox.critical(self, "Error", 
                            "Telegram channel must be:\n"
                            "- Channel: start with @ or -100\n"
                            "- User ID: numbers only")
                        return False
                    
                if key in ["POLL_INTERVAL", "ALARM_TIME_THRESHOLD"]:
                    try:
                        config[key] = int(value)
                    except ValueError:
                        QMessageBox.critical(self, "Error", f"Invalid number for {key.replace('_', ' ')}")
                        return False
                elif key == "SIMILARITY_THRESHOLD":
                    try:
                        config[key] = float(value)
                        if not 0 <= config[key] <= 1:
                            raise ValueError
                    except ValueError:
                        QMessageBox.critical(self, "Error", "Similarity threshold must be between 0 and 1")
                        return False
                else:
                    config[key] = value

            if ConfigManager.save_config(account_name, config):
                if show_message:
                    QMessageBox.information(self, "Success", "Settings saved successfully")
                return True
            else:
                QMessageBox.critical(self, "Error", "Failed to save settings")
                return False
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An error occurred: {str(e)}")
            return False

    def start_monitoring(self):
        """Start alarm monitoring"""
        account_name = self.account_selector.currentText()
        if not account_name:
            QMessageBox.critical(self, "Error", "No account selected")
            return

        config = ConfigManager.load_config(account_name)
        if not config:
            QMessageBox.critical(self, "Error", "Failed to load account settings")
            return

        self.monitor_thread = MonitorThread(config)
        self.monitor_thread.log_signal.connect(self.log_signal.emit)
        self.monitor_thread.start()
        
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_save.setEnabled(False)
        self.set_fields_enabled(False)

    def stop_monitoring(self):
        """Stop alarm monitoring"""
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread = None
            
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_save.setEnabled(True)
        self.set_fields_enabled(True)

    def set_fields_enabled(self, enabled):
        """Enable/disable input fields"""
        for field in self.fields.values():
            field.setEnabled(enabled)

    def show_help(self):
        """Show help information"""
        help_text = """
        <div style="white-space: pre-line; color: white;">
        <div style="text-align: center;">
        <span style="color:#4da6ff; font-size:18px; font-weight:bold;">
        📡 HK Monitoring bot - Help
        </span>
        </div>
        This program monitors alarms from a local or remote PRTG instance and sends notifications to Telegram in real time.  
        It is compatible with <b>PRTG Network Monitor 2017 (cracked)</b>.  
        <b>Note:</b> The PRTG server itself does not need internet access — only the computer or server running this program must have internet and be able to access PRTG via LAN or IP.


        <span style="color:#ff4c4c;"><u>Account Management:</u></span>
        1. Use <b>Add</b> to create new monitoring profiles  
        2. Select account from dropdown to load settings  
        3. Modify settings and click <b>Save</b>  
        4. Use <b>Del</b> to remove unwanted profiles

        <span style="color:#ff4c4c;"><u>Monitoring:</u></span>
        1. Select account and click <b>Start</b>  
        2. System will monitor alarms and send notifications  
        3. Click <b>Stop</b> to pause monitoring  
        4. Use <b>Clear Log</b> to clear the event log display

        <span style="color:#ff4c4c;"><u>Telegram Channel/User:</u></span>  
        1. For public channels: @channel_name  
        2. For private channels: -100123456789  
        3. For personal users: 123456789 (user ID)  
        4. Bot must have permission to send messages  
        5. You must <b>create a Telegram bot</b> using @BotFather and use the <b>bot token</b> in the settings

        <span style="color:#ff4c4c;"><u>Log:</u></span>   
        1. All system messages and notifications appear here  
        2. Errors, status updates, and sent alerts are logged

        <span style="color:#ff4c4c;"><u>Tips for Best Usage:</u></span>
        • POLL INTERVAL = 15  
        • ALARM TIME THRESHOLD = 5  
        • SIMILARITY THRESHOLD = 0.8
        </div>
        """
        msg = QMessageBox(self)
        msg.setWindowTitle("Help")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(help_text)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #1e1e1e;
                color: white;
                font-family: Arial;
            }
            QLabel {
                color: white;
            }
            QPushButton {
                background-color: #8b1e2d;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #a82338;
            }
        """)
        msg.exec_()

    def show_about(self):
        """Show about information"""
        about_text ="""
        <div style="white-space: pre-line; color: white;">
        <b>HK Monitoring bot</b>

        Copyright © 2025 HK Monitoring bot  
        Version: 1.3
        Programmed by Network *****  
        To contact me:  <a href='*****'>Linkedin</a>
        </div>
        """

        msg = QMessageBox(self)
        msg.setWindowTitle("About")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(about_text)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #1e1e1e;
                color: white;
                font-family: Arial;
            }
            QLabel {
                color: white;
            }
            QPushButton {
                background-color: #8b1e2d;
                color: white;
                padding: 6px 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #a82338;
            }
        """)
        msg.exec_()

    def update_log(self, message):
        """Update log display with new message"""
        self.log_area.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    def closeEvent(self, event):
        """Handle window close event"""
        self.stop_monitoring()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())