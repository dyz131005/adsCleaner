# Copyright (c) 2025 dyz131005
# Licensed under the MIT License

import sys
import os
import ctypes
import winreg
import psutil
import shutil
import send2trash
import traceback
import win32com.client
import win32api
import win32con
import win32file
import win32security
import winioctlcon
import pywintypes
import subprocess
import threading
import time
import uuid
import zipfile
import tempfile
import queue
import configparser
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QGroupBox, QCheckBox, QProgressBar, QFileDialog,
    QListWidget, QStackedWidget, QMessageBox, QAction, QSystemTrayIcon, QMenu,
    QDialog, QTextEdit, QScrollArea, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit,
    QInputDialog, QFormLayout
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QPoint
from PyQt5.QtGui import QIcon, QTextCursor, QFont, QColor, QMouseEvent, QTextOption

# 强制绕过GIL锁的优化 - 在导入PyQt5之前执行
# Python 3.12 兼容性修复
if hasattr(sys, 'setcheckinterval'):
    sys.setcheckinterval(1000000)  # 减少GIL切换频率
sys.setswitchinterval(0.005)   # 设置更短的线程切换间隔

# 设置插件路径 - 必须放在所有导入之前
if hasattr(sys, '_MEIPASS'):
    # 打包环境
    os.environ['QT_PLUGIN_PATH'] = os.path.join(sys._MEIPASS, 'PyQt5', 'Qt5', 'plugins')
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = os.environ['QT_PLUGIN_PATH']
else:
    # 开发环境 - 自动查找PyQt5插件路径
    pyqt_path = os.path.dirname(sys.executable) if hasattr(sys, 'frozen') else sys.prefix
    plugins_path = os.path.join(pyqt_path, 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins')
    
    # 备选路径
    candidate_paths = [
        plugins_path,
        os.path.join(sys.prefix, 'Lib', 'site-packages', 'PyQt5', 'Qt5', 'plugins'),
        os.path.join(sys.prefix, 'Lib', 'site-packages', 'PyQt5', 'Qt', 'plugins')
    ]
    
    # 查找有效路径
    found = False
    for path in candidate_paths:
        if os.path.exists(path):
            os.environ['QT_PLUGIN_PATH'] = path
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = path
            print(f"设置插件路径: {path}")
            found = True
            break
    
    if not found:
        print("警告: 未找到PyQt5插件路径，程序可能无法正常运行")

# 判断是否打包环境
def is_frozen():
    return hasattr(sys, '_MEIPASS')

# 修复ctypes.wintypes问题 - 使用原生ctypes类型
HANDLE = ctypes.c_void_p
DWORD = ctypes.c_ulong
BOOL = ctypes.c_int

# 定义Windows API函数
SetFileInformationByHandle = ctypes.windll.kernel32.SetFileInformationByHandle
SetFileInformationByHandle.argtypes = [HANDLE, DWORD, ctypes.c_void_p, DWORD]
SetFileInformationByHandle.restype = BOOL

# 定义文件信息常量
FileDispositionInfo = 4  # FILE_DISPOSITION_INFO的常量值

# 工具配置（本地查找）
TOOLS_CONFIG = {
    "handle": {
        "exe": "handle64.exe" if sys.maxsize > 2**32 else "handle.exe",
        "zip": "Handle.zip"
    },
    "psexec": {
        "exe": "PsExec64.exe" if sys.maxsize > 2**32 else "PsExec.exe",
        "zip": "PSTools.zip"
    }
}

class CleanerWorker(QThread):
    """清理工作线程，负责在后台执行清理任务"""
    progress = pyqtSignal(int)
    message = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    warning = pyqtSignal(str)
    detailed_log = pyqtSignal(str)  # 新增详细日志信号
    task_completed = pyqtSignal()  # 新增任务完成信号
    heartbeat = pyqtSignal()  # 心跳信号

    def __init__(self, tasks, force_mode=False):
        super().__init__()
        self.tasks = tasks
        self.is_canceled = False
        self.force_mode = force_mode  # 是否启用强制模式
        self.log_buffer = []  # 日志缓冲区
        self.tools_installed = False  # 工具是否已安装
        self.current_task_index = 0  # 当前任务索引
        self.last_activity_time = time.time()  # 最后活动时间
        self.task_queue = queue.Queue()  # 任务队列
        self.batch_size = 50  # 每批处理文件数量
        
        # 填充任务队列
        for task in tasks:
            self.task_queue.put(task)

    def log(self, message):
        """记录日志并发送信号"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.log_buffer.append(log_entry)
        self.detailed_log.emit(log_entry)
        self.last_activity_time = time.time()  # 更新最后活动时间

    def run(self):
        """执行清理任务 - 确保UI响应性"""
        try:
            # 确保工具已安装
            if not self.install_required_tools():
                self.error.emit("无法找到必要工具，强力模式功能受限")
            
            total = self.task_queue.qsize()
            processed = 0
            
            # 心跳定时器 - 增加频率
            heartbeat_timer = QTimer()
            heartbeat_timer.setInterval(500)  # 增加到500毫秒
            heartbeat_timer.timeout.connect(self.check_heartbeat)
            heartbeat_timer.start()
            
            # 顺序执行任务
            while not self.task_queue.empty() and not self.is_canceled:
                func, args = self.task_queue.get()
                
                # 执行任务
                try:
                    func(*args)
                except Exception as e:
                    self.log(f"任务执行失败: {e}")
                
                # 更新进度
                processed += 1
                progress_value = int(processed / total * 100)
                self.progress.emit(progress_value)
                self.message.emit(f"清理中: {args[0] if args else func.__name__} ({progress_value}%)")
                
                # 增加UI响应性 - 更频繁地处理事件
                self.heartbeat.emit()
                time.sleep(0.005)  # 减少延迟
                
                # 检查是否被取消
                if self.is_canceled:
                    break
            
            if self.is_canceled:
                self.log("清理任务已被用户取消")
                self.message.emit("清理已取消!")
            else:
                self.message.emit("清理完成!")
                self.log("所有清理任务已完成")
        except Exception as e:
            self.log(f"清理过程中发生异常: {str(e)}")
            self.error.emit(str(e))
        finally:
            heartbeat_timer.stop()
            self.finished.emit()

    def check_heartbeat(self):
        """检查心跳，防止假死"""
        current_time = time.time()
        if current_time - self.last_activity_time > 10:  # 10秒无活动
            self.log("检测到可能假死，发送心跳信号")
            self.heartbeat.emit()
            self.last_activity_time = current_time

    def execute_task(self, func, args):
        """执行单个任务并发送完成信号"""
        try:
            func(*args)
        except Exception as e:
            self.log(f"任务执行失败: {e}")
        finally:
            self.task_completed.emit()  # 发送任务完成信号

    def cancel(self):
        """取消清理任务"""
        self.is_canceled = True
        self.log("用户请求取消清理任务")

    def get_logs(self):
        """获取完整日志"""
        return "\n".join(self.log_buffer)

    def install_required_tools(self):
        """安装必要的工具（handle.exe, psexec.exe）"""
        if not self.force_mode:
            return True  # 不需要工具
            
        try:
            self.log("检查必要工具是否已安装...")
            base_dir = os.path.dirname(os.path.abspath(__file__))
            tools_dir = os.path.join(os.environ['TEMP'], "adsCleanerTools")
            os.makedirs(tools_dir, exist_ok=True)
            
            all_tools_available = True
            
            for tool_name, config in TOOLS_CONFIG.items():
                tool_path = os.path.join(tools_dir, config['exe'])
                
                # 检查工具是否存在
                if os.path.exists(tool_path):
                    self.log(f"工具 {config['exe']} 已存在")
                    continue
                
                # 检查根目录是否有压缩包
                zip_path = self.find_tool_zip(config['zip'])
                
                if zip_path:
                    self.log(f"找到本地压缩包: {zip_path}")
                    # 解压文件
                    try:
                        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                            zip_ref.extractall(tools_dir)
                        self.log(f"解压成功: {zip_path}")
                    except Exception as e:
                        self.log(f"解压失败: {str(e)}")
                        all_tools_available = False
                        continue
                    
                    # 检查提取的文件
                    if not os.path.exists(tool_path):
                        self.log(f"工具 {config['exe']} 未在压缩包中找到")
                        all_tools_available = False
                    else:
                        self.log(f"工具 {config['exe']} 安装成功")
                else:
                    self.log(f"未找到工具 {tool_name} 的压缩包")
                    self.warning.emit(
                        "文件可能被篡改或是测试版，请下载完整版\n"
                        f"下载地址: <a href='https://github.com/dyz131005/adsCleaner/releases'>"
                        "https://github.com/dyz131005/adsCleaner/releases</a>"
                    )
                    all_tools_available = False
            
            self.tools_installed = all_tools_available
            return all_tools_available
        except Exception as e:
            self.log(f"安装工具时出错: {str(e)}")
            return False

    def find_tool_zip(self, zip_name):
        """在本地查找工具压缩包"""
        # 检查程序同目录
        base_dir = os.path.dirname(os.path.abspath(__file__))
        local_path = os.path.join(base_dir, zip_name)
        if os.path.exists(local_path):
            return local_path
        
        # 检查打包后的根目录
        if is_frozen():
            meipass_path = os.path.join(sys._MEIPASS, zip_name)
            if os.path.exists(meipass_path):
                return meipass_path
        
        # 检查工具目录
        tools_dir = os.path.join(os.environ['TEMP'], "adsCleanerTools")
        tools_path = os.path.join(tools_dir, zip_name)
        if os.path.exists(tools_path):
            return tools_path
        
        # 检查其他可能的名称
        alt_names = [
            zip_name.lower(),
            zip_name.upper(),
            zip_name.capitalize()
        ]
        
        for name in alt_names:
            # 检查程序同目录
            alt_path = os.path.join(base_dir, name)
            if os.path.exists(alt_path):
                return alt_path
            
            # 检查打包后的根目录
            if is_frozen():
                alt_meipass = os.path.join(sys._MEIPASS, name)
                if os.path.exists(alt_meipass):
                    return alt_meipass
            
            # 检查工具目录
            alt_tools = os.path.join(tools_dir, name)
            if os.path.exists(alt_tools):
                return alt_tools
        
        return None

class ErrorLogDialog(QDialog):
    """错误日志对话框"""
    def __init__(self, logs, parent=None):
        super().__init__(parent)
        self.setWindowTitle("清理日志")
        self.setGeometry(300, 300, 800, 600)
        
        if parent:
            self.setWindowIcon(parent.windowIcon())
        
        layout = QVBoxLayout()
        
        # 创建文本编辑框
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(False)
        self.text_edit.setFont(QFont("Consolas", 9))
        self.text_edit.setPlainText(logs)
        self.text_edit.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.text_edit.setLineWrapMode(QTextEdit.NoWrap)  # 不自动换行
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # 需要时显示水平滚动条
        
        # 添加闪烁光标
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text_edit.setTextCursor(cursor)
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.text_edit)
        
        layout.addWidget(scroll_area)
        
        # 添加按钮
        btn_layout = QHBoxLayout()
        self.copy_btn = QPushButton("复制日志")
        self.copy_btn.clicked.connect(self.copy_logs)
        self.save_btn = QPushButton("保存到文件")
        self.save_btn.clicked.connect(self.save_logs)
        self.close_btn = QPushButton("关闭")
        self.close_btn.clicked.connect(self.close)
        
        btn_layout.addWidget(self.copy_btn)
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.close_btn)
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def append_log(self, log_entry):
        """追加日志条目"""
        self.text_edit.append(log_entry)
        # 滚动到底部
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text_edit.setTextCursor(cursor)
    
    def copy_logs(self):
        """复制日志到剪贴板"""
        clipboard = QApplication.clipboard()
        clipboard.setText(self.text_edit.toPlainText())
        QMessageBox.information(self, "成功", "日志已复制到剪贴板")
    
    def save_logs(self):
        """保存日志到文件"""
        file_path, _ = QFileDialog.getSaveFileName(self, "保存日志", "清理日志.txt", "文本文件 (*.txt)")
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(self.text_edit.toPlainText())
                QMessageBox.information(self, "成功", f"日志已保存到: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"保存日志失败: {str(e)}")

class UpdateLogDialog(QDialog):
    """更新日志对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("更新日志")
        self.setGeometry(200, 200, 600, 400)
        
        # 设置图标
        if parent:
            self.setWindowIcon(parent.windowIcon())
        
        # 创建主布局
        layout = QVBoxLayout()
        
        # 创建文本编辑框
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFont(QFont("微软雅黑", 10))
        self.text_edit.setLineWrapMode(QTextEdit.NoWrap)  # 不自动换行
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # 需要时显示水平滚动条
        
        # 创建滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.text_edit)
        
        layout.addWidget(scroll_area)
        
        # 添加关闭按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        btn_layout.addStretch()
        
        layout.addLayout(btn_layout)
        self.setLayout(layout)
        
        # 加载更新日志
        self.load_update_log()

    def load_update_log(self):
        """加载更新日志内容"""
        # 确定日志文件路径
        if is_frozen():
            # 打包环境
            base_path = sys._MEIPASS
        else:
            # 开发环境
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        log_path = os.path.join(base_path, "newlog.txt")
        
        # 检查文件是否存在
        if not os.path.exists(log_path):
            self.text_edit.setText("更新日志文件未找到。")
            return
        
        try:
            # 读取日志内容
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 解析日志内容
            if "&dyz&" in content:
                # 分割日志条目
                entries = content.split("&dyz&")
                # 过滤空条目
                entries = [entry.strip() for entry in entries if entry.strip()]
                
                # 格式化日志 - 改进排版
                formatted_log = ""
                for i, entry in enumerate(entries):
                    # 标题单独一行
                    formatted_log += f"<h3>更新 #{i+1}</h3>\n"
                    
                    # 处理日志内容
                    lines = entry.split('\n')
                    for line in lines:
                        if line.strip():  # 非空行
                            formatted_log += f"{line.strip()}<br/>\n"
                    
                    # 日志之间添加更多间距
                    formatted_log += "<br/><br/>\n"
                    formatted_log += "<hr/>\n"
                    formatted_log += "<br/><br/>\n"
                
                self.text_edit.setHtml(formatted_log)
            else:
                self.text_edit.setText(content)
        except Exception as e:
            self.text_edit.setText(f"加载更新日志失败: {str(e)}")

class RestorePointDialog(QDialog):
    """创建系统还原点对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("创建系统还原点")
        self.setGeometry(300, 300, 400, 300)
        
        if parent:
            self.setWindowIcon(parent.windowIcon())
        
        layout = QFormLayout()
        
        # 还原点描述
        self.desc_edit = QLineEdit()
        self.desc_edit.setPlaceholderText("请输入还原点描述")
        layout.addRow("还原点描述:", self.desc_edit)
        
        # 还原点类型
        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "应用程序安装", 
            "应用程序卸载", 
            "系统更新", 
            "手动创建", 
            "其他"
        ])
        layout.addRow("还原点类型:", self.type_combo)
        
        # 按钮
        btn_layout = QHBoxLayout()
        self.confirm_btn = QPushButton("确认")
        self.confirm_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.confirm_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addRow(btn_layout)
        
        self.setLayout(layout)
    
    def get_data(self):
        """获取用户输入的数据"""
        return self.desc_edit.text(), self.type_combo.currentText()

class ForceModePasswordDialog(QDialog):
    """强力模式密码输入对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚠️ 强力模式激活")
        self.setGeometry(300, 300, 500, 500)
        
        if parent:
            self.setWindowIcon(parent.windowIcon())
        
        layout = QVBoxLayout()
        
        # 警告标签
        warning_label = QLabel(
            "<h3>强力模式激活 (实验箱)</h3>"
            "<p>此模式使用底层技术强制操作文件系统，可能带来风险。</p>"
            "<p style='color:red;'><b>警告: 此操作可能导致系统不稳定或数据损坏！</b></p>"
        )
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)
        
        # 免责声明框
        disclaimer_label = QLabel("免责声明:")
        layout.addWidget(disclaimer_label)
        
        self.disclaimer_text = QTextEdit()
        self.disclaimer_text.setPlainText(
            "1. 使用强力模式可能导致不可预知的系统错误，包括但不限于系统崩溃、数据丢失、程序无法运行等。\n"
            "2. 开发者及软件作者不对因使用强力模式造成的任何损失承担责任。\n"
            "3. 用户需自行承担使用强力模式的一切风险。\n"
            "4. 在激活强力模式前，请确保已备份重要数据并创建系统还原点。\n\n"
            "请仔细阅读以上免责声明。激活强力模式即表示您已充分了解并同意承担所有风险。"
        )
        self.disclaimer_text.setReadOnly(True)
        self.disclaimer_text.setMinimumHeight(150)
        layout.addWidget(self.disclaimer_text)
        
        # 阅读计时器
        self.timer_label = QLabel("请阅读免责声明（剩余 7 秒）")
        self.timer_label.setStyleSheet("color: blue;")
        layout.addWidget(self.timer_label)
        
        # 密码输入
        password_layout = QHBoxLayout()
        self.password_edit = QLineEdit()
        self.password_edit.setPlaceholderText("输入密码以激活强力模式")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setContextMenuPolicy(Qt.NoContextMenu)  # 禁用右键菜单
        
        # 小眼睛按钮
        self.toggle_eye_btn = QPushButton()
        self.toggle_eye_btn.setIcon(QIcon(":/icons/eye_open.png"))  # 需要提供图标资源，这里用文本代替
        self.toggle_eye_btn.setText("显示")
        self.toggle_eye_btn.setCheckable(True)
        self.toggle_eye_btn.toggled.connect(self.toggle_password_visibility)
        
        password_layout.addWidget(QLabel("密码:"))
        password_layout.addWidget(self.password_edit)
        password_layout.addWidget(self.toggle_eye_btn)
        
        layout.addLayout(password_layout)
        
        # 添加长按提示
        long_press_label = QLabel("提示: 长按密码框可显示密码")
        long_press_label.setStyleSheet("color: #666666; font-size: 10px; font-style: italic;")
        layout.addWidget(long_press_label)
        
        # 按钮
        btn_layout = QHBoxLayout()
        self.activate_btn = QPushButton("激活强力模式")
        self.activate_btn.setStyleSheet("background-color: #FF5722; color: white; font-weight: bold;")
        self.activate_btn.clicked.connect(self.activate_force_mode)
        self.activate_btn.setEnabled(False)  # 初始不可用
        
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.activate_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        # 状态标签
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: red;")
        layout.addWidget(self.status_label)
        
        self.setLayout(layout)
        
        # 初始化计时器
        self.seconds_remaining = 7
        self.timer = QTimer(self)
        self.timer.setInterval(1000)  # 1秒
        self.timer.timeout.connect(self.update_timer)
        self.timer.start()
        
        # 设置密码框的长按事件
        self.password_edit.setMouseTracking(True)
        self.password_edit.mousePressEvent = self.on_password_mouse_press
        self.password_edit.mouseReleaseEvent = self.on_password_mouse_release
        self.mouse_press_time = 0
        self.mouse_pressed = False
    
    def on_password_mouse_press(self, event: QMouseEvent):
        """鼠标按下事件"""
        if event.button() == Qt.LeftButton:
            self.mouse_press_time = time.time()
            self.mouse_pressed = True
    
    def on_password_mouse_release(self, event: QMouseEvent):
        """鼠标释放事件"""
        if event.button() == Qt.LeftButton and self.mouse_pressed:
            press_duration = time.time() - self.mouse_press_time
            if press_duration > 1.0:  # 长按超过1秒
                # 临时显示密码
                original_echo = self.password_edit.echoMode()
                self.password_edit.setEchoMode(QLineEdit.Normal)
                QTimer.singleShot(2000, lambda: self.password_edit.setEchoMode(original_echo))
            self.mouse_pressed = False
    
    def toggle_password_visibility(self, checked):
        """切换密码可见性"""
        if checked:
            self.password_edit.setEchoMode(QLineEdit.Normal)
            self.toggle_eye_btn.setText("隐藏")
        else:
            self.password_edit.setEchoMode(QLineEdit.Password)
            self.toggle_eye_btn.setText("显示")
    
    def update_timer(self):
        """更新计时器"""
        self.seconds_remaining -= 1
        if self.seconds_remaining > 0:
            self.timer_label.setText(f"请阅读免责声明（剩余 {self.seconds_remaining} 秒）")
        else:
            self.timer.stop()
            self.timer_label.setText("已阅读免责声明，可以激活")
            self.activate_btn.setEnabled(True)
    
    def activate_force_mode(self):
        """验证密码并激活强力模式"""
        password = self.password_edit.text().strip()
        developer_password = "某wei请开放bl锁"  # 修改后的密码
        
        if password == developer_password:
            self.accept()
        else:
            self.status_label.setText("密码错误！访问被拒绝。")

class NoContextMenuLabel(QLabel):
    """自定义标签类，禁用右键菜单但保留超链接功能"""
    def contextMenuEvent(self, event):
        # 禁用右键菜单
        pass

class DiskCleanerApp(QMainWindow):
    """磁盘清理应用主窗口"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("adsC盘清理大师")
        self.setGeometry(100, 100, 800, 600)
        
        # 图标设置 - 直接加载ICO文件
        base_path = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_path, "pkk.ico")
        
        # 在打包环境中尝试从MEIPASS加载图标
        if not os.path.exists(icon_path) and is_frozen():
            icon_path = os.path.join(sys._MEIPASS, "pkk.ico")
        
        if os.path.exists(icon_path):
            try:
                self.setWindowIcon(QIcon(icon_path))
            except Exception as e:
                print(f"设置窗口图标失败: {e}")
                # 尝试使用默认图标
                try:
                    self.setWindowIcon(QIcon())
                except:
                    pass
        else:
            print(f"警告: 图标文件未找到: {icon_path}")
            # 尝试使用默认图标
            try:
                self.setWindowIcon(QIcon())
            except:
                pass
        
        # 开发者模式标志
        self.developer_force_mode = False
        self.force_mode_activated = False
        self.log_dialog = None  # 日志对话框
        
        # 加载配置
        self.load_config()
        
        self.init_ui()
        self.worker = None
        self.failed_files = []  # 记录清理失败的文件

    def load_config(self):
        """加载配置设置"""
        self.config = configparser.ConfigParser()
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
        
        if os.path.exists(config_path):
            self.config.read(config_path, encoding="utf-8")
            if 'Settings' in self.config:
                self.force_mode_activated = self.config.getboolean('Settings', 'ForceMode', fallback=False)
                self.developer_force_mode = self.config.getboolean('Settings', 'DeveloperMode', fallback=False)
        else:
            # 默认配置
            self.config['Settings'] = {
                'ForceMode': 'False',
                'DeveloperMode': 'False'
            }

    def save_config(self):
        """保存配置设置"""
        self.config['Settings'] = {
            'ForceMode': str(self.force_mode_activated),
            'DeveloperMode': str(self.developer_force_mode)
        }
        
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")
        with open(config_path, 'w', encoding="utf-8") as configfile:
            self.config.write(configfile)

    def init_ui(self):
        """初始化用户界面"""
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # 模式选择
        mode_layout = QHBoxLayout()
        mode_label = QLabel("用户模式:")
        self.mode_combo = QComboBox()
        # 添加深度清理模式
        self.mode_combo.addItems(["普通用户", "技术人员", "深度清理"])
        self.mode_combo.currentIndexChanged.connect(self.switch_mode)
        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        
        # 功能堆叠
        self.stacked_widget = QStackedWidget()
        
        # 普通用户界面
        self.normal_widget = self.create_normal_ui()
        
        # 技术人员界面
        self.advanced_widget = self.create_advanced_ui()
        
        # 深度清理界面
        self.deep_clean_widget = self.create_deep_clean_ui()
        
        self.stacked_widget.addWidget(self.normal_widget)
        self.stacked_widget.addWidget(self.advanced_widget)
        self.stacked_widget.addWidget(self.deep_clean_widget)
        
        # 公共组件
        self.progress_bar = QProgressBar()
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("font-weight: bold;")
        
        # 添加到主布局
        main_layout.addLayout(mode_layout)
        main_layout.addWidget(self.stacked_widget)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.status_label)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        self.clean_btn = QPushButton("开始清理")
        self.clean_btn.clicked.connect(self.start_clean)
        self.cancel_btn = QPushButton("取消清理")
        self.cancel_btn.clicked.connect(self.cancel_clean)
        self.cancel_btn.setEnabled(False)
        self.uninstall_btn = QPushButton("打开卸载程序")
        self.uninstall_btn.clicked.connect(self.open_uninstaller)
        # 添加创建系统还原点按钮
        self.restore_point_btn = QPushButton("创建系统还原点")
        self.restore_point_btn.clicked.connect(self.create_system_restore_point)
        btn_layout.addWidget(self.clean_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.uninstall_btn)
        btn_layout.addWidget(self.restore_point_btn)
        
        main_layout.addLayout(btn_layout)
        
        # 添加GitHub链接 (使用自定义标签禁用右键菜单)
        github_label = NoContextMenuLabel(
            f"<a href='https://github.com/dyz131005/adsCleaner/releases'>"
            "https://github.com/dyz131005/adsCleaner/releases</a>"
        )
        github_label.setOpenExternalLinks(True)
        github_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(github_label)
        
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        # 添加菜单
        self.create_menu()
        
        # 如果之前激活了强力模式，更新UI
        if self.force_mode_activated:
            self.deep_dev_mode_label.setText("强力模式: <span style='color: green; font-weight: bold;'>已激活</span>")
            self.force_mode_check.setEnabled(True)
            if self.mode_combo.currentIndex() == 2:  # 深度清理模式
                self.force_mode_check.setChecked(True)
        else:
            # 新增：确保强力模式未激活时，复选框禁用
            self.force_mode_check.setEnabled(False)
            self.force_mode_check.setChecked(False)

    def create_normal_ui(self):
        """创建普通用户界面"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        group = QGroupBox("清理选项 (普通模式)")
        grid = QVBoxLayout()
        
        self.normal_checks = [
            ("临时文件", True),
            ("缩略图缓存", True),
            ("回收站", False),
            ("下载文件夹", False),
            ("浏览器缓存", True),
            ("Windows日志文件", False)
        ]
        
        self.normal_checkboxes = []
        for text, checked in self.normal_checks:
            cb = QCheckBox(text)
            cb.setChecked(checked)
            grid.addWidget(cb)
            self.normal_checkboxes.append(cb)
        
        group.setLayout(grid)
        layout.addWidget(group)
        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def create_advanced_ui(self):
        """创建技术人员界面"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 清理选项
        group = QGroupBox("高级清理选项")
        grid = QVBoxLayout()
        
        self.advanced_checks = [
            ("系统临时文件", True),
            ("Windows更新缓存", True),
            ("事件日志文件", False),
            ("错误报告", True),
            ("DirectX着色器缓存", False),
            ("Delivery优化文件", True),
            ("Windows Defender缓存", True),
            ("Microsoft Office缓存", False)
        ]
        
        self.advanced_checkboxes = []
        for text, checked in self.advanced_checks:
            cb = QCheckBox(text)
            cb.setChecked(checked)
            grid.addWidget(cb)
            self.advanced_checkboxes.append(cb)
        
        group.setLayout(grid)
        layout.addWidget(group)
        
        # 自定义路径
        custom_group = QGroupBox("自定义清理路径")
        custom_layout = QVBoxLayout()
        
        self.path_list = QListWidget()
        self.path_list.setStyleSheet("QListWidget { background-color: #f0f0f0; }")
        
        # 添加强力模式输入框
        self.force_path_edit = QLineEdit()
        self.force_path_edit.setPlaceholderText("输入路径或特殊代码激活强力模式")
        self.force_path_edit.textChanged.connect(self.check_force_mode_activation)
        self.force_path_edit.setContextMenuPolicy(Qt.NoContextMenu)  # 禁用右键菜单
        
        add_btn = QPushButton("添加路径")
        add_btn.clicked.connect(self.add_custom_path)
        remove_btn = QPushButton("移除选中")
        remove_btn.clicked.connect(self.remove_custom_path)
        
        # 开发者模式提示
        self.dev_mode_label = QLabel("开发者模式: 未激活")
        if self.developer_force_mode:
            self.dev_mode_label.setText("开发者模式: <span style='color: green; font-weight: bold;'>已激活</span>")
        else:
            self.dev_mode_label.setText("开发者模式: 未激活")
        self.dev_mode_label.setStyleSheet("color: gray; font-style: italic;")
        
        custom_layout.addWidget(QLabel("自定义路径列表:"))
        custom_layout.addWidget(self.path_list)
        custom_layout.addWidget(QLabel("强力模式激活:"))
        custom_layout.addWidget(self.force_path_edit)
        custom_layout.addWidget(self.dev_mode_label)
        custom_layout.addWidget(add_btn)
        custom_layout.addWidget(remove_btn)
        custom_group.setLayout(custom_layout)
        layout.addWidget(custom_group)
        
        # 添加示例路径
        self.path_list.addItems([
            os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Temp'),
            os.path.join(os.environ.get('LOCALAPPDATA', 'C:\\Users\\User\\AppData\\Local'), 'Temp')
        ])
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def create_deep_clean_ui(self):
        """创建深度清理界面"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 添加警告标签
        warning_label = QLabel(
            "⚠️ 警告: 深度清理模式会清理系统关键缓存文件，可能导致某些程序需要重新初始化。\n"
            "强烈建议在清理前创建系统还原点!"
        )
        warning_label.setStyleSheet("color: red; font-weight: bold;")
        layout.addWidget(warning_label)
        
        # 清理选项
        group = QGroupBox("深度清理选项")
        grid = QVBoxLayout()
        
        self.deep_clean_checks = [
            ("旧的Windows更新文件", False),
            ("系统内存转储文件", False),
            ("预读取文件", False),
            ("字体缓存", False),
            ("Windows Installer缓存", False),
            ("系统日志存档", False),
            ("Windows错误报告存档", False),
            ("DirectX着色器缓存（深度）", False)
        ]
        
        self.deep_clean_checkboxes = []
        for text, checked in self.deep_clean_checks:
            cb = QCheckBox(text)
            cb.setChecked(checked)
            grid.addWidget(cb)
            self.deep_clean_checkboxes.append(cb)
        
        group.setLayout(grid)
        layout.addWidget(group)
        
        # 添加创建还原点按钮
        restore_btn = QPushButton("立即创建系统还原点")
        restore_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        restore_btn.clicked.connect(self.create_system_restore_point)
        layout.addWidget(restore_btn)
        
        # 自定义路径输入（用于特殊代码激活）
        custom_group = QGroupBox("自定义清理路径（输入特殊代码激活强力模式）")
        custom_layout = QVBoxLayout()
        
        self.deep_custom_path_edit = QLineEdit()
        self.deep_custom_path_edit.setPlaceholderText("输入路径或特殊代码激活强力模式")
        self.deep_custom_path_edit.textChanged.connect(self.check_deep_force_mode_activation)
        self.deep_custom_path_edit.setContextMenuPolicy(Qt.NoContextMenu)  # 禁用右键菜单
        
        add_btn = QPushButton("选择路径")
        add_btn.clicked.connect(self.add_deep_custom_path)
        
        # 状态标签
        self.deep_dev_mode_label = QLabel("强力模式: 未激活")
        if self.force_mode_activated:
            self.deep_dev_mode_label.setText("强力模式: <span style='color: green; font-weight: bold;'>已激活</span>")
        else:
            self.deep_dev_mode_label.setText("强力模式: 未激活")
        self.deep_dev_mode_label.setStyleSheet("color: gray; font-style: italic;")
        
        custom_layout.addWidget(QLabel("输入路径或特殊代码:"))
        custom_layout.addWidget(self.deep_custom_path_edit)
        custom_layout.addWidget(add_btn)
        custom_layout.addWidget(self.deep_dev_mode_label)
        custom_group.setLayout(custom_layout)
        layout.addWidget(custom_group)
        
        # 添加强力模式选项
        force_group = QGroupBox("开发者专用强力模式 (实验箱)")
        force_layout = QVBoxLayout()
        
        self.force_mode_check = QCheckBox("启用IRP强力清除模式 (危险!)")
        self.force_mode_check.setStyleSheet("color: #FF5722; font-weight: bold;")
        self.force_mode_check.setEnabled(self.force_mode_activated)
        self.force_mode_check.setChecked(self.force_mode_activated)
        
        force_note = QLabel(
            "此模式使用底层IRP操作强制清除被锁定的文件\n"
            "可能导致系统不稳定，仅限专业人员使用"
        )
        force_note.setStyleSheet("color: #795548; font-size: 10pt;")
        
        force_layout.addWidget(self.force_mode_check)
        force_layout.addWidget(force_note)
        force_group.setLayout(force_layout)
        layout.addWidget(force_group)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def add_deep_custom_path(self):
        """为深度清理模式添加自定义路径"""
        path = QFileDialog.getExistingDirectory(self, "选择清理目录")
        if path:
            self.deep_custom_path_edit.setText(path)

    def check_deep_force_mode_activation(self):
        """检查深度清理模式下是否输入了特殊代码"""
        text = self.deep_custom_path_edit.text().strip()
        if text == "&*dyz!!!!dyz*&":
            # 检查是否选择了自定义路径
            if self.deep_custom_path_edit.text().strip() == "":
                QMessageBox.warning(self, "激活失败", "请先在自定义路径列表中添加至少一个路径")
                return
                
            # 检查是否只选择了激活代码
            self.activate_developer_force_mode()
            self.deep_custom_path_edit.clear()

    def create_menu(self):
        """创建菜单栏"""
        menubar = self.menuBar()
        file_menu = menubar.addMenu('文件')
        
        exit_action = QAction('退出', self)
        exit_action.triggered.connect(self.close_app)
        file_menu.addAction(exit_action)
        
        tools_menu = menubar.addMenu('工具')
        # 添加创建系统还原点菜单项
        restore_action = QAction('创建系统还原点', self)
        restore_action.triggered.connect(self.create_system_restore_point)
        tools_menu.addAction(restore_action)
        
        help_menu = menubar.addMenu('帮助')
        
        # 添加"关于"菜单项
        about_action = QAction('关于', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
        
        # 添加"更新日志"菜单项
        log_action = QAction('更新日志', self)
        log_action.triggered.connect(self.show_update_log)
        help_menu.addAction(log_action)

    def check_force_mode_activation(self):
        """检查是否输入了强力模式激活代码"""
        text = self.force_path_edit.text().strip()
        if text == "&*dyz!!!!dyz*&":
            # 检查是否选择了自定义路径
            if self.path_list.count() == 0:
                QMessageBox.warning(self, "激活失败", "请先在自定义路径列表中添加至少一个路径")
                return
                
            # 检查是否只选择了激活代码
            self.activate_developer_force_mode()
            self.force_path_edit.clear()

    def activate_developer_force_mode(self):
        """激活开发者强力模式"""
        if self.developer_force_mode:
            return
            
        dialog = ForceModePasswordDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            self.developer_force_mode = True
            self.force_mode_activated = True
            self.deep_dev_mode_label.setText("强力模式: <span style='color: green; font-weight: bold;'>已激活</span>")
            self.dev_mode_label.setText("开发者模式: <span style='color: green; font-weight: bold;'>已激活</span>")
            self.force_mode_check.setEnabled(True)
            
            # 在深度清理模式启用强力模式选项
            if self.mode_combo.currentIndex() == 2:  # 深度清理模式
                self.force_mode_check.setChecked(True)
            
            # 保存配置
            self.save_config()
                
            QMessageBox.information(self, "强力模式激活", 
                "强力模式已激活！\n\n"
                "警告：此模式可能导致系统不稳定，使用需谨慎。")

    def show_update_log(self):
        """显示更新日志对话框"""
        log_dialog = UpdateLogDialog(self)
        log_dialog.exec_()

    def switch_mode(self):
        """切换用户模式"""
        index = self.mode_combo.currentIndex()
        self.stacked_widget.setCurrentIndex(index)
        
        # 当切换到深度清理模式时显示警告
        if index == 2:  # 深度清理模式
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("深度清理警告")
            msg_box.setText("⚠️ 警告: 深度清理模式会清理系统关键缓存文件，可能导致某些程序需要重新初始化。\n\n强烈建议在清理前创建系统还原点！是否现在创建？")
            
            # 使用确认和取消按钮
            confirm_btn = msg_box.addButton("确认", QMessageBox.YesRole)
            cancel_btn = msg_box.addButton("取消", QMessageBox.NoRole)
            msg_box.setDefaultButton(confirm_btn)
            
            msg_box.exec_()
            
            if msg_box.clickedButton() == confirm_btn:
                self.create_system_restore_point()
                
            # 如果开发者模式已激活，启用强力模式选项
            if self.developer_force_mode:
                self.force_mode_check.setEnabled(True)
            else:
                # 新增：未激活强力模式时禁用复选框
                self.force_mode_check.setEnabled(False)
                self.force_mode_check.setChecked(False)

    def add_custom_path(self):
        """添加自定义清理路径"""
        path = QFileDialog.getExistingDirectory(self, "选择清理目录")
        if path:
            self.path_list.addItem(path)

    def remove_custom_path(self):
        """移除选中的自定义路径"""
        for item in self.path_list.selectedItems():
            self.path_list.takeItem(self.path_list.row(item))

    def start_clean(self):
        """开始清理操作"""
        if self.worker and self.worker.isRunning():
            QMessageBox.warning(self, "警告", "清理操作正在进行中")
            return
        
        # 重置失败文件列表
        self.failed_files = []
        
        tasks = []
        mode = self.mode_combo.currentIndex()
        
        # 检查是否激活了开发者强力模式
        force_mode = self.force_mode_activated
        
        # 普通模式任务
        if mode == 0:
            for i, (text, _) in enumerate(self.normal_checks):
                if self.normal_checkboxes[i].isChecked():
                    paths = self.get_normal_path(text)
                    if text == "回收站":
                        # 特殊处理回收站
                        tasks.append((self.empty_recycle_bin, []))
                    elif isinstance(paths, list):
                        for path in paths:
                            tasks.append((self.clean_directory, [path, force_mode]))
                    else:
                        tasks.append((self.clean_directory, [path, force_mode]))
        
        # 高级模式任务
        elif mode == 1:
            # 检查是否只选择了激活代码
            if self.force_mode_activated and self.path_list.count() == 1:
                path = self.path_list.item(0).text()
                # 修复：传递正确的参数
                tasks.append((self.force_clean_directory, [path]))
            else:
                for i, (text, _) in enumerate(self.advanced_checks):
                    if self.advanced_checkboxes[i].isChecked():
                        path = self.get_advanced_path(text)
                        tasks.append((self.clean_directory, [path, force_mode]))
                
                # 添加自定义路径
                for i in range(self.path_list.count()):
                    path = self.path_list.item(i).text()
                    tasks.append((self.clean_directory, [path, force_mode]))
        
        # 深度清理模式任务
        elif mode == 2:
            force_mode = self.force_mode_check.isChecked()
            for i, (text, _) in enumerate(self.deep_clean_checks):
                if self.deep_clean_checkboxes[i].isChecked():
                    path = self.get_deep_clean_path(text)
                    if path:
                        # 修复：传递正确的参数
                        if force_mode:
                            tasks.append((self.force_clean_directory, [path]))
                        else:
                            tasks.append((self.clean_directory, [path, force_mode]))
            
            # 添加自定义路径
            custom_path = self.deep_custom_path_edit.text().strip()
            if custom_path and custom_path != "&*dyz!!!!dyz*&":
                if force_mode:
                    tasks.append((self.force_clean_directory, [custom_path]))
                else:
                    tasks.append((self.clean_directory, [custom_path, force_mode]))
        
        if not tasks:
            QMessageBox.warning(self, "警告", "请至少选择一个清理选项")
            return
        
        # 强力模式警告
        if force_mode:
            warning_msg = (
                "⚠️ 警告: 您即将使用开发者专用强力模式 (实验箱)！\n\n"
                "此操作将强制删除被系统锁定的文件，可能导致:\n"
                "- 正在运行的程序崩溃\n"
                "- 系统不稳定\n"
                "- 数据永久丢失\n\n"
                "注意: 此操作将绕过安全软件保护机制\n"
                "      可能触发安全软件警报\n\n"
                "您已明确授权并接受所有风险！"
            )
            
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("强力模式警告")
            msg_box.setText(warning_msg)
            
            # 使用确认和取消按钮
            confirm_btn = msg_box.addButton("确认", QMessageBox.YesRole)
            cancel_btn = msg_box.addButton("取消", QMessageBox.NoRole)
            msg_box.setDefaultButton(cancel_btn)
            
            msg_box.exec_()
            
            if msg_box.clickedButton() != confirm_btn:
                return
        
        self.clean_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在准备清理...")
        
        # 创建日志对话框（如果不存在）
        if not self.log_dialog:
            self.log_dialog = ErrorLogDialog("", self)
            self.log_dialog.setWindowTitle("清理日志 - 进行中")
        
        # 清空日志并显示
        self.log_dialog.text_edit.clear()
        self.log_dialog.show()
        
        # 创建并启动工作线程
        self.worker = CleanerWorker(tasks, force_mode)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.message.connect(self.status_label.setText)
        self.worker.finished.connect(self.on_clean_finished)
        self.worker.error.connect(self.show_error)
        self.worker.warning.connect(self.show_warning)
        self.worker.detailed_log.connect(self.log_dialog.append_log)
        self.worker.heartbeat.connect(self.heartbeat)
        self.worker.start()

    def heartbeat(self):
        """心跳响应，防止假死"""
        QApplication.processEvents()

    def update_ui(self):
        """更新UI，防止界面卡死"""
        QApplication.processEvents()

    def cancel_clean(self):
        """取消清理操作"""
        if self.worker and self.worker.isRunning():
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("确认取消")
            msg_box.setText("确定要取消清理操作吗？")
            
            # 使用确认和取消按钮
            confirm_btn = msg_box.addButton("确认", QMessageBox.YesRole)
            cancel_btn = msg_box.addButton("取消", QMessageBox.NoRole)
            msg_box.setDefaultButton(cancel_btn)
            
            msg_box.exec_()
            
            if msg_box.clickedButton() == confirm_btn:
                self.worker.cancel()
                self.cancel_btn.setEnabled(False)
                self.status_label.setText("正在取消清理...")
        else:
            self.cancel_btn.setEnabled(False)

    def log_message(self, message):
        """记录日志消息"""
        # 这里可以添加日志到文件或其他存储
        pass

    def get_normal_path(self, option):
        """获取普通模式清理路径"""
        user = os.getlogin()
        appdata = os.environ.get('APPDATA', f'C:\\Users\\{user}\\AppData\\Roaming')
        localappdata = os.environ.get('LOCALAPPDATA', f'C:\\Users\\{user}\\AppData\\Local')
        
        paths = {
            "临时文件": [
                os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Temp'),
                os.path.join(localappdata, 'Temp')
            ],
            "缩略图缓存": os.path.join(localappdata, 'Microsoft', 'Windows', 'Explorer'),
            "回收站": "",  # 特殊处理，不返回路径
            "下载文件夹": os.path.join(os.environ.get('USERPROFILE', f'C:\\Users\\{user}'), 'Downloads'),
            "浏览器缓存": [
                os.path.join(localappdata, 'Google', 'Chrome', 'User Data', 'Default', 'Cache'),
                os.path.join(localappdata, 'Microsoft', 'Edge', 'User Data', 'Default', 'Cache'),
                os.path.join(localappdata, 'Mozilla', 'Firefox', 'Profiles')
            ],
            "Windows日志文件": os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Logs')
        }
        return paths.get(option, "")

    def get_advanced_path(self, option):
        """获取高级模式清理路径"""
        user = os.getlogin()
        localappdata = os.environ.get('LOCALAPPDATA', f'C:\\Users\\{user}\\AppData\\Local')
        programdata = os.environ.get('ProgramData', 'C:\\ProgramData')
        windir = os.environ.get('WINDIR', 'C:\\Windows')
        
        paths = {
            "系统临时文件": os.path.join(windir, 'Temp'),
            "Windows更新缓存": os.path.join(windir, 'SoftwareDistribution', 'Download'),
            "事件日志文件": os.path.join(windir, 'System32', 'winevt', 'Logs'),
            "错误报告": os.path.join(programdata, 'Microsoft', 'Windows', 'WER'),
            "DirectX着色器缓存": os.path.join(localappdata, 'D3DSCache'),
            "Delivery优化文件": os.path.join(windir, 'ServiceProfiles', 'NetworkService', 'AppData', 'Local', 'Microsoft', 'Windows', 'DeliveryOptimization'),
            "Windows Defender缓存": os.path.join(programdata, 'Microsoft', 'Windows Defender', 'Scans', 'History'),
            "Microsoft Office缓存": [
                os.path.join(localappdata, 'Microsoft', 'Office', '16.0', 'OfficeFileCache'),
                os.path.join(localappdata, 'Microsoft', 'Office', 'ClickToRun', 'Pipeline')
            ]
        }
        return paths.get(option, "")

    def get_deep_clean_path(self, option):
        """获取深度清理模式路径"""
        windir = os.environ.get('WINDIR', 'C:\\Windows')
        programdata = os.environ.get('ProgramData', 'C:\\ProgramData')
        localappdata = os.environ.get('LOCALAPPDATA', f'C:\\Users\\{os.getlogin()}\\AppData\\Local')
        
        paths = {
            "旧的Windows更新文件": os.path.join(windir, 'SoftwareDistribution', 'Download'),
            "系统内存转储文件": os.path.join(windir, 'MEMORY.DMP'),
            "预读取文件": os.path.join(windir, 'Prefetch'),
            "字体缓存": os.path.join(windir, 'ServiceProfiles', 'LocalService', 'AppData', 'Local', 'FontCache'),
            "Windows Installer缓存": os.path.join(windir, 'Installer'),
            "系统日志存档": os.path.join(windir, 'System32', 'LogFiles'),
            "Windows错误报告存档": os.path.join(programdata, 'Microsoft', 'Windows', 'WER', 'ReportArchive'),
            "DirectX着色器缓存（深度）": [
                os.path.join(localappdata, 'D3DSCache'),
                os.path.join(localappdata, 'NVIDIA Corporation', 'NV_Cache')
            ]
        }
        return paths.get(option, "")

    def clean_directory(self, path, force_mode=False):
        """清理指定目录"""
        if isinstance(path, list):
            for p in path:
                self._clean_single_dir(p, force_mode)
        else:
            self._clean_single_dir(path, force_mode)

    def _clean_single_dir(self, path, force_mode=False):
        """清理单个目录 - 确保实际删除文件"""
        if self.worker:
            self.worker.log(f"开始清理: {path} (模式: {'强力' if force_mode else '普通'})")
        
        if not os.path.exists(path):
            if self.worker:
                self.worker.log(f"路径不存在: {path}")
            return
        
        try:
            # 获取目录内容
            items = os.listdir(path)
            total_items = len(items)
            
            # 分批次处理，避免卡顿
            for i in range(0, total_items, self.worker.batch_size):
                batch = items[i:i+self.worker.batch_size]
                for item in batch:
                    # 定期检查是否被取消
                    if self.worker and self.worker.is_canceled:
                        return
                    
                    item_path = os.path.join(path, item)
                    
                    # 跳过系统关键文件（仅在非实验箱模式下）
                    if not self.force_mode_activated:
                        system_files = [
                            "ntoskrnl.exe", "hal.dll", "winload.exe", "winresume.exe",
                            "bootmgr", "pagefile.sys", "hiberfil.sys", "swapfile.sys"
                        ]
                        
                        if os.path.basename(item_path).lower() in system_files:
                            if self.worker:
                                self.worker.log(f"跳过系统关键文件: {item_path}")
                            continue
                    
                    try:
                        if os.path.isfile(item_path) or os.path.islink(item_path):
                            # 跳过系统关键文件
                            if item == "MEMORY.DMP" and "Windows" in path:
                                if self.worker:
                                    self.worker.log(f"跳过系统内存转储文件: {item_path}")
                                continue
                                
                            # 尝试删除文件
                            self.delete_file(item_path, force_mode)
                        elif os.path.isdir(item_path):
                            # 尝试删除目录
                            self.delete_directory(item_path, force_mode)
                    except Exception as e:
                        if self.worker:
                            self.worker.log(f"删除失败 {item_path}: {e}")
                    
                    # 发送心跳信号，防止假死
                    if self.worker:
                        self.worker.heartbeat.emit()
        except Exception as e:
            if self.worker:
                self.worker.log(f"清理路径 {path} 时出错: {e}")

    def force_clean_directory(self, path):
        """强力模式清理目录 - 修复：只接受一个参数"""
        if self.worker:
            self.worker.log(f"【强力模式】开始清理: {path}")
        
        if not os.path.exists(path):
            if self.worker:
                self.worker.log(f"路径不存在: {path}")
            return
        
        try:
            # 特殊处理：预读取文件需要管理员权限
            if "Prefetch" in path:
                self.clean_prefetch(True)  # 总是使用强力模式
                return
            
            # 修复：使用 os.listdir 而不是 os.list
            items = os.listdir(path)
            total_items = len(items)
            
            # 分批次处理
            for i in range(0, total_items, self.worker.batch_size):
                batch = items[i:i+self.worker.batch_size]
                for item in batch:
                    # 定期检查是否被取消
                    if self.worker and self.worker.is_canceled:
                        return
                    
                    item_path = os.path.join(path, item)
                    try:
                        if os.path.isfile(item_path) or os.path.islink(item_path):
                            # 跳过系统关键文件
                            if item == "MEMORY.DMP" and "Windows" in path:
                                if self.worker:
                                    self.worker.log(f"跳过系统内存转储文件: {item_path}")
                                continue
                                
                            # 尝试强制删除文件
                            self.force_delete_file(item_path)
                        elif os.path.isdir(item_path):
                            # 尝试强制删除目录
                            self.force_delete_directory(item_path)
                    except Exception as e:
                        if self.worker:
                            self.worker.log(f"【强力模式】删除失败 {item_path}: {e}")
                    
                    # 发送心跳信号，防止假死
                    if self.worker:
                        self.worker.heartbeat.emit()
        except Exception as e:
            if self.worker:
                self.worker.log(f"【强力模式】清理路径 {path} 时出错: {e}")

    def delete_file(self, file_path, force_mode=False):
        """安全删除文件 - 确保实际删除"""
        try:
            # 尝试直接删除
            os.unlink(file_path)
            if self.worker:
                self.worker.log(f"已删除文件: {file_path} (普通删除方法)")
                
            # 验证文件是否被删除
            if os.path.exists(file_path):
                if self.worker:
                    self.worker.log(f"文件删除后仍然存在: {file_path}")
                if force_mode:
                    # 如果强力模式激活，尝试强制删除
                    self.force_delete_file(file_path)
                else:
                    raise Exception("文件删除后仍然存在")
        except PermissionError:
            if force_mode:
                # 如果强力模式激活，尝试强制删除
                self.force_delete_file(file_path)
            else:
                error_msg = f"权限不足: {file_path}"
                if self.worker:
                    self.worker.log(error_msg)
                    self.worker.warning.emit(error_msg)
        except Exception as e:
            error_msg = f"删除文件失败 {file_path}: {e}"
            if self.worker:
                self.worker.log(error_msg)
                self.worker.warning.emit(error_msg)

    def delete_directory(self, dir_path, force_mode=False):
        """安全删除目录 - 确保实际删除"""
        try:
            # 尝试直接删除
            shutil.rmtree(dir_path)
            if self.worker:
                self.worker.log(f"已删除目录: {dir_path} (普通删除方法)")
                
            # 验证目录是否被删除
            if os.path.exists(dir_path):
                if self.worker:
                    self.worker.log(f"目录删除后仍然存在: {dir_path}")
                if force_mode:
                    # 如果强力模式激活，尝试强制删除
                    self.force_delete_directory(dir_path)
                else:
                    raise Exception("目录删除后仍然存在")
        except PermissionError:
            if force_mode:
                # 如果强力模式激活，尝试强制删除
                self.force_delete_directory(dir_path)
            else:
                error_msg = f"权限不足: {dir_path}"
                if self.worker:
                    self.worker.log(error_msg)
                    self.worker.warning.emit(error_msg)
        except Exception as e:
            error_msg = f"删除目录失败 {dir_path}: {e}"
            if self.worker:
                self.worker.log(error_msg)
                self.worker.warning.emit(error_msg)

    def force_delete_file(self, file_path):
        """强制删除文件 - 使用IRP操作，确保实际删除"""
        if self.worker and self.worker.is_canceled:
            return
        
        try:
            if self.worker:
                self.worker.log(f"【强力模式】尝试强制删除文件: {file_path}")
            
            # 检查文件是否被占用
            if self.is_file_running(file_path):
                if self.worker:
                    self.worker.log(f"检测到文件被占用: {file_path}")
                
                # 尝试结束相关进程
                if self.kill_processes_using_file(file_path):
                    if self.worker:
                        self.worker.log(f"成功结束占用文件的进程: {file_path}")
                    # 给系统一点时间释放资源
                    time.sleep(1)
                else:
                    if self.worker:
                        self.worker.log(f"无法结束占用文件的进程: {file_path}")
                    
                    # 尝试解除文件锁定
                    if self.unlock_file(file_path):
                        if self.worker:
                            self.worker.log(f"成功解除文件锁定: {file_path}")
                        # 给系统一点时间释放资源
                        time.sleep(1)
            
            # 获取文件所有权并设置权限
            try:
                self.take_ownership(file_path)
                if self.worker:
                    self.worker.log(f"已获取文件所有权: {file_path}")
            except Exception as e:
                if self.worker:
                    self.worker.log(f"获取文件所有权失败: {file_path} - {e}")
            
            # 方法1: 使用重命名后删除（最可靠）
            try:
                # 生成随机临时文件名
                temp_dir = os.path.dirname(file_path)
                temp_name = f".{uuid.uuid4().hex[:8]}.tmp"
                temp_path = os.path.join(temp_dir, temp_name)
                
                # 重命名文件
                os.rename(file_path, temp_path)
                
                # 删除重命名后的文件
                os.unlink(temp_path)
                
                if self.worker:
                    self.worker.log(f"【强力模式】重命名后删除成功: {file_path}")
                
                # 验证文件是否被删除
                if os.path.exists(file_path) or os.path.exists(temp_path):
                    if self.worker:
                        self.worker.log(f"【强力模式】重命名删除后文件仍存在: {file_path}")
                    raise Exception("重命名删除后文件仍存在")
                else:
                    return  # 成功删除，不再尝试其他方法
            except Exception as e:
                if self.worker:
                    self.worker.log(f"【强力模式】重命名删除失败: {e}")
            
            # 方法2: 使用FILE_FLAG_DELETE_ON_CLOSE
            try:
                # 获取文件句柄，并设置删除标志
                handle = win32file.CreateFile(
                    file_path,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE | win32file.FILE_SHARE_DELETE,
                    None,
                    win32file.OPEN_EXISTING,
                    win32file.FILE_ATTRIBUTE_NORMAL | win32file.FILE_FLAG_DELETE_ON_CLOSE,
                    None
                )
                win32file.CloseHandle(handle)
                if self.worker:
                    self.worker.log(f"【强力模式】文件标记为关闭时删除: {file_path}")
                
                # 验证文件是否被删除
                if os.path.exists(file_path):
                    if self.worker:
                        self.worker.log(f"【强力模式】FILE_FLAG_DELETE_ON_CLOSE未生效: {file_path}")
                    raise Exception("FILE_FLAG_DELETE_ON_CLOSE未生效")
                else:
                    return
            except Exception as e:
                if self.worker:
                    self.worker.log(f"【强力模式】使用FILE_FLAG_DELETE_ON_CLOSE删除失败: {e}")
            
            # 方法3: 使用SetFileInformationByHandle设置删除标志
            try:
                # 获取文件句柄
                handle = win32file.CreateFile(
                    file_path,
                    win32file.GENERIC_WRITE,
                    win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE | win32file.FILE_SHARE_DELETE,
                    None,
                    win32file.OPEN_EXISTING,
                    win32file.FILE_FLAG_BACKUP_SEMANTICS | win32file.FILE_FLAG_OPEN_REPARSE_POINT,
                    None
                )
                
                # 设置文件删除标志
                delete_flag = ctypes.c_byte(1)
                
                # 调用Windows API设置删除标志
                result = SetFileInformationByHandle(
                    handle.handle,
                    FileDispositionInfo,
                    ctypes.byref(delete_flag),
                    ctypes.sizeof(delete_flag)
                )
                
                if not result:
                    error_code = ctypes.windll.kernel32.GetLastError()
                    raise ctypes.WinError(error_code)
                
                win32file.CloseHandle(handle)
                if self.worker:
                    self.worker.log(f"【强力模式】文件标记为删除: {file_path}")
                
                # 验证文件是否被删除
                if os.path.exists(file_path):
                    if self.worker:
                        self.worker.log(f"【强力模式】SetFileInformationByHandle未生效: {file_path}")
                    raise Exception("SetFileInformationByHandle未生效")
                else:
                    return
            except Exception as e:
                if self.worker:
                    self.worker.log(f"【强力模式】SetFileInformationByHandle删除失败: {e}")
            
            # 方法4: 使用命令行强制删除（使用takeown和icacls）
            try:
                # 创建批处理文件
                batch_content = f"""
                @echo off
                :loop
                takeown /f "{file_path}" >nul 2>&1
                icacls "{file_path}" /grant administrators:F >nul 2>&1
                del /f /q "{file_path}" >nul 2>&1
                if exist "{file_path}" (
                    timeout /t 1 /nobreak >nul
                    goto loop
                )
                """
                batch_path = os.path.join(os.environ['TEMP'], f"del_{uuid.uuid4().hex[:8]}.bat")
                with open(batch_path, "w", encoding="gbk") as f:
                    f.write(batch_content)
                
                # 直接运行批处理（增加超时处理）
                subprocess.run(f'cmd /c "{batch_path}"', shell=True, timeout=30)
                os.unlink(batch_path)
                
                if self.worker:
                    self.worker.log(f"【强力模式】命令行强制删除成功: {file_path}")
                
                # 验证文件是否被删除
                if os.path.exists(file_path):
                    if self.worker:
                        self.worker.log(f"【强力模式】命令行删除后文件仍存在: {file_path}")
                    raise Exception("命令行删除后文件仍存在")
            except subprocess.TimeoutExpired:
                if self.worker:
                    self.worker.log(f"【强力模式】命令行强制删除超时: {file_path}")
                raise Exception("命令行强制删除超时")
            except Exception as e:
                if self.worker:
                    self.worker.log(f"【强力模式】命令行强制删除失败: {e}")
            
            # 方法5: 重启后删除
            try:
                # 使用MoveFileEx设置重启后删除
                MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
                ctypes.windll.kernel32.MoveFileExW(file_path, None, MOVEFILE_DELAY_UNTIL_REBOOT)
                if self.worker:
                    self.worker.log(f"【强力模式】文件将在重启后删除: {file_path}")
                self.failed_files.append((file_path, "文件将在系统重启后删除"))
            except Exception as e:
                if self.worker:
                    self.worker.log(f"【强力模式】设置重启删除失败: {e}")
                raise
        except Exception as e:
            error_msg = f"【强力模式】强制删除文件失败: {file_path} - {e}"
            if self.worker:
                self.worker.log(error_msg)
            self.failed_files.append((file_path, str(e)))
        finally:
            # 发送心跳信号，防止假死
            if self.worker:
                self.worker.heartbeat.emit()
            
    def take_ownership(self, file_path):
        """获取文件所有权并设置完全控制权限"""
        try:
            # 获取文件安全描述符
            sd = win32security.GetFileSecurity(file_path, win32security.OWNER_SECURITY_INFORMATION)
            user, domain, _ = win32security.LookupAccountName("", os.getenv("USERNAME"))
            
            # 设置新的所有者
            sd.SetSecurityDescriptorOwner(user, False)
            
            # 设置新的DACL
            dacl = win32security.ACL()
            dacl.AddAccessAllowedAce(win32security.ACL_REVISION, win32con.FILE_ALL_ACCESS, user)
            sd.SetSecurityDescriptorDacl(1, dacl, 0)
            
            # 应用新的安全描述符
            win32security.SetFileSecurity(file_path, win32security.DACL_SECURITY_INFORMATION | win32security.OWNER_SECURITY_INFORMATION, sd)
            
            return True
        except Exception as e:
            if self.worker:
                self.worker.log(f"获取文件所有权失败: {file_path} - {e}")
            return False

    def is_file_running(self, file_path):
        """检查文件是否被进程使用"""
        try:
            file_path = os.path.abspath(file_path).lower()
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'open_files']):
                try:
                    # 检查可执行文件本身
                    if proc.info.get('exe') and os.path.abspath(proc.info['exe']).lower() == file_path:
                        return True
                    
                    # 检查打开的文件
                    files = proc.info.get('open_files')
                    if files:
                        for f in files:
                            if os.path.abspath(f.path).lower() == file_path:
                                return True
                except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                    continue
            return False
        except Exception as e:
            if self.worker:
                self.worker.log(f"检查文件是否运行时出错: {e}")
            return False

    def kill_processes_using_file(self, file_path):
        """结束使用指定文件的进程"""
        try:
            file_path = os.path.abspath(file_path).lower()
            killed = False
            
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'open_files']):
                try:
                    pid = proc.pid
                    name = proc.info.get('name', '未知进程')
                    
                    # 跳过系统关键进程
                    if name.lower() in ['system', 'svchost.exe', 'explorer.exe', 'wininit.exe', 'csrss.exe']:
                        continue
                    
                    # 检查可执行文件本身
                    exe_path = proc.info.get('exe')
                    if exe_path and os.path.abspath(exe_path).lower() == file_path:
                        proc.kill()
                        if self.worker:
                            self.worker.log(f"已结束进程 {pid} ({name}) 使用文件: {file_path}")
                        killed = True
                        continue
                    
                    # 检查打开的文件
                    files = proc.info.get('open_files')
                    if files:
                        for f in files:
                            if os.path.abspath(f.path).lower() == file_path:
                                proc.kill()
                                if self.worker:
                                    self.worker.log(f"已结束进程 {pid} ({name}) 使用文件: {file_path}")
                                killed = True
                                break
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
                except Exception as e:
                    if self.worker:
                        self.worker.log(f"结束进程 {pid} 时出错: {e}")
            
            return killed
        except Exception as e:
            if self.worker:
                self.worker.log(f"结束进程时出错: {e}")
            return False

    def terminate_processes_aggressively(self, file_path):
        """更强大的进程终止方式"""
        try:
            file_path = os.path.abspath(file_path).lower()
            
            # 方法1：使用taskkill强制终止
            try:
                subprocess.run(f'taskkill /f /im "{os.path.bastname(file_path)}"', 
                              shell=True, check=True, timeout=10)
                self.worker.log(f"使用taskkill强制终止进程: {file_path}")
                return True
            except:
                pass
            
            # 方法2：使用WMIC终止进程
            try:
                process_name = os.path.basename(file_path)
                subprocess.run(f'wmic process where "name=\'{process_name}\'" delete', 
                              shell=True, check=True, timeout=10)
                self.worker.log(f"使用WMIC强制终止进程: {file_path}")
                return True
            except:
                pass
            
            # 方法3：使用psexec以SYSTEM权限终止
            try:
                base_dir = os.path.dirname(os.path.abspath(__file__))
                tools_dir = os.path.join(base_dir, "tools")
                if not os.path.exists(tools_dir):
                    tools_dir = os.path.join(os.environ['TEMP'], "adsCleanerTools")
                
                psexec_path = os.path.join(tools_dir, "PsExec64.exe" if sys.maxsize > 2**32 else "PsExec.exe")
                
                if os.path.exists(psexec_path):
                    subprocess.run(
                        f'"{psexec_path}" -accepteula -s taskkill /f /im "{os.path.basename(file_path)}"',
                        shell=True, check=True, timeout=15
                    )
                    self.worker.log(f"使用psexec以SYSTEM权限终止进程: {file_path}")
                    return True
            except Exception as e:
                self.worker.log(f"使用psexec终止进程失败: {e}")
            
            return False
        except Exception as e:
            self.worker.log(f"强力终止进程时出错: {e}")
            return False

    def unlock_file(self, file_path):
        """使用特殊技术解除文件锁定"""
        try:
            if self.worker:
                self.worker.log(f"尝试解除文件锁定: {file_path}")
            
            # 方法1: 使用Windows内置工具handle.exe
            if self.try_unlock_with_handle(file_path):
                return True
            
            # 方法2: 使用底层API强制关闭句柄
            if self.try_unlock_with_api(file_path):
                return True
            
            return False
        except Exception as e:
            if self.worker:
                self.worker.log(f"解除文件锁定时出错: {e}")
            return False

    def try_unlock_with_handle(self, file_path):
        """使用Sysinternals的handle.exe解除文件锁定"""
        try:
            # 检查handle.exe是否可用
            base_dir = os.path.dirname(os.path.abspath(__file__))
            tools_dir = os.path.join(base_dir, "tools")
            if not os.path.exists(tools_dir):
                tools_dir = os.path.join(os.environ['TEMP'], "adsCleanerTools")
            
            handle_exe = os.path.join(tools_dir, "handle.exe")
            
            if not os.path.exists(handle_exe):
                # 尝试64位版本
                handle_exe = os.path.join(tools_dir, "handle64.exe")
            
            if not os.path.exists(handle_exe):
                self.worker.log("未找到handle.exe，跳过此方法")
                return False
            
            self.worker.log(f"使用handle.exe解除文件锁定: {file_path}")
            
            # 查找文件句柄
            result = subprocess.run(
                [handle_exe, '-accepteula', file_path],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            
            if result.returncode != 0:
                self.worker.log(f"handle.exe执行失败: {result.stderr}")
                return False
                
            if "No matching handles found" in result.stdout:
                self.worker.log("未找到匹配的文件句柄")
                return False
                
            # 关闭所有相关句柄
            subprocess.run(
                [handle_exe, '-accepteula', '-c', file_path, '-y'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.worker.log("已使用handle.exe关闭文件句柄")
            return True
        except Exception as e:
            self.worker.log(f"使用handle.exe解锁失败: {e}")
            return False

    def try_unlock_with_api(self, file_path):
        """使用Windows API解除文件锁定"""
        try:
            self.worker.log(f"尝试使用Windows API解除文件锁定: {file_path}")
            
            # 定义必要的Windows API
            kernel32 = ctypes.Windll('kernel32', use_last_error=True)
            
            # 定义结构体和常量
            FILE_SHARE_READ = 1
            FILE_SHARE_WRITE = 2
            FILE_SHARE_DELETE = 4
            OPEN_EXISTING = 3
            
            # 使用正确的属性名：win32file.FILE_FLAG_BACKUP_SEMANTICS
            FILE_FLAG_BACKUP_SEMANTICS = win32file.FILE_FLAG_BACKUP_SEMANTICS
            
            # 尝试打开文件
            handle = kernel32.CreateFileW(
                file_path,
                0,  # 无访问权限
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                None,
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS,
                None
            )
            
            if handle == -1:  # INVALID_HANDLE_VALUE
                error = ctypes.get_last_error()
                self.worker.log(f"无法打开文件句柄 (错误代码: {error})")
                return False
            
            # 尝试设置文件删除标志
            FILE_DISPOSITION_INFO = 4
            disposition_info = ctypes.c_byte(1)  # 设置为True表示删除
            
            result = SetFileInformationByHandle(
                handle,
                FILE_DISPOSITION_INFO,
                ctypes.byref(disposition_info),
                ctypes.sizeof(disposition_info)
            )
            
            if not result:
                error_code = ctypes.windll.kernel32.GetLastError()
                self.worker.log(f"SetFileInformationByHandle失败 (错误代码: {error_code})")
            
            # 关闭句柄
            kernel32.CloseHandle(handle)
            
            return bool(result)
        except Exception as e:
            self.worker.log(f"使用Windows API解锁失败: {e}")
            return False

    def force_delete_directory(self, dir_path):
        """强制删除目录 - 使用IRP操作"""
        if self.worker and self.worker.is_canceled:
            return
        
        try:
            if self.worker:
                self.worker.log(f"【强力模式】尝试强制删除目录: {dir_path}")
            
            # 先删除目录内容
            for root, dirs, files in os.walk(dir_path, topdown=False):
                for name in files:
                    if self.worker and self.worker.is_canceled:
                        return
                    file_path = os.path.join(root, name)
                    self.force_delete_file(file_path)
                    
                    # 发送心跳信号，防止假死
                    if self.worker:
                        self.worker.heartbeat.emit()
                
                for name in dirs:
                    if self.worker and self.worker.is_canceled:
                        return
                    subdir_path = os.path.join(root, name)
                    self.force_delete_directory(subdir_path)
                    
                    # 发送心跳信号，防止假死
                    if self.worker:
                        self.worker.heartbeat.emit()
            
            # 然后删除目录本身
            try:
                # 使用IRP删除目录
                handle = win32file.CreateFile(
                    dir_path,
                    win32file.GENERIC_WRITE,
                    win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE | win32file.FILE_SHARE_DELETE,
                    None,
                    win32file.OPEN_EXISTING,
                    win32file.FILE_FLAG_BACKUP_SEMANTICS | win32file.FILE_FLAG_OPEN_REPARSE_POINT,
                    None
                )
                
                # 设置目录删除标志
                delete_flag = ctypes.c_byte(1)  # 1表示删除目录
                
                # 调用Windows API设置删除标志
                result = SetFileInformationByHandle(
                    handle.handle,  # 获取底层HANDLE
                    FileDispositionInfo,
                    ctypes.byref(delete_flag),
                    ctypes.sizeof(delete_flag)
                )
                
                if not result:
                    error_code = ctypes.windll.kernel32.GetLastError()
                    raise ctypes.WinError(error_code)
                
                win32file.CloseHandle(handle)
                if self.worker:
                    self.worker.log(f"【强力模式】目录标记为删除: {dir_path}")
            except Exception as e:
                if self.worker:
                    self.worker.log(f"【强力模式】IRP删除目录失败: {e}")
                
                # 方法2: 使用命令行强制删除（提权到SYSTEM）
                try:
                    # 创建批处理文件
                    batch_content = f"""
                    @echo off
                    :loop
                    takeown /f "{dir_path}" /r /d y >nul 2>&1
                    icacls "{dir_path}" /grant administrators:F /t /c >nul 2>&1
                    rd /s /q "{dir_path}" >nul 2>&1
                    if exist "{dir_path}" (
                        timeout /t 1 /nobreak >nul
                        goto loop
                    )
                    """
                    batch_path = os.path.join(os.environ['TEMP'], f"rd_{uuid.uuid4().hex[:8]}.bat")
                    with open(batch_path, "w", encoding="gbk") as f:
                        f.write(batch_content)
                    
                    # 使用psexec以SYSTEM权限运行
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    tools_dir = os.path.join(base_dir, "tools")
                    if not os.path.exists(tools_dir):
                        tools_dir = os.path.join(os.environ['TEMP'], "adsCleanerTools")
                    
                    psexec_path = os.path.join(tools_dir, "PsExec64.exe" if sys.maxsize > 2**32 else "PsExec.exe")
                    
                    if os.path.exists(psexec_path):
                        # 以SYSTEM权限运行
                        subprocess.run(f'"{psexec_path}" -accepteula -s -d cmd /c "{batch_path}"', shell=True, timeout=60)
                    else:
                        # 如果没有psexec，尝试直接运行
                        subprocess.run(f'cmd /c "{batch_path}"', shell=True, timeout=60)
                    
                    os.unlink(batch_path)
                    if self.worker:
                        self.worker.log(f"【强力模式】命令行强制删除目录成功: {dir_path}")
                except subprocess.TimeoutExpired:
                    if self.worker:
                        self.worker.log(f"【强力模式】命令行强制删除目录超时: {dir_path}")
                    raise Exception("命令行强制删除目录超时")
                except Exception as e2:
                    if self.worker:
                        self.worker.log(f"【强力模式】命令行强制删除目录失败: {e2}")
                    
                    # 方法3: 重启后删除
                    try:
                        # 使用MoveFileEx设置重启后删除
                        MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
                        ctypes.windll.kernel32.MoveFileExW(dir_path, None, MOVEFILE_DELAY_UNTIL_REBOOT)
                        if self.worker:
                            self.worker.log(f"【强力模式】目录将在重启后删除: {dir_path}")
                        self.failed_files.append((dir_path, "目录将在系统重启后删除"))
                    except Exception as e3:
                        if self.worker:
                            self.worker.log(f"【强力模式】设置重启删除失败: {e3}")
                        raise
        except Exception as e:
            error_msg = f"【强力模式】强制删除目录失败: {dir_path} - {e}"
            if self.worker:
                self.worker.log(error_msg)
            self.failed_files.append((dir_path, str(e)))
        finally:
            # 发送心跳信号，防止假死
            if self.worker:
                self.worker.heartbeat.emit()

    def clean_prefetch(self, force_mode=False):
        """清理预读取文件（需要特殊处理）"""
        prefetch_path = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Prefetch')
        
        if not os.path.exists(prefetch_path):
            if self.worker:
                self.worker.log("预读取文件夹不存在")
            return
            
        try:
            # 使用管理员权限删除
            if force_mode:
                # 强力模式下强制删除
                self.force_delete_directory(prefetch_path)
            else:
                subprocess.run(f'cmd /c "del /f /q "{prefetch_path}\\*.*""', shell=True, check=True, timeout=30)
            if self.worker:
                self.worker.log("已清理预读取文件")
        except subprocess.TimeoutExpired:
            if self.worker:
                self.worker.log("清理预读取文件超时")
        except Exception as e:
            if self.worker:
                self.worker.log(f"清理预读取文件失败: {e}")

    def empty_recycle_bin(self):
        """清空回收站"""
        try:
            # 使用send2trash清空回收站
            send2trash.send2trash([])
            if self.worker:
                self.worker.log("回收站已清空 (send2trash方法)")
        except Exception as e:
            if self.worker:
                self.worker.log(f"清空回收站失败: {e}")
            # 备选方案：使用命令行
            try:
                subprocess.run('cmd /c "rd /s /q C:\\$Recycle.bin"', shell=True, check=True, timeout=30)
                if self.worker:
                    self.worker.log("使用命令行清空回收站成功")
            except subprocess.TimeoutExpired:
                if self.worker:
                    self.worker.log("命令行清空回收站超时")
            except Exception as ex:
                if self.worker:
                    self.worker.log(f"命令行清空回收站失败: {ex}")

    def create_system_restore_point(self):
        """创建系统还原点"""
        try:
            # 显示对话框让用户输入还原点信息
            dialog = RestorePointDialog(self)
            if dialog.exec_() != QDialog.Accepted:
                return
                
            description, type_name = dialog.get_data()
            
            # 如果用户没有输入描述，使用默认描述
            if not description.strip():
                description = f"adsCleaner创建的还原点 ({os.getlogin()})"
            
            # 映射类型到系统还原点类型
            type_map = {
                "应用程序安装": 0,
                "应用程序卸载": 1,
                "系统更新": 2,
                "手动创建": 3,
                "其他": 4
            }
            
            type_value = type_map.get(type_name, 3)  # 默认为手动创建
            
            # 方法1：使用Windows命令创建还原点
            type_str_map = {
                "应用程序安装": "APPLICATION_INSTALL",
                "应用程序卸载": "APPLICATION_UNINSTALL",
                "系统更新": "MODIFY_SETTINGS",
                "手动创建": "MODIFY_SETTINGS",
                "其他": "MODIFY_SETTINGS"
            }
            
            type_str = type_str_map.get(type_name, "MODIFY_SETTINGS")
            command = f'powershell -Command "Checkpoint-Computer -Description \\"{description}\\" -RestorePointType \\"{type_str}\\""'
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                QMessageBox.information(self, "成功", "系统还原点创建成功！")
                return
            else:
                print(f"命令创建还原点失败: {result.stderr}")
                
            # 方法2：使用WMI API（如果命令失败）
            try:
                wmi = win32com.client.GetObject("winmgmts:\\\\.\\root\\default")
                system_restore = wmi.Get("SystemRestore")
                
                # 创建还原点
                result = system_restore.CreateRestorePoint(description, type_value, 100)
                
                if result == 0:
                    QMessageBox.information(self, "成功", "系统还原点创建成功！")
                else:
                    QMessageBox.warning(self, "警告", f"系统还原点创建失败，错误代码: {result}")
            except Exception as wmi_error:
                print(f"WMI创建还原点失败: {wmi_error}")
                # 方法3：打开系统还原界面
                try:
                    subprocess.run('control sysdm.cpl,,4', shell=True)
                    QMessageBox.information(self, "提示", "已打开系统还原设置界面，请手动创建还原点。")
                except Exception as ui_error:
                    print(f"打开系统还原界面失败: {ui_error}")
                    QMessageBox.critical(self, "错误", "无法创建系统还原点，请检查系统还原功能是否启用")
        except subprocess.TimeoutExpired:
            QMessageBox.critical(self, "错误", "创建系统还原点超时")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"创建系统还原点时发生错误:\n{str(e)}")

    def open_uninstaller(self):
        """打开系统卸载程序"""
        try:
            subprocess.run('control appwiz.cpl', shell=True)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开卸载程序:\n{str(e)}")

    def on_clean_finished(self):
        """清理完成处理"""
        self.clean_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        # 更新日志对话框标题
        if self.log_dialog:
            self.log_dialog.setWindowTitle("清理日志 - 已完成")
        
        # 收集并显示日志
        logs = ""
        if self.worker:
            logs = self.worker.get_logs()
        
        # 如果有失败的文件，添加到日志
        if self.failed_files:
            logs += "\n\n无法清理的文件:\n"
            for file_path, reason in self.failed_files:
                logs += f"- {file_path}: {reason}\n"
            
            if any("将在系统重启后删除" in r for _, r in self.failed_files):
                logs += "\n注意: 部分文件将在系统重启后删除"
        
        # 在日志对话框中显示最终结果
        if self.log_dialog:
            self.log_dialog.text_edit.append("\n\n" + "="*50 + "\n清理完成!\n" + "="*50)
        
        # 不再重置强力模式状态 - 移除相关代码
        QMessageBox.information(self, "完成", "清理操作已完成!")
            
        self.progress_bar.setValue(0)
        self.status_label.setText("就绪")

    def show_error(self, msg):
        """显示错误信息"""
        QMessageBox.critical(self, "错误", msg)
        self.clean_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
    
    def show_warning(self, msg):
        """显示警告信息"""
        self.status_label.setText(f"警告: {msg}")

    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(self, "关于 adsC盘清理大师", 
                         "版本: 1.2\n\n"
                         "一款深度清理C盘的专业工具\n"
                         "支持三种清理模式:\n"
                         "  - 普通用户模式\n"
                         "  - 技术人员模式\n"
                         "  - 深度清理模式\n\n"
                         "新增深度清理模式\n"
                         "许可证: MIT\n"
                         "开发者：dyz131005\n"
                         "邮箱: 3069278895@qq.com")

    def close_app(self):
        """关闭应用"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        self.save_config()  # 保存配置
        QApplication.quit()

    def closeEvent(self, event):
        """关闭事件处理"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        self.save_config()  # 保存配置
        event.accept()


def is_admin():
    """检查当前是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    """以管理员权限重新运行程序"""
    script = os.path.abspath(sys.argv[0])
    params = ' '.join([script] + sys.argv[1:])
    
    print(f"请求管理员权限...")
    
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
    except Exception as e:
        print(f"请求管理员权限失败: {e}")
        return False
    return True

if __name__ == "__main__":
    try:
        # 检查是否已经是管理员权限
        if not is_admin():
            print("当前不是管理员权限，尝试以管理员权限重启...")
            # 尝试以管理员权限重新运行
            if run_as_admin():
                print("已请求管理员权限，退出当前进程")
                sys.exit(0)
            else:
                print("管理员权限请求失败，继续运行（功能可能受限）")
        
        print("创建QApplication...")
        app = QApplication(sys.argv)
        
        print("创建主窗口...")
        window = DiskCleanerApp()
        
        print("显示窗口...")
        window.show()
        
        print("进入事件循环...")
        sys.exit(app.exec_())
    except Exception as e:
        # 将错误信息写入文件
        error_log = "error.log"
        with open(error_log, "w", encoding="utf-8") as f:
            f.write(f"程序崩溃: {str(e)}\n")
            f.write("堆栈跟踪:\n")
            f.write(traceback.format_exc())
        
        # 在控制台显示错误
        print(f"程序崩溃: {str(e)}")
        print(traceback.format_exc())
        
        # 尝试显示错误对话框
        try:
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "程序崩溃", f"发生未处理的异常:\n{str(e)}\n\n详细信息请查看 {error_log}")
            sys.exit(1)
        except:
            sys.exit(1)