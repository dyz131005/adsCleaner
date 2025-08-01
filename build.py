import os
import shutil
import PyInstaller.__main__
import sys

def main():
    """构建可执行文件的主函数"""
    # 获取当前脚本所在目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    
    print(f"当前工作目录: {os.getcwd()}")
    
    # 图标处理
    icon_path = os.path.join(base_dir, 'pkk.ico')
    if not os.path.exists(icon_path):
        print(f"错误: 图标文件未找到: {icon_path}")
        print("请确保图标文件位于项目根目录")
        return
    
    # 清理之前的构建
    for folder in ['build', 'dist']:
        if os.path.exists(folder):
            print(f"删除目录: {folder}")
            shutil.rmtree(folder, ignore_errors=True)
    
    # 设置QT插件路径
    try:
        import PyQt5
        pyqt_path = os.path.dirname(PyQt5.__file__)
        candidate_paths = [
            os.path.join(pyqt_path, "Qt5", "plugins"),
            os.path.join(pyqt_path, "Qt", "plugins")
        ]
        
        qt_plugin_path = None
        for path in candidate_paths:
            if os.path.exists(path):
                qt_plugin_path = path
                print(f"使用Qt插件路径: {qt_plugin_path}")
                os.environ['QT_PLUGIN_PATH'] = qt_plugin_path
                break
        
        if not qt_plugin_path:
            print("警告: PyQt5插件路径未找到，程序可能无法正常运行")
    except ImportError:
        print("错误: PyQt5未安装，请先安装依赖")
        print("运行: pip install -r requirements.txt")
        return
    
    # 构建命令
    build_args = [
        '--onefile',
        '--windowed',
        '--name=adsCleaner',
        f'--icon={icon_path}',
        f'--add-data={icon_path};.',
        '--hidden-import=PyQt5.QtCore',
        '--hidden-import=PyQt5.QtGui',
        '--hidden-import=PyQt5.QtWidgets',
        'main.py'
    ]
    
    print("开始打包...")
    print("命令参数:", " ".join(build_args))
    
    try:
        # 执行打包
        PyInstaller.__main__.run(build_args)
        print("\n构建完成！可执行文件在 dist 目录")
    except Exception as e:
        print(f"\n打包过程中发生错误: {str(e)}")
        print("可能的原因: ")
        print("1. 路径中包含非ASCII字符（如中文）")
        print("2. 依赖包未正确安装")
        print("3. PyInstaller版本问题")
        print("\n建议: 使用纯英文路径的项目目录")
        print("运行: pip install -r requirements.txt 确保所有依赖已安装")

if __name__ == "__main__":
    main()
    input("按Enter键退出...")  # 等待用户查看结果