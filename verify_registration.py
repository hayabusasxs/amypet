#!/usr/bin/env python3
"""
验证PET配准质量和体素网格一致性的脚本
用于确定是否可以在mri_gtmpvc中使用--reg-identity选项
"""

import os
import sys
import subprocess
from pathlib import Path
import numpy as np
import nibabel as nib
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def compare_image_headers(img1_path: Path, img2_path: Path) -> dict:
    """
    比较两个NIfTI图像的头文件信息
    
    参数:
        img1_path: 第一个图像路径
        img2_path: 第二个图像路径
        
    返回:
        包含比较结果的字典
    """
    try:
        img1 = nib.load(img1_path)
        img2 = nib.load(img2_path)
        
        # 获取基本信息
        shape1, shape2 = img1.shape, img2.shape
        affine1, affine2 = img1.affine, img2.affine
        pixdim1 = img1.header.get_zooms()
        pixdim2 = img2.header.get_zooms()
        
        # 比较结果
        results = {
            'shapes_match': shape1 == shape2,
            'shape1': shape1,
            'shape2': shape2,
            'affines_match': np.allclose(affine1, affine2, atol=1e-6),
            'affine_diff_max': np.abs(affine1 - affine2).max(),
            'pixdims_match': np.allclose(pixdim1, pixdim2, atol=1e-6),
            'pixdim1': pixdim1,
            'pixdim2': pixdim2,
            'can_use_reg_identity': False
        }
        
        # 判断是否可以使用--reg-identity
        if (results['shapes_match'] and 
            results['affines_match'] and 
            results['pixdims_match']):
            results['can_use_reg_identity'] = True
            
        return results
        
    except Exception as e:
        logger.error(f"❌ 比较图像头文件时出错: {e}")
        return {'error': str(e)}

def verify_patient_registration(subject_id: str, 
                              subjects_dir: str = None,
                              variant_tag: str = "") -> dict:
    """
    验证单个患者的配准质量
    
    参数:
        subject_id: 患者ID
        subjects_dir: FreeSurfer SUBJECTS_DIR
        variant_tag: PET变体标识
        
    返回:
        验证结果字典
    """
    if subjects_dir is None:
        subjects_dir = os.environ.get('SUBJECTS_DIR')
        if not subjects_dir:
            raise ValueError("请设置SUBJECTS_DIR环境变量或提供subjects_dir参数")
    
    subjects_dir = Path(subjects_dir)
    subject_dir = subjects_dir / subject_id
    
    # 构建文件路径
    if variant_tag:
        pet_variant_name = f"{subject_id}_pet{variant_tag}"
        pet_prefix = f"{subject_id}_pet{variant_tag}"
    else:
        pet_variant_name = f"{subject_id}_pet"
        pet_prefix = f"{subject_id}_pet"
    
    # 关键文件路径
    registrated_pet = subject_dir / "pet" / pet_variant_name / "registrated_pet.nii.gz"
    gtmseg_file = subject_dir / "mri" / "gtmseg.mgz"
    lta_file = subject_dir / "pet" / pet_variant_name / "pet2mri.lta"
    
    logger.info(f"🔍 验证患者 {subject_id}{variant_tag} 的配准质量...")
    
    results = {
        'subject_id': subject_id,
        'variant_tag': variant_tag,
        'files_exist': {},
        'registration_quality': {},
        'recommendation': ''
    }
    
    # 检查文件存在性
    files_to_check = {
        'registrated_pet': registrated_pet,
        'gtmseg': gtmseg_file,
        'lta_matrix': lta_file
    }
    
    for name, path in files_to_check.items():
        results['files_exist'][name] = path.exists()
        if not path.exists():
            logger.warning(f"⚠️ 缺少文件: {path}")
    
    # 如果关键文件存在，进行详细验证
    if results['files_exist']['registrated_pet'] and results['files_exist']['gtmseg']:
        # 比较图像头文件
        comparison = compare_image_headers(registrated_pet, gtmseg_file)
        results['registration_quality'] = comparison
        
        # 生成建议
        if comparison.get('can_use_reg_identity', False):
            results['recommendation'] = 'reg_identity'
            logger.info("✅ 推荐使用 --reg-identity")
        elif results['files_exist']['lta_matrix']:
            results['recommendation'] = 'use_lta'
            logger.info("✅ 推荐使用 --reg 配准矩阵文件")
        else:
            results['recommendation'] = 'regheader'
            logger.info("✅ 推荐使用 --regheader")
            
    else:
        results['recommendation'] = 'missing_files'
        logger.error("❌ 缺少必要的文件，无法进行验证")
    
    return results

def print_verification_report(results: dict):
    """
    打印验证报告
    
    参数:
        results: 验证结果字典
    """
    subject_id = results['subject_id']
    variant = results['variant_tag']
    
    print(f"\n{'='*60}")
    print(f"📊 患者 {subject_id}{variant} 配准验证报告")
    print(f"{'='*60}")
    
    # 文件状态
    print(f"\n📁 文件状态:")
    for name, exists in results['files_exist'].items():
        status = "✅ 存在" if exists else "❌ 缺失"
        print(f"   {name}: {status}")
    
    # 配准质量
    if 'error' not in results['registration_quality']:
        reg_qual = results['registration_quality']
        print(f"\n🔬 配准质量分析:")
        
        # 图像尺寸
        shape_status = "✅ 一致" if reg_qual.get('shapes_match', False) else "❌ 不一致"
        print(f"   图像尺寸: {shape_status}")
        print(f"   - 配准PET: {reg_qual.get('shape1', 'N/A')}")
        print(f"   - GTM分割: {reg_qual.get('shape2', 'N/A')}")
        
        # 仿射变换矩阵
        affine_status = "✅ 一致" if reg_qual.get('affines_match', False) else "❌ 不一致"
        print(f"   仿射矩阵: {affine_status}")
        if not reg_qual.get('affines_match', False):
            print(f"   - 最大差异: {reg_qual.get('affine_diff_max', 'N/A'):.6f}")
        
        # 体素尺寸
        pixdim_status = "✅ 一致" if reg_qual.get('pixdims_match', False) else "❌ 不一致"
        print(f"   体素尺寸: {pixdim_status}")
        print(f"   - 配准PET: {reg_qual.get('pixdim1', 'N/A')}")
        print(f"   - GTM分割: {reg_qual.get('pixdim2', 'N/A')}")
    
    # 建议
    print(f"\n💡 mri_gtmpvc 建议:")
    rec = results['recommendation']
    if rec == 'reg_identity':
        print("   ✅ 可以安全使用 --reg-identity")
        print("   理由: 两个图像具有完全一致的体素网格")
    elif rec == 'use_lta':
        print("   ⚠️ 推荐使用 --reg pet2mri.lta")
        print("   理由: 图像网格存在差异，但有精确的配准矩阵")
    elif rec == 'regheader':
        print("   ⚠️ 推荐使用 --regheader")
        print("   理由: 缺少配准矩阵，但图像应在同一空间")
    else:
        print("   ❌ 无法进行配准，请检查缺失的文件")

def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("用法: python verify_registration.py <subject_id> [variant_tag]")
        print("例如: python verify_registration.py 001")
        print("例如: python verify_registration.py 001 -1")
        sys.exit(1)
    
    subject_id = sys.argv[1]
    variant_tag = sys.argv[2] if len(sys.argv) > 2 else ""
    
    try:
        results = verify_patient_registration(subject_id, variant_tag=variant_tag)
        print_verification_report(results)
        
    except Exception as e:
        logger.error(f"❌ 验证过程中出现错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 