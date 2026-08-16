# modules/pet_pvc_processor.py
"""
PET 部分容积校正处理模块

## 📋 功能说明
本模块实现PET图像的部分容积校正（Partial Volume Correction, PVC）处理，
主要包括GTM分割和mri_gtmpvc校正两个步骤。

## 🔄 处理流程

### 步骤1: GTM分割 (gtmseg)
- 对MR图像执行GTM分割
- 生成gtmseg.mgz文件用于后续PVC处理

### 步骤2: PVC校正 (mri_gtmpvc)
- 对每个PET变体执行PVC校正
- 支持多个PSF值（2，3，4，5，6）
- 生成校正后的统计结果

## 📁 输入要求
- FreeSurfer重建完成的受试者数据
- 已配准的PET图像（*.mgz格式）
- 对应的配准矩阵文件（pet2mri.lta）

## 📤 输出结果
- 每个变体和PSF组合的PVC校正结果
- 存储在 {subject}/pet_pvc/{variant}/gtmpvc_psf{N}.output/ 目录中
"""

import os
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any, Callable
import concurrent.futures
from tqdm import tqdm
import time
import sys # 用于日志处理器恢复

from . import utils
import config

# 自定义日志处理器，将日志通过tqdm.write输出
class TqdmLoggingHandler(logging.Handler):
    """一个将日志记录重定向到tqdm.write()的处理器，以避免与进度条冲突。"""
    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg, file=sys.stdout)
            self.flush()
        except Exception:
            self.handleError(record)

logger = logging.getLogger(__name__)

# 常量定义
PSF_VALUES = [2, 3, 4, 5, 6]  # PSF值列表
PVC_DIR_NAME = 'pet_pvc'      # PVC输出目录名
PET_DIR_NAME = 'pet'          # PET数据目录名
MRI_DIR_NAME = 'mri'          # MRI数据目录名
GTMSEG_FILE = 'gtmseg.mgz'    # GTM分割文件名
REG_MATRIX_FILE = 'pet2mri.lta'  # 配准矩阵文件名


def check_prerequisites(subject_id: str) -> Tuple[bool, str]:
    """
    检查PVC处理的先决条件
    
    参数:
        subject_id: 受试者ID
        
    返回:
        (是否满足条件, 错误信息)
    """
    subject_id = utils.format_patient_id(subject_id)
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    
    # 检查FreeSurfer重建目录
    mri_dir = subject_dir / MRI_DIR_NAME
    if not mri_dir.exists():
        return False, f"FreeSurfer重建目录不存在: {mri_dir}"
    
    # 检查PET目录
    pet_dir = subject_dir / PET_DIR_NAME
    if not pet_dir.exists():
        return False, f"PET目录不存在: {pet_dir}"
    
    # 检查是否有PET变体
    pet_variants = find_pet_variants(subject_id)
    if not pet_variants:
        return False, f"未找到PET变体数据: {pet_dir}"
    
    return True, ""

def find_pet_variants(subject_id: str) -> List[str]:
    """
    查找受试者的所有PET变体
    
    参数:
        subject_id: 受试者ID
        
    返回:
        PET变体列表，例如：['001_pet-zte', '001_pet-1-2-3']
    """
    subject_id = utils.format_patient_id(subject_id)
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    pet_dir = subject_dir / PET_DIR_NAME
    
    if not pet_dir.exists():
        return []
    
    variants = []
    for item in pet_dir.iterdir():
        if item.is_dir() and item.name.startswith(f"{subject_id}_pet"):
            # 检查该变体目录中是否包含必需文件
            pet_file = item / f"{item.name}.mgz"
            reg_file = item / REG_MATRIX_FILE
            
            if pet_file.exists() and reg_file.exists():
                variants.append(item.name)
            else:
                logger.warning(f"⚠️ 变体 {item.name} 缺少必需文件: "
                             f"PET文件={pet_file.exists()}, 配准文件={reg_file.exists()}")
    
    return sorted(variants)

