#################################################
# Copyright (c) 2025 dyz131005
# Licensed under the MIT License
#################################################

import os
import shutil
import sys
import subprocess
import argparse

def check_and_install_dependencies():
    """检查并安装缺失的依赖"""
    print("🔍 检查依赖...")
    
    # 确定虚拟环境的Python路径
    venv_python = sys.executable
    print(f"🐍 使用Python: {venv_python}")
    
    # 检查必要的模块
    required_modules = {
        'PyInstaller': 'pyinstaller',
        'PyQt5': 'pyqt5',
        'psutil': 'psutil', 
        'send2trash': 'send2trash',
        'win32com': 'pywin32'
    }
    
    missing_modules = []
    
    for import_name, package_name in required_modules.items():
        try:
            if import_name == 'win32com':
                __import__('win32com.client')
            else:
                __import__(import_name)
            print(f"✅ {import_name} 已安装")
        except ImportError:
            print(f"❌ {import_name} 未安装")
            missing_modules.append(package_name)
    
    if missing_modules:
        print(f"\n⚠️ 需要安装 {len(missing_modules)} 个模块")
        install_cmd = [venv_python, "-m", "pip", "install"] + missing_modules
        print(f"🔧 安装命令: {' '.join(install_cmd)}")
        
        try:
            result = subprocess.run(install_cmd, check=True, capture_output=True, text=True)
            print("✅ 依赖安装成功")
            return True
        except subprocess.CalledProcessError as e:
            print(f"❌ 依赖安装失败: {e}")
            if e.stderr:
                print(f"错误信息: {e.stderr}")
            return False
    else:
        print("✅ 所有依赖已安装")
        return True

def build_with_pyinstaller(console=False):
    """使用PyInstaller构建"""
    try:
        # 使用虚拟环境中的PyInstaller
        venv_python = sys.executable
        
        # 创建版本信息文件
        version_info = '''
# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=(1, 4, 0, 0),
    prodvers=(1, 4, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '080404b0',
          [StringStruct('CompanyName', 'dyz131005'),
           StringStruct('FileDescription', 'adsC盘清理大师 - 专业的Windows磁盘清理工具'),
           StringStruct('FileVersion', '1.4.0.0'),
           StringStruct('InternalName', 'adsCleaner'),
           StringStruct('LegalCopyright', 'Copyright Ⓒ 2025 dyz131005. Licensed under MIT License.'),
           StringStruct('OriginalFilename', 'adsCleaner.exe'),
           StringStruct('ProductName', 'adsCleaner Disk Cleaner'),
           StringStruct('ProductVersion', '1.4.0.0')])
      ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
'''
        with open('version_info.txt', 'w', encoding='utf-8') as f:
            f.write(version_info)
        
        # 构建参数
        build_args = [
            '--onefile',
            '--name=adsCleaner',
            '--icon=pkk.ico',
            '--version-file=version_info.txt',
            '--add-data=pkk.ico;.',
            '--add-data=newlog.txt;.',
            '--add-data=eye.ico;.',
        ]
        
        # 根据参数选择窗口模式
        if console:
            build_args.append('--console')
            print("🔧 构建为控制台程序")
        else:
            build_args.append('--windowed')
            print("🔧 构建为窗口程序")
        
        # 添加工具文件
        tool_zips = ["Handle.zip", "PSTools.zip"]
        for zip_name in tool_zips:
            if os.path.exists(zip_name):
                build_args.append(f'--add-data={zip_name};.')
        
        build_args.append('main.py')
        
        # 直接调用PyInstaller模块
        cmd = [venv_python, "-m", "PyInstaller"] + build_args
        print(f"🔧 执行命令: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, check=True)
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ PyInstaller构建失败: {e}")
        return False
    except Exception as e:
        print(f"❌ 构建过程中出错: {e}")
        return False

def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='adsCleaner 构建工具')
    parser.add_argument('--console', action='store_true', help='构建为控制台程序（默认是窗口程序）')
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    
    print("=" * 60)
    print("adsCleaner 构建工具")
    print("版本 1.4 - 虚拟环境专用版")
    print("=" * 60)
    
    # 检查虚拟环境
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        print("✅ 检测到虚拟环境")
        print(f"🐍 Python路径: {sys.executable}")
        print(f"📁 工作目录: {os.getcwd()}")
    else:
        print("⚠️ 未检测到虚拟环境，但继续执行")
    
    # 检查必要文件
    required_files = ['pkk.ico', 'newlog.txt', 'main.py', 'eye.ico']
    for file in required_files:
        if os.path.exists(file):
            print(f"✅ {file} 存在")
        else:
            print(f"❌ {file} 缺失!")
            return
    
    # 检查并安装依赖
    if not check_and_install_dependencies():
        print("❌ 依赖检查失败")
        return
    
    # 清理旧构建
    for folder in ['build', 'dist']:
        if os.path.exists(folder):
            print(f"🗑️ 删除旧目录: {folder}")
            shutil.rmtree(folder, ignore_errors=True)
    
    # 构建
    print("\n🚀 开始构建...")
    if build_with_pyinstaller(console=args.console):
        # 清理临时文件
        for temp_file in ['version_info.txt']:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        
        exe_path = os.path.join('dist', 'adsCleaner.exe')
        if os.path.exists(exe_path):
            print(f"\n✅ 构建成功!")
            print(f"📦 生成文件: {exe_path}")
            print(f"💾 文件大小: {os.path.getsize(exe_path) / (1024*1024):.2f} MB")
            print("\n🔍 验证版本信息:")
            print("   右键点击 dist\\adsCleaner.exe → 属性 → 详细信息")
            print("   版本号应为: 1.4.0.0")
            
            # 显示使用说明
            if args.console:
                print("\n💡 提示: 此版本为控制台程序，运行时将显示命令行窗口")
            else:
                print("\n💡 提示: 此版本为窗口程序，运行时不会显示命令行窗口")
                
        else:
            print("❌ 构建完成但未找到生成的文件")
    else:
        print("❌ 构建失败")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
    
    input("\n按 Enter 键退出...")