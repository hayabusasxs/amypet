#!/usr/bin/env python3
"""
详细解释bbregister变换矩阵计算过程的示例
展示从PET世界坐标到MRI世界坐标的变换是如何计算的
"""

import numpy as np
from typing import Tuple, Dict
import logging

logger = logging.getLogger(__name__)

def simulate_bbregister_transform_calculation():
    """
    模拟bbregister计算PET到MRI世界坐标变换的过程
    这是一个简化的教学示例，展示基本原理
    """
    
    print("🔍 模拟bbregister配准过程")
    print("="*60)
    
    # 1. 原始图像参数
    print("\n1️⃣ 原始图像参数:")
    
    # PET图像参数（低分辨率）
    pet_affine = np.array([
        [-2.0,  0.0,  0.0,   256.0],  # 2mm体素，原点在(256, -290, -195)
        [ 0.0,  2.0,  0.0,  -290.0],  
        [ 0.0,  0.0,  2.5,  -195.0],
        [ 0.0,  0.0,  0.0,     1.0]
    ])
    
    # MRI图像参数（高分辨率）  
    mri_affine = np.array([
        [-1.0,  0.0,  0.0,   128.0],  # 1mm体素，原点在(128, -145, -78)
        [ 0.0,  1.0,  0.0,  -145.0],  
        [ 0.0,  0.0,  1.0,   -78.0],
        [ 0.0,  0.0,  0.0,     1.0]
    ])
    
    print(f"PET仿射矩阵原点: {pet_affine[:3, 3]}")
    print(f"MRI仿射矩阵原点: {mri_affine[:3, 3]}")
    print(f"原点差异: {pet_affine[:3, 3] - mri_affine[:3, 3]}")
    
    # 2. 找到对应的解剖标志点（bbregister的核心）
    print("\n2️⃣ 解剖标志点对应关系:")
    
    # 假设bbregister找到了几个对应的解剖点
    correspondence_points = {
        "前连合": {
            "pet_voxel": [64, 72, 39],      # PET中的体素坐标
            "mri_voxel": [128, 145, 117]    # MRI中对应的体素坐标
        },
        "胼胝体膝": {
            "pet_voxel": [64, 85, 45],
            "mri_voxel": [128, 170, 135] 
        },
        "小脑蚓部": {
            "pet_voxel": [64, 45, 25],
            "mri_voxel": [128, 90, 75]
        }
    }
    
    # 将对应点转换到各自的世界坐标系
    pet_world_points = []
    mri_world_points = []
    
    for landmark, coords in correspondence_points.items():
        # PET体素 → PET世界坐标
        pet_voxel = np.array([*coords["pet_voxel"], 1])
        pet_world = pet_affine @ pet_voxel
        pet_world_points.append(pet_world[:3])
        
        # MRI体素 → MRI世界坐标  
        mri_voxel = np.array([*coords["mri_voxel"], 1])
        mri_world = mri_affine @ mri_voxel
        mri_world_points.append(mri_world[:3])
        
        print(f"{landmark}:")
        print(f"  PET: 体素{coords['pet_voxel']} → 世界坐标{pet_world[:3].round(1)}")
        print(f"  MRI: 体素{coords['mri_voxel']} → 世界坐标{mri_world[:3].round(1)}")
        print(f"  世界坐标差异: {(pet_world[:3] - mri_world[:3]).round(1)}")
    
    # 3. 计算最优变换矩阵（简化的最小二乘法）
    print("\n3️⃣ 计算PET世界坐标到MRI世界坐标的变换:")
    
    # 转换为numpy数组
    pet_points = np.array(pet_world_points)    # N×3，N个PET世界坐标点
    mri_points = np.array(mri_world_points)    # N×3，N个对应的MRI世界坐标点
    
    # 简化版本：假设只有平移变换（实际bbregister还包括旋转和缩放）
    translation = np.mean(mri_points - pet_points, axis=0)
    
    # 构建世界坐标变换矩阵
    world_to_world_transform = np.array([
        [1.0,  0.0,  0.0,  translation[0]],  # 简化：只有平移，无旋转
        [0.0,  1.0,  0.0,  translation[1]],  # 实际bbregister会优化所有参数
        [0.0,  0.0,  1.0,  translation[2]], 
        [0.0,  0.0,  0.0,  1.0]
    ])
    
    print(f"计算得到的世界坐标变换矩阵:")
    print(world_to_world_transform)
    print(f"主要是平移变换: {translation.round(1)} mm")
    
    # 4. 验证变换效果
    print("\n4️⃣ 验证变换效果:")
    
    test_pet_world = pet_world_points[0]  # 取第一个点测试
    test_mri_world = mri_world_points[0]
    
    # 应用变换
    test_pet_homog = np.array([*test_pet_world, 1])
    transformed_world = world_to_world_transform @ test_pet_homog
    
    print(f"测试点变换:")
    print(f"  原始PET世界坐标: {test_pet_world.round(1)}")
    print(f"  变换后坐标: {transformed_world[:3].round(1)}")  
    print(f"  目标MRI世界坐标: {test_mri_world.round(1)}")
    print(f"  变换误差: {(transformed_world[:3] - test_mri_world).round(1)} mm")
    
    return world_to_world_transform

def explain_lta_file_content():
    """
    解释LTA文件中存储的变换信息
    """
    print("\n" + "="*60)
    print("📄 LTA文件内容解析")
    print("="*60)
    
    print("""
LTA文件实际上存储的是复合变换矩阵，它包含了：

1. 变换类型标识:
   type = 0  # LINEAR_VOX_TO_VOX (直接体素到体素)
   type = 1  # LINEAR_RAS_TO_RAS (世界坐标到世界坐标)

2. 变换矩阵:
   如果type=0，存储的是从PET体素直接到MRI体素的复合变换
   如果type=1，存储的是从PET世界坐标到MRI世界坐标的变换

3. 源图像信息 (PET):
   - 图像尺寸: volume = 128 128 64  
   - 体素大小: voxelsize = 2.0 2.0 2.5
   - 坐标轴方向: xras, yras, zras
   - 中心坐标: cras

4. 目标图像信息 (MRI):
   - 相应的MRI图像参数
   
实际使用时，mri_vol2vol读取这些信息，执行完整的变换过程。
    """)
    
    # 展示典型的复合变换计算
    print("\n🔄 复合变换矩阵的计算:")
    print("""
完整的体素到体素变换 = MRI_affine_inverse @ world_transform @ PET_affine

其中:
- PET_affine: PET体素 → PET世界坐标
- world_transform: PET世界坐标 → MRI世界坐标 (bbregister计算的)
- MRI_affine_inverse: MRI世界坐标 → MRI体素坐标

这个复合变换直接将PET体素坐标映射到MRI体素坐标。
    """)

def main():
    """主函数：演示整个变换计算过程"""
    
    print("🎯 bbregister变换矩阵计算详解")
    print("=" * 80)
    
    # 模拟配准过程
    world_transform = simulate_bbregister_transform_calculation()
    
    # 解释LTA文件
    explain_lta_file_content()
    
    print("\n💡 关键要点:")
    print("1. bbregister通过匹配解剖边界找到最优变换参数")
    print("2. 世界坐标变换补偿了两个扫描仪坐标系的差异") 
    print("3. LTA文件可能存储复合变换，直接从体素到体素")
    print("4. mri_vol2vol应用这个变换，统一到MRI坐标系")

if __name__ == "__main__":
    main() 