def run_gtmseg(subject_id: str) -> Tuple[bool, str]:
    """
    对MR图像执行GTM分割
    
    参数:
        subject_id: 受试者ID
        
    返回:
        (成功标志, 错误信息)
    """
    subject_id = utils.format_patient_id(subject_id)
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    gtmseg_file = subject_dir / MRI_DIR_NAME / GTMSEG_FILE
    
    # 检查是否已存在gtmseg结果
    if gtmseg_file.exists():
        return True, "已存在"
    
    # 设置环境变量
    env = os.environ.copy()
    env['SUBJECTS_DIR'] = str(config.SUBJECTS_DIR)
    
    # 构建gtmseg命令
    cmd = ['gtmseg', '--s', subject_id, '--xcerseg']
    
    try:
        # 执行gtmseg命令
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=1800  # 30分钟超时
        )
        
        success = False
        error_msg = ""
        
        if result.returncode == 0:
            # 验证输出文件
            if gtmseg_file.exists():
                success = True
            else:
                error_msg = f"GTM分割命令执行成功，但未找到输出文件: {gtmseg_file}"
        else:
            error_msg = f"GTM分割失败 (返回码: {result.returncode})\n标准错误: {result.stderr}"
            
        # 显示错误信息（如果有）
        if not success and error_msg:
            logger.error(f"❌ GTM分割失败 - {subject_id}: {error_msg}")
            
        return success, error_msg
            
    except subprocess.TimeoutExpired:
        error_msg = f"GTM分割超时（>30分钟）: {subject_id}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"执行GTM分割时发生异常: {e}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg

def run_mri_gtmpvc(subject_id: str, variant: str, psf: int) -> Tuple[bool, str]:
    """
    对指定变体和PSF值执行mri_gtmpvc
    
    参数:
        subject_id: 受试者ID
        variant: PET变体名称，例如：'001_pet-zte'
        psf: PSF值
        
    返回:
        (成功标志, 错误信息)
    """
    subject_id = utils.format_patient_id(subject_id)
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    
    # 构建文件路径
    pet_file = subject_dir / PET_DIR_NAME / variant / f"{variant}.mgz"
    reg_file = subject_dir / PET_DIR_NAME / variant / REG_MATRIX_FILE
    seg_file = subject_dir / MRI_DIR_NAME / GTMSEG_FILE
    
    # 创建输出目录
    pvc_dir = subject_dir / PVC_DIR_NAME / variant
    output_dir = pvc_dir / f"gtmpvc_psf{psf}.output"
    
    # 检查输出目录是否已存在且包含结果
    gtm_stats_file = output_dir / "gtm.stats.dat"
    if gtm_stats_file.exists():
        return True, "已存在"
    
    # 创建必要的目录
    pvc_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 验证输入文件
    if not pet_file.exists():
        error_msg = f"PET文件不存在: {pet_file}"
        logger.error(f"❌ PVC处理失败 - {subject_id} {variant} PSF{psf}: {error_msg}")
        return False, error_msg
    
    if not reg_file.exists():
        error_msg = f"配准文件不存在: {reg_file}"
        logger.error(f"❌ PVC处理失败 - {subject_id} {variant} PSF{psf}: {error_msg}")
        return False, error_msg
    
    if not seg_file.exists():
        error_msg = f"GTM分割文件不存在: {seg_file}"
        logger.error(f"❌ PVC处理失败 - {subject_id} {variant} PSF{psf}: {error_msg}")
        return False, error_msg
    
    # 设置环境变量
    env = os.environ.copy()
    env['SUBJECTS_DIR'] = str(config.SUBJECTS_DIR)
    
    # 构建mri_gtmpvc命令
    cmd = [
        'mri_gtmpvc',
        '--i', str(pet_file),
        '--reg', str(reg_file),
        '--psf', str(psf),
        '--seg', str(seg_file),
        '--default-seg-merge',
        '--auto-mask', '1', '.01',
        '--mgx', '.01',
        '--o', str(output_dir),
        '--no-rescale'
    ]
    
    try:
        # 执行mri_gtmpvc命令
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=3600  # 60分钟超时
        )
        
        success = False
        error_msg = ""
        
        if result.returncode == 0:
            # 验证输出文件
            if gtm_stats_file.exists():
                success = True
            else:
                error_msg = f"PVC命令执行成功，但未找到统计文件: {gtm_stats_file}"
        else:
            error_msg = f"PVC处理失败 (返回码: {result.returncode})\n标准错误: {result.stderr}"
            
        # 显示错误信息（如果有）
        if not success and error_msg:
            logger.error(f"❌ PVC处理失败 - {subject_id} {variant} PSF{psf}: {error_msg}")
            
        return success, error_msg
            
    except subprocess.TimeoutExpired:
        error_msg = f"PVC处理超时（>60分钟）: 受试者={subject_id}, 变体={variant}, PSF={psf}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"执行PVC处理时发生异常: {e}"
        logger.error(f"❌ {error_msg}")
        return False, error_msg

