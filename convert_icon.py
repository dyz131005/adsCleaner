# Copyright (c) 2025 dyz131005
# Licensed under the MIT License

from PIL import Image
import os
import sys

def convert_png_to_ico():
    """将pkk.png转换为pkk.ico"""
    try:
        # 固定输入输出文件名
        input_file = "pkk.png"
        output_file = "pkk.ico"
        
        # 检查输入文件是否存在
        if not os.path.exists(input_file):
            print(f"错误: 输入文件不存在: {input_file}")
            return False
        
        # 使用PIL转换
        img = Image.open(input_file)
        
        # 创建不同尺寸的图标
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        
        # 保存为ICO格式
        img.save(output_file, format="ICO", sizes=sizes)
        print(f"成功将 {input_file} 转换为 {output_file}")
        return True
    except Exception as e:
        print(f"转换图标失败: {e}")
        return False

if __name__ == "__main__":
    if convert_png_to_ico():
        print("图标转换成功!")
        sys.exit(0)
    else:
        print("图标转换失败!")
        sys.exit(1)