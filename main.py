import sys
import os
import ctypes
import winreg
import psutil
import shutil
import send2trash
import traceback
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QComboBox, QGroupBox, QCheckBox, QProgressBar, QFileDialog,
    QListWidget, QStackedWidget, QMessageBox, QAction, QSystemTrayIcon, QMenu
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon

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

class CleanerWorker(QThread):
    """清理工作线程，负责在后台执行清理任务"""
    progress = pyqtSignal(int)
    message = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, tasks):
        super().__init__()
        self.tasks = tasks
        self.is_canceled = False

    def run(self):
        """执行清理任务"""
        try:
            total = len(self.tasks)
            for i, (func, args) in enumerate(self.tasks):
                if self.is_canceled:
                    break
                func(*args)
                self.progress.emit(int((i + 1) / total * 100))
                self.message.emit(f"清理中: {args[0] if args else func.__name__}")
            self.message.emit("清理完成!")
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def cancel(self):
        """取消清理任务"""
        self.is_canceled = True

class DiskCleanerApp(QMainWindow):
    """磁盘清理应用主窗口"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("adsC盘清理大师")
        self.setGeometry(100, 100, 800, 600)
        
        # 图标设置 - 使用相对路径
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
        else:
            print(f"警告: 图标文件未找到: {icon_path}")
        
        self.init_ui()
        self.worker = None

    def init_ui(self):
        """初始化用户界面"""
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # 模式选择
        mode_layout = QHBoxLayout()
        mode_label = QLabel("用户模式:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["普通用户", "技术人员"])
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
        
        self.stacked_widget.addWidget(self.normal_widget)
        self.stacked_widget.addWidget(self.advanced_widget)
        
        # 公共组件
        self.progress_bar = QProgressBar()
        self.status_label = QLabel("就绪")
        
        # 添加到主布局
        main_layout.addLayout(mode_layout)
        main_layout.addWidget(self.stacked_widget)
        main_layout.addWidget(self.progress_bar)
        main_layout.addWidget(self.status_label)
        
        # 操作按钮
        btn_layout = QHBoxLayout()
        self.clean_btn = QPushButton("开始清理")
        self.clean_btn.clicked.connect(self.start_clean)
        self.uninstall_btn = QPushButton("打开卸载程序")
        self.uninstall_btn.clicked.connect(self.open_uninstaller)
        btn_layout.addWidget(self.clean_btn)
        btn_layout.addWidget(self.uninstall_btn)
        
        main_layout.addLayout(btn_layout)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        # 添加菜单
        self.create_menu()

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
            ("浏览器缓存", True)
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
            ("日志文件", False),
            ("错误报告", True),
            ("DirectX着色器缓存", False),
            ("Delivery优化文件", True)
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
        add_btn = QPushButton("添加路径")
        add_btn.clicked.connect(self.add_custom_path)
        remove_btn = QPushButton("移除选中")
        remove_btn.clicked.connect(self.remove_custom_path)
        
        custom_layout.addWidget(self.path_list)
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

    def create_menu(self):
        """创建菜单栏"""
        menubar = self.menuBar()
        file_menu = menubar.addMenu('文件')
        
        exit_action = QAction('退出', self)
        exit_action.triggered.connect(self.close_app)
        file_menu.addAction(exit_action)
        
        help_menu = menubar.addMenu('帮助')
        about_action = QAction('关于', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def switch_mode(self):
        """切换用户模式"""
        index = self.mode_combo.currentIndex()
        self.stacked_widget.setCurrentIndex(index)

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
        
        tasks = []
        mode = self.mode_combo.currentIndex()
        
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
                            tasks.append((self.clean_directory, [path]))
                    else:
                        tasks.append((self.clean_directory, [paths]))
        
        # 高级模式任务
        else:
            for i, (text, _) in enumerate(self.advanced_checks):
                if self.advanced_checkboxes[i].isChecked():
                    path = self.get_advanced_path(text)
                    tasks.append((self.clean_directory, [path]))
            
            # 添加自定义路径
            for i in range(self.path_list.count()):
                path = self.path_list.item(i).text()
                tasks.append((self.clean_directory, [path]))
        
        if not tasks:
            QMessageBox.warning(self, "警告", "请至少选择一个清理选项")
            return
        
        self.clean_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.status_label.setText("正在准备清理...")
        
        self.worker = CleanerWorker(tasks)
        self.worker.progress.connect(self.progress_bar.setValue)
        self.worker.message.connect(self.status_label.setText)
        self.worker.finished.connect(self.on_clean_finished)
        self.worker.error.connect(self.show_error)
        self.worker.start()

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
                os.path.join(localappdata, 'Microsoft', 'Edge', 'User Data', 'Default', 'Cache')
            ]
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
            "日志文件": os.path.join(windir, 'Logs'),
            "错误报告": os.path.join(programdata, 'Microsoft', 'Windows', 'WER'),
            "DirectX着色器缓存": os.path.join(localappdata, 'D3DSCache'),
            "Delivery优化文件": os.path.join(windir, 'ServiceProfiles', 'NetworkService', 'AppData', 'Local', 'Microsoft', 'Windows', 'DeliveryOptimization')
        }
        return paths.get(option, "")

    def clean_directory(self, path):
        """清理指定目录"""
        if isinstance(path, list):
            for p in path:
                self._clean_single_dir(p)
        else:
            self._clean_single_dir(path)

    def _clean_single_dir(self, path):
        """清理单个目录"""
        print(f"开始清理: {path}")
        if not os.path.exists(path):
            print(f"路径不存在: {path}")
            return
        
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                try:
                    if os.path.isfile(item_path) or os.path.islink(item_path):
                        os.unlink(item_path)
                        print(f"已删除文件: {item_path}")
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        print(f"已删除目录: {item_path}")
                except Exception as e:
                    print(f"删除失败 {item_path}: {e}")
        except Exception as e:
            print(f"清理路径 {path} 时出错: {e}")
    
    def empty_recycle_bin(self):
        """清空回收站"""
        try:
            # 使用send2trash清空回收站
            send2trash.send2trash([])
            print("回收站已清空")
        except Exception as e:
            print(f"清空回收站失败: {e}")
            # 备选方案：使用命令行
            try:
                os.system('cmd /c "rd /s /q C:\\$Recycle.bin"')
                print("使用命令行清空回收站")
            except Exception as ex:
                print(f"命令行清空回收站失败: {ex}")

    def open_uninstaller(self):
        """打开系统卸载程序"""
        try:
            os.system('control appwiz.cpl')
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开卸载程序:\n{str(e)}")

    def on_clean_finished(self):
        """清理完成处理"""
        self.clean_btn.setEnabled(True)
        QMessageBox.information(self, "完成", "清理操作已完成!")
        self.progress_bar.setValue(0)
        self.status_label.setText("就绪")

    def show_error(self, msg):
        """显示错误信息"""
        QMessageBox.critical(self, "错误", msg)
        self.clean_btn.setEnabled(True)

    def show_about(self):
        """显示关于对话框"""
        QMessageBox.about(self, "关于 adsC盘清理大师", 
                         "版本: 1.0\n\n"
                         "一款深度清理C盘的专业工具\n"
                         "支持普通用户和技术人员两种模式\n"
                         "开发者：csdn用户@程序鸠\n"
                         "B站：@qpython前方恐怖预警")

    def close_app(self):
        """关闭应用"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        QApplication.quit()

    def closeEvent(self, event):
        """关闭事件处理"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
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