def pvc_processor_main(patient_ids: List[str], max_workers: int = 4) -> Dict[str, Any]:
    """
    PVC处理模块主函数 - 采用扁平化并行结构

    处理流程:
    1. 先决条件检查 (串行)
    2. GTM分割 (并行)
    3. PVC校正 (并行)

    参数:
        patient_ids: 患者ID列表
        max_workers: 最大并行处理数
        
    返回:
        处理结果字典
    """
    logger.info(f"🎯 启动PVC处理模块，处理 {len(patient_ids)} 个受试者")
    logger.info(f"  - 最大并行数: {max_workers}")

    patient_ids = [utils.format_patient_id(pid) for pid in patient_ids]
    total_subjects = len(patient_ids)
    
    # 最终结果存储
    results = {
        pid: {
            'subject_id': pid, 'success': False, 'gtmseg_success': False,
            'prereq_ok': False, 'pvc_tasks_total': 0, 'pvc_tasks_success': 0,
            'errors': []
        } for pid in patient_ids
    }

    # 设置日志处理器以配合tqdm
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers
    tqdm_handler = TqdmLoggingHandler()
    root_logger.handlers = [tqdm_handler]

    try:
        # --- 阶段1: 先决条件检查 ---
        subjects_for_gtm = []
        logger.info("--- 阶段1: 先决条件检查 ---")
        with tqdm(total=total_subjects, desc="[1/3] 🔍 检查先决条件", unit="受试者", ncols=120) as pbar:
            for patient_id in patient_ids:
                prereq_ok, error_msg = check_prerequisites(patient_id)
                results[patient_id]['prereq_ok'] = prereq_ok
                if prereq_ok:
                    subjects_for_gtm.append(patient_id)
                else:
                    error_message = f"先决条件检查失败: {error_msg}"
                    logger.error(f"❌ 受试者 {patient_id} - {error_message}")
                    results[patient_id]['errors'].append(error_message)
                pbar.update(1)

        if not subjects_for_gtm:
            logger.warning("⚠️ 所有受试者均未通过先决条件检查，处理中止。")
            return results

        # --- 阶段2: GTM分割 ---
        subjects_for_pvc = []
        logger.info("--- 阶段2: GTM分割 ---")
        with tqdm(total=len(subjects_for_gtm), desc="[2/3] 🧠 GTM分割", unit="受试者", ncols=120) as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_patient = {
                    executor.submit(run_gtmseg, patient_id): patient_id
                    for patient_id in subjects_for_gtm
                }
                
                for future in concurrent.futures.as_completed(future_to_patient):
                    patient_id = future_to_patient[future]
                    try:
                        gtm_success, gtm_error = future.result()
                        results[patient_id]['gtmseg_success'] = gtm_success
                        if gtm_success:
                            if gtm_error != "已存在":
                                logger.info(f"✅ GTM分割成功 - {patient_id}")
                            subjects_for_pvc.append(patient_id)
                        else:
                            error_message = f"GTM分割失败: {gtm_error}"
                            # run_gtmseg内部已经记录了错误，这里不再重复记录
                            results[patient_id]['errors'].append(error_message)
                    except Exception as e:
                        error_message = f"GTM分割时发生致命异常: {e}"
                        logger.error(f"❌ 受试者 {patient_id} - {error_message}")
                        results[patient_id]['errors'].append(error_message)
                        results[patient_id]['gtmseg_success'] = False
                    pbar.update(1)
        
        if not subjects_for_pvc:
            logger.warning("⚠️ 所有受试者GTM分割均失败，PVC处理中止。")
            return results

        # --- 阶段3: PVC校正 ---
        logger.info("--- 阶段3: PVC校正 ---")
        # 准备所有PVC任务
        pvc_tasks = []
        for patient_id in subjects_for_pvc:
            variants = find_pet_variants(patient_id)
            if not variants:
                error_message = "GTM分割成功但未找到有效的PET变体"
                logger.warning(f"⚠️ 受试者 {patient_id} - {error_message}")
                results[patient_id]['errors'].append(error_message)
                continue
            
            results[patient_id]['pvc_tasks_total'] = len(variants) * len(PSF_VALUES)
            for variant in variants:
                for psf in PSF_VALUES:
                    pvc_tasks.append((patient_id, variant, psf))

        if not pvc_tasks:
            logger.warning("⚠️ 未能生成任何PVC任务，处理中止。")
            return results
            
        # 执行PVC任务
        with tqdm(total=len(pvc_tasks), desc="[3/3] ⚙️ PVC校正", unit="任务", ncols=120) as pbar:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_task = {
                    executor.submit(run_mri_gtmpvc, pid, var, psf): (pid, var, psf)
                    for pid, var, psf in pvc_tasks
                }

                for future in concurrent.futures.as_completed(future_to_task):
                    patient_id, variant, psf = future_to_task[future]
                    try:
                        pvc_success, pvc_error = future.result()
                        if pvc_success:
                            results[patient_id]['pvc_tasks_success'] += 1
                        else:
                            error_message = f"变体 {variant} PSF {psf} 失败: {pvc_error}"
                            # run_mri_gtmpvc 内部已经记录了详细错误日志
                            results[patient_id]['errors'].append(error_message)
                    except Exception as e:
                        error_message = f"变体 {variant} PSF {psf} 执行异常: {e}"
                        logger.error(f"❌ 受试者 {patient_id} - {error_message}")
                        results[patient_id]['errors'].append(error_message)
                    pbar.update(1)

    finally:
        # 恢复原始的日志处理器
        root_logger.handlers = original_handlers
        print() # 确保光标换行

    # --- 总结 ---
    successful_patients = 0
    total_pvc_tasks_overall = 0
    successful_pvc_tasks_overall = 0

    for pid, res in results.items():
        # 如果先决条件不满足或GTM失败，则整体失败
        if not res['prereq_ok'] or not res['gtmseg_success']:
            res['success'] = False
        else:
            # 否则，成功取决于PVC任务是否全部成功，且必须有任务
            is_successful = res['pvc_tasks_success'] == res['pvc_tasks_total']
            has_tasks = res['pvc_tasks_total'] > 0
            res['success'] = is_successful and has_tasks
        
        if res['success']:
            successful_patients += 1
        
        total_pvc_tasks_overall += res['pvc_tasks_total']
        successful_pvc_tasks_overall += res['pvc_tasks_success']

    logger.info(f"📊 PVC处理总结:")
    logger.info(f"  - 受试者成功率: {successful_patients}/{total_subjects} ({successful_patients/total_subjects*100:.1f}%)")
    if total_pvc_tasks_overall > 0:
        pvc_success_rate = successful_pvc_tasks_overall / total_pvc_tasks_overall * 100
        logger.info(f"  - PVC任务成功率: {successful_pvc_tasks_overall}/{total_pvc_tasks_overall} ({pvc_success_rate:.1f}%)")
    
    logger.info(f"🏁 PVC处理模块完成")
    
    return results

# 兼容性函数，供main.py调用
def process_pvc_for_patients(patient_ids: List[str], max_workers: int = 4) -> Dict[str, Any]:
    """
    为患者列表执行PVC处理（主入口）
    
    参数:
        patient_ids: 患者ID列表
        max_workers: 最大并行处理数
        
    返回:
        处理结果字典
    """
    return pvc_processor_main(patient_ids, max_workers) 