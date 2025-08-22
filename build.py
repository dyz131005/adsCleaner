# Copyright (c) 2025 dyz131005
# Licensed under the MIT License

import os
import shutil
import sys
import PyInstaller.__main__

def main():
    """构建可执行文件的主函数"""
    print("=" * 50)
    print("adsCleaner 打包工具")
    print("版权所有 (c) 2025 dyz131005")
    print("MIT 许可证 - 详见 LICENSE 文件")
    print("=" * 50)
    
    # 获取当前脚本所在目录
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    
    print(f"\n当前工作目录: {os.getcwd()}")
    
    # 检查图标文件
    icon_path = os.path.join(base_dir, 'pkk.ico')
    if not os.path.exists(icon_path):
        # 如果ICO不存在，尝试使用PNG
        png_path = os.path.join(base_dir, 'pkk.png')
        if os.path.exists(png_path):
            print("\n⚠️ 警告: 未找到ICO图标文件，但存在PNG文件")
            print("请先运行 convert_icon.py 转换图标")
        else:
            print(f"\n❌ 错误: 图标文件未找到: pkk.ico 或 pkk.png")
            print("请确保图标文件位于项目根目录")
        return
    
    # 日志文件处理
    log_path = os.path.join(base_dir, 'newlog.txt')
    if not os.path.exists(log_path):
        print(f"\n⚠️ 警告: 更新日志文件未找到: {log_path}")
        print("请创建")
    
    # 清理之前的构建
    for folder in ['build', 'dist']:
        if os.path.exists(folder):
            print(f"\n⚠️ 清理旧构建: 删除目录 {folder}")
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
                print(f"\n✅ 使用Qt插件路径: {qt_plugin_path}")
                os.environ['QT_PLUGIN_PATH'] = qt_plugin_path
                break
        
        if not qt_plugin_path:
            print("\n⚠️ 警告: PyQt5插件路径未找到，程序可能无法正常运行")
    except ImportError:
        print("\n❌ 错误: PyQt5未安装，请先安装依赖")
        print("运行: pip install -r requirements.txt")
        return
    
    # 添加工具压缩包到打包资源
    tool_files = []
    tool_zips = ["Handle.zip", "PSTools.zip"]
    for zip_name in tool_zips:
        zip_path = os.path.join(base_dir, zip_name)
        if os.path.exists(zip_path):
            print(f"\n✅ 找到工具压缩包: {zip_path}")
            tool_files.append(f'--add-data={zip_path};.')
        else:
            print(f"\n⚠️ 警告: 工具压缩包未找到: {zip_path}")
            print("请确保压缩包位于项目根目录")
    
    # 构建命令
    build_args = [
        '--onefile',
        '--windowed',
        '--name=adsCleaner',
        f'--icon={icon_path}',
        f'--add-data={icon_path};.',
        f'--add-data={log_path};.',  # 添加日志文件
        '--hidden-import=PyQt5.QtCore',
        '--hidden-import=PyQt5.QtGui',
        '--hidden-import=PyQt5.QtWidgets',
        '--exclude-module=PIL',  # 排除PIL模块
        '--exclude-module=Pillow',  # 排除Pillow模块
    ]
    
    # 添加工具文件
    build_args.extend(tool_files)
    
    # 添加主程序
    build_args.append('main.py')
    
    print("\n" + "=" * 50)
    print("开始打包...")
    print("命令参数:", " ".join(build_args))
    print("=" * 50)
    
    try:
        # 执行打包
        PyInstaller.__main__.run(build_args)
        print("\n✅ 构建完成！可执行文件在 dist 目录")
        
        # 显示打包结果位置
        dist_path = os.path.join(base_dir, 'dist', 'adsCleaner.exe')
        if os.path.exists(dist_path):
            print(f"\n程序位置: {os.path.abspath(dist_path)}")
            print("大小:", round(os.path.getsize(dist_path) / (1024 * 1024), 2), "MB")
        else:
            print("\n⚠️ 警告: 未找到生成的可执行文件")
    except Exception as e:
        print(f"\n❌ 打包过程中发生错误: {str(e)}")
        print("可能的原因: ")
        print("1. 路径中包含非ASCII字符（如中文）")
        print("2. 依赖包未正确安装")
        print("3. PyInstaller版本问题")
        print("4. 缺少必要的系统依赖")
        print("\n解决方案建议: ")
        print("- 使用纯英文路径的项目目录")
        print("- 运行: pip install --upgrade -r requirements.txt")
        print("- 检查系统环境变量是否配置正确")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ 未处理的异常: {str(e)}")
        import traceback
        traceback.print_exc()
    
    input("\n按 Enter 键退出...")  # 等待用户查看结果