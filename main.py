#!/usr/bin/env python3
# main.py

import os
import sys
import argparse
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable, Union
from datetime import datetime

from modules import utils
from modules import dcm_converter
from modules import header_extractor
from modules import recon_processor
from modules import registration
from modules import mask_processor
from modules import suvr_calculator
from modules import pvc_suvr_calculator
from modules import directory_renamer
from modules import info_get
from modules import delete
from modules import check
from modules import recon_status
from modules import pet_pvc_processor
from modules import clear

import config

# 常量定义
VALID_STEPS = {
    'rename': '目录重命名',
    'convert': 'DICOM转换',
    'header': 'Header提取',
    'info': '患者信息获取',
    'recon': 'FreeSurfer重建',
    'recon_sta': 'FreeSurfer状态检查',
    'registrate': '图像配准',
    'mask': '掩膜制作',
    'suvr': 'SUVR计算',
    'pvc': 'PET部分容积校正',
    'pvc_suvr': 'PVC校正SUVR计算',
    'delete': '文件删除',
    'check': '结果检查',
#     参数 (长)	参数 (短)	描述
# --segmentation-check	-sc	检查FreeSurfer的分割和区域划分结果。
# --registration-check	-rc	检查PET到MR的配准结果。
# --mask-check	-mc	检查基于配准结果生成的掩膜（Mask）是否正确。
# --info-check	-ic	检查患者信息的一致性。
# --all-check	-ac	进行全面检查，包含以上所有内容以及PET影像。
# 如：    python main.py -i 001 -rc
    'clear': '临时文件清理'
}

VALID_MODALITIES = ['mr', 'pet', 'both']
DEFAULT_MAX_WORKERS = 10

def setup_environment() -> logging.Logger:
    """设置运行环境和日志系统"""
    # 确保目录存在
    for directory in [config.LOG_DIR, config.MR_DIR, config.PET_DIR, config.RECON_DIR]:
        os.makedirs(directory, exist_ok=True)
    
    # 设置日志
    utils.setup_logging(config.LOG_LEVEL)
    logger = logging.getLogger('main')
    
    # 记录启动信息
    logger.info("="*80)
    logger.info("🚀 AMYPET处理系统启动")
    logger.info(f"配置信息: ROOT_DIR={config.ROOT_DIR}")
    logger.info(f"FreeSurfer: {config.FREESURFER_HOME}")
    logger.info(f"DCM2NIIX: {config.DCM2NIIX_PATH}")
    logger.info("="*80)
    
    return logger

def parse_arguments() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='AMYPET处理系统')
    
    # 患者范围选项（互斥）
    patient_group = parser.add_mutually_exclusive_group(required=True)
    patient_group.add_argument('-r', '--range', type=str, 
                              help='患者范围，例如"1-5"表示处理编号1到5的患者')
    patient_group.add_argument('-i', '--ids', type=str, 
                              help='患者ID列表，例如"1,3,5"表示处理编号1,3,5的患者')
    
    # 处理步骤选项
    valid_steps_help = ", ".join(f"{k}({v})" for k, v in VALID_STEPS.items())
    parser.add_argument('-s', '--steps', type=str, default='all',
                        help=f'要执行的处理步骤，使用逗号分隔，可选项: {valid_steps_help}, all '
                             f'(all不包含delete和check步骤，delete默认删除所有文件，可用--keep-nifti参数保留.nii.gz文件)')
    
    # 模态选项
    parser.add_argument('-m', '--modality', type=str, default='both', choices=VALID_MODALITIES,
                       help='处理的模态，可选项: mr,pet,both')
    
    # 并行处理选项
    parser.add_argument('-w', '--workers', type=int, default=DEFAULT_MAX_WORKERS,
                       help=f'最大并行处理数，默认为{DEFAULT_MAX_WORKERS}')
    
    # FreeSurfer特有选项
    parser.add_argument('-f', '--fs-flags', type=str, default='',
                       help='传递给FreeSurfer recon-all的额外标志，使用空格分隔')
    
    # 其他选项
    parser.add_argument('--force', action='store_true',
                       help='强制重新执行处理步骤，即使结果已存在')
    parser.add_argument('--no-delete-confirm', action='store_true',
                       help='删除header时不需要确认')
    parser.add_argument('--keep-nifti', action='store_true',
                       help='删除文件时保留.nii.gz文件')
    
    # 检查结果选项 (直接使用简短选项，方便命令行输入)
    check_group = parser.add_argument_group('结果检查选项')
    check_group.add_argument('-sc', '--segmentation-check', action='store_true',
                           help='检查分割和区域划分结果')
    check_group.add_argument('-rc', '--registration-check', action='store_true',
                           help='检查配准结果')
    check_group.add_argument('-mc', '--mask-check', action='store_true',
                           help='检查掩膜制作结果')
    check_group.add_argument('-ac', '--all-check', action='store_true',
                           help='全面检查（包括分割、配准、掩膜和PET影像）')
    
    return parser.parse_args()

def get_patient_list(args: argparse.Namespace) -> List[str]:
    """从参数中解析患者ID列表"""
    if args.range:
        return utils.parse_patient_range(args.range)
    elif args.ids:
        return [utils.format_patient_id(pid) for pid in args.ids.split(',')]
    return []

def _get_step_function(step: str) -> Callable:
    """获取处理步骤对应的函数"""
    step_functions = {
        'rename': run_rename_step,
        'convert': run_convert_step,
        'header': run_header_step,
        'info': run_info_step,
        'recon': run_recon_step,
        'recon_sta': run_recon_status_step,
        'registrate': run_registration_step,
        'mask': run_mask_step,
        'suvr': run_suvr_step,
        'delete': run_delete_step,
        'check': run_check_step,
        'clear': run_clear_step
    }
    return step_functions.get(step)

def _validate_steps(steps: List[str]) -> List[str]:
    """验证步骤名称，返回有效的步骤列表"""
    valid_steps = []
    for step in steps:
        if step in VALID_STEPS or step == 'all':
            valid_steps.append(step)
        else:
            logging.getLogger('main').warning(f"⚠️ 忽略无效的处理步骤: {step}")
    return valid_steps

def run_convert_step(patient_ids: List[str], modality: str, max_workers: int, logger: logging.Logger) -> Dict:
    """运行DICOM转换步骤"""
    logger.info(f"开始执行DICOM转换步骤，患者: {len(patient_ids)}个，模态: {modality}")
    
    results = dcm_converter.convert_patient_ids(
        patient_ids, 
        modality=modality,
        max_workers=max_workers
    )
    
    # 报告结果
    mr_success = sum(1 for r in results.values() if r.get('mr_success', False))
    pet_success = sum(1 for r in results.values() if r.get('pet_success', False))
    
    if modality in ['mr', 'both']:
        logger.info(f"MR转换结果: {mr_success}/{len(patient_ids)} 成功")
    
    if modality in ['pet', 'both']:
        logger.info(f"PET转换结果: {pet_success}/{len(patient_ids)} 成功")
    
    return results

def run_header_step(patient_ids: List[str], modality: str, max_workers: int, logger: logging.Logger) -> Dict:
    """运行header提取步骤"""
    logger.info(f"开始执行header提取步骤，患者: {len(patient_ids)}个，模态: {modality}")
    
    results = header_extractor.extract_headers_from_patient_ids(
        patient_ids,
        modality=modality,
        max_workers=max_workers
    )
    
    # 报告结果
    mr_success = sum(1 for r in results.values() 
                  if 'mr' in r and r['mr'].get('dcm_header_success', False) and r['mr'].get('nifti_header_success', False))
    
    pet_success = 0
    for r in results.values():
        if 'pet' in r and isinstance(r['pet'], dict):
            dcm_success_any = any(s for s in r['pet'].get('dcm_header_success', {}).values() if isinstance(s, bool) and s)
            nifti_success_any = any(s for s in r['pet'].get('nifti_header_success', {}).values() if isinstance(s, bool) and s)
            # 只要有DICOM或NIfTI header提取成功就算成功（适应没有原始DICOM的情况）
            if dcm_success_any or nifti_success_any:
                pet_success += 1
    
    if modality in ['mr', 'both']:
        logger.info(f"MR header提取结果: {mr_success}/{len(patient_ids)} 成功")
    
    if modality in ['pet', 'both']:
        logger.info(f"PET header提取结果: {pet_success}/{len(patient_ids)} 成功")
    
    return results

def run_info_step(patient_ids: List[str], logger: logging.Logger) -> Dict:
    """运行信息获取步骤"""
    logger.info(f"开始执行患者信息获取步骤，患者: {len(patient_ids)}个")
    
    # 调用info_get模块的功能
    results = info_get.get_patient_info_for_ids(patient_ids)
    
    # 报告结果
    success_count = sum(1 for success in results.values() if success)
    logger.info(f"信息获取结果: {success_count}/{len(patient_ids)} 成功")
    
    return results

def run_recon_step(patient_ids: List[str], fs_flags: List[str], max_workers: int, logger: logging.Logger) -> Dict:
    """运行FreeSurfer重建步骤"""
    logger.info(f"开始执行FreeSurfer重建步骤，患者: {len(patient_ids)}个")
    
    # 准备subject_info字典
    subject_info = {}
    for pid in patient_ids:
        subj_dir = config.MR_DIR / pid
        mr_nifti = subj_dir / f"{pid}_mr.nii.gz"
        
        if not mr_nifti.exists():
            logger.warning(f"⚠️ 患者 {pid} 的MR NIfTI文件不存在，跳过")
            continue
            
        subject_info[pid] = mr_nifti
    
    if not subject_info:
        logger.error("❌ 没有找到任何有效的MR NIfTI文件，无法执行FreeSurfer重建")
        return {}
    
    logger.info(f"找到 {len(subject_info)} 个有效患者的MR数据，开始执行FreeSurfer重建")
    
    # 执行重建
    results = recon_processor.run_recon_all_parallel(
        subject_info,
        additional_flags=fs_flags,
        max_workers=max_workers
    )
    
    # 报告结果
    success_count = sum(1 for success in results.values() if success)
    logger.info(f"FreeSurfer重建结果: {success_count}/{len(subject_info)} 成功")
    
    return results

def run_registration_step(patient_ids: List[str], max_workers: int, logger: logging.Logger) -> Dict:
    """运行图像配准步骤"""
    logger.info(f"开始执行图像配准步骤，患者: {len(patient_ids)}个")
    
    # 准备配准参数 - 使用配置文件中的默认设置
    from modules.registration import DEFAULT_REG_METHOD, DEFAULT_INTERP, DEFAULT_INIT
    reg_params = {
        'method': DEFAULT_REG_METHOD,
        'interp': DEFAULT_INTERP,
        'init': DEFAULT_INIT
    }
    
    # 调用registration模块的功能
    results = registration.registrate_patient_ids(
        patient_ids=patient_ids,
        max_workers=max_workers,
        reg_params=reg_params
    )
    
    # 报告结果
    success_count = sum(1 for r in results.values() if r.get('success', False))
    logger.info(f"图像配准结果: {success_count}/{len(patient_ids)} 成功")
    
    return results

def run_mask_step(patient_ids: List[str], max_workers: int, logger: logging.Logger) -> Dict:
    """运行掩膜制作步骤"""
    logger.info(f"开始执行掩膜制作步骤，患者: {len(patient_ids)}个")
    
    # 调用mask_processor模块的功能
    results = mask_processor.create_masks_for_patients(
        patient_ids=patient_ids,
        max_workers=max_workers
    )
    
    # 报告结果
    success_count = sum(1 for pid, r in results.items() if 'error' not in r or r['error'] is not False)
    logger.info(f"掩膜制作结果: {success_count}/{len(patient_ids)} 成功")
    
    return results

def run_suvr_step(patient_ids: List[str], max_workers: int = 8, logger: logging.Logger = None) -> Dict:
    """运行SUVr计算步骤"""
    logger.info(f"开始执行SUVr计算步骤，患者: {len(patient_ids)}个")
    
    # 调用suvr_calculator模块的功能
    results = suvr_calculator.calculate_suvr_for_patients(
        patient_ids=patient_ids,
        max_workers=max_workers
    )
    
    # 统计成功率
    total_variants = 0
    success_variants = 0
    
    for patient_results in results.values():
        for variant_result in patient_results.values():
            total_variants += 1
            if variant_result.get('success', False):
                success_variants += 1
    
    logger.info(f"SUVr计算结果: {success_variants}/{total_variants} 个变体成功")
    
    return results

def run_pvc_step(patient_ids: List[str], max_workers: int, logger: logging.Logger) -> Dict:
    """运行PET部分容积校正步骤"""
    logger.info(f"开始执行PET部分容积校正步骤，患者: {len(patient_ids)}个")
    
    # 调用pet_pvc_processor模块的功能
    results = pet_pvc_processor.process_pvc_for_patients(
        patient_ids=patient_ids,
        max_workers=max_workers
    )
    
    # 统计成功率
    total_patients = len(patient_ids)
    successful_patients = sum(1 for r in results.values() if r.get('success', False))
    total_pvc_tasks = sum(r.get('total_pvc_tasks', 0) for r in results.values())
    successful_pvc_tasks = sum(r.get('successful_pvc_tasks', 0) for r in results.values())
    
    logger.info(f"PVC处理结果: {successful_patients}/{total_patients} 个受试者成功")
    logger.info(f"PVC任务结果: {successful_pvc_tasks}/{total_pvc_tasks} 个任务成功")
    
    return results

def run_pvc_suvr_step(patient_ids: List[str], max_workers: int, logger: logging.Logger) -> Dict:
    """运行PVC校正SUVR计算步骤"""
    logger.info(f"开始执行PVC校正SUVR计算步骤，患者: {len(patient_ids)}个")
    
    try:
        # 调用PVC SUVR计算模块
        from modules.pvc_suvr_calculator import calculate_pvc_suvr_for_patients
        results = calculate_pvc_suvr_for_patients(patient_ids, max_workers)
        
        # 统计处理结果
        total_patients = len(patient_ids)
        successful_patients = sum(1 for r in results.values() if r.get('success', False))
        total_calculations = sum(r.get('total_calculations', 0) for r in results.values())
        successful_calculations = sum(r.get('successful_calculations', 0) for r in results.values())
        
        success = successful_patients > 0
        
        if success:
            logger.info(f"✅ PVC SUVR计算完成: {successful_patients}/{total_patients} 个受试者成功, "
                       f"{successful_calculations}/{total_calculations} 个计算任务成功")
        else:
            logger.error(f"❌ PVC SUVR计算全部失败: 0/{total_patients} 个受试者成功")
        
        return {
            'success': success,
            'patients_processed': total_patients,
            'successful_patients': successful_patients,
            'total_calculations': total_calculations,
            'successful_calculations': successful_calculations,
            'detailed_results': results
        }
        
    except Exception as e:
        error_msg = f"PVC SUVR计算步骤执行失败: {e}"
        logger.error(f"❌ {error_msg}")
        return {
            'success': False,
            'error': error_msg,
            'patients_processed': 0,
            'successful_patients': 0
        }

def run_rename_step(patient_ids: List[str], modality: str, max_workers: int, logger: logging.Logger) -> Dict:
    """运行目录重命名步骤"""
    logger.info(f"开始执行目录重命名步骤，患者: {len(patient_ids)}个，模态: {modality}")
    
    # 直接使用传入的患者ID列表，不再计算范围
    results, skipped_patients = directory_renamer.rename_directory_for_ids(
        patient_ids=patient_ids,
        modality=modality,
        max_workers=max_workers
    )
    
    # 检查是否有跳过的患者
    if skipped_patients:
        logger.warning(f"⚠️ 以下患者的目录重命名被跳过: {', '.join(sorted(skipped_patients))}")
        logger.warning("  - 可能原因: 1) PET文件夹中有多个子文件夹(可能是变体); 2) 无法识别患者ID; 3) 目录结构异常")
    
    # 统计成功率
    total = len(results)
    success_count = sum(1 for success in results.values() if success)
    
    logger.info(f"目录重命名结果: {success_count}/{total} 成功")
    
    return results

def run_delete_step(patient_ids: List[str], modality: str, force: bool, keep_nifti: bool, logger: logging.Logger) -> Dict:
    """运行文件删除步骤"""
    nifti_msg = "保留.nii.gz文件" if keep_nifti else "删除所有文件"
    logger.info(f"开始执行文件删除步骤，患者: {len(patient_ids)}个，模态: {modality}，{nifti_msg}")
    
    # 调用delete模块的功能
    results = delete.delete_files_from_patient_ids(
        patient_ids=patient_ids,
        modality=modality,
        confirm=(not force),
        keep_nifti=keep_nifti
    )
    
    # 统计结果
    mr_deleted_total = 0
    pet_deleted_total = 0
    mr_patients = 0
    pet_patients = 0
    
    for r in results.values():
        if 'mr' in r and r['mr']:
            mr_deleted_total += r['mr'].get('files_deleted', 0)
            if r['mr'].get('files_deleted', 0) > 0:
                mr_patients += 1
        
        if 'pet' in r and r['pet']:
            pet_deleted_total += r['pet'].get('files_deleted', 0)
            if r['pet'].get('files_deleted', 0) > 0:
                pet_patients += 1
    
    nifti_msg = "（保留.nii.gz文件）" if keep_nifti else ""
    
    if modality == 'mr':
        logger.info(f"MR文件删除结果{nifti_msg}: {mr_patients}/{len(patient_ids)} 个患者成功，共删除 {mr_deleted_total} 个文件")
    elif modality == 'pet':
        logger.info(f"PET文件删除结果{nifti_msg}: {pet_patients}/{len(patient_ids)} 个患者成功，共删除 {pet_deleted_total} 个文件")
    else:
        logger.info(f"文件删除结果{nifti_msg}: "
                   f"MR: {mr_patients}/{len(patient_ids)} 个患者成功，共删除 {mr_deleted_total} 个文件，"
                   f"PET: {pet_patients}/{len(patient_ids)} 个患者成功，共删除 {pet_deleted_total} 个文件")
    
    return results

def run_check_step(patient_ids: List[str], check_type: str, logger: logging.Logger) -> Dict:
    """运行结果检查步骤"""
    if len(patient_ids) > 1:
        logger.warning(f"⚠️ 检查功能只能对单个患者的结果进行检查，将只处理第一个患者: {patient_ids[0]}")
    
    patient_id = patient_ids[0]
    logger.info(f"开始对患者 {patient_id} 执行 {check_type} 检查...")
    
    # 调用check模块功能
    try:
        check.check_results(
            subject_id=patient_id,
            check_type=check_type,
            recon_dir=config.RECON_DIR
        )
        logger.info(f"{utils.SUCCESS_EMOJI} 患者 {patient_id} 的 {check_type} 检查已完成")
        return {patient_id: {'success': True}}
    except Exception as e:
        logger.error(f"{utils.ERROR_EMOJI} 执行患者 {patient_id} 的 {check_type} 检查时出错: {e}")
        return {patient_id: {'success': False, 'error': str(e)}}

def run_clear_step(patient_ids: List[str], logger: logging.Logger) -> Dict:
    """运行临时文件清理步骤"""
    logger.info(f"启动交互式文件清理模块...")
    
    try:
        clear.run_clear_interactive(patient_ids)
        logger.info(f"✅ 文件清理模块执行完毕。")
        # 清理模块本身是交互式的，其成功与否由用户操作决定
        # 这里返回一个通用成功状态
        return {pid: {'success': True} for pid in patient_ids}
    except Exception as e:
        logger.error(f"❌ 执行文件清理模块时发生错误: {e}")
        return {pid: {'success': False, 'error': str(e)} for pid in patient_ids}


def run_recon_status_step(patient_ids: List[str], logger: logging.Logger) -> Dict:
    """运行FreeSurfer状态检查步骤"""
    logger.info(f"开始执行FreeSurfer状态检查步骤，患者: {len(patient_ids)}个")
    
    results = recon_status.process_subjects_recon_status(patient_ids)
    
    # 报告结果
    success_count = sum(1 for r in results.values() if r['success'])
    logger.info(f"FreeSurfer状态检查结果: {success_count}/{len(patient_ids)} 成功")
    
    return results

def _get_all_steps() -> List[str]:
    """获取所有标准处理步骤（不包括delete和check）"""
    return [s for s in VALID_STEPS.keys() if s not in ['delete', 'check', 'clear']]

def _run_processing_step(step: str, patient_ids: List[str], args: argparse.Namespace, logger: logging.Logger) -> Dict:
    """运行指定的处理步骤"""
    try:
        logger.info(f"开始执行步骤: {step} ({VALID_STEPS.get(step, '未知步骤')})")
        
        # 根据步骤类型调用不同的处理函数
        if step == 'rename':
            return run_rename_step(patient_ids, args.modality, args.workers, logger)
        elif step == 'convert':
            return run_convert_step(patient_ids, args.modality, args.workers, logger)
        elif step == 'header':
            return run_header_step(patient_ids, args.modality, args.workers, logger)
        elif step == 'info':
            return run_info_step(patient_ids, logger)
        elif step == 'recon':
            fs_flags = args.fs_flags.split() if args.fs_flags else []
            return run_recon_step(patient_ids, fs_flags, args.workers, logger)
        elif step == 'recon_sta':
            return run_recon_status_step(patient_ids, logger)
        elif step == 'registrate':
            return run_registration_step(patient_ids, args.workers, logger)
        elif step == 'mask':
            return run_mask_step(patient_ids, args.workers, logger)
        elif step == 'suvr':
            return run_suvr_step(patient_ids, args.workers, logger)
        elif step == 'pvc':
            return run_pvc_step(patient_ids, args.workers, logger)
        elif step == 'pvc_suvr':
            return run_pvc_suvr_step(patient_ids, args.workers, logger)
        elif step == 'delete':
            return run_delete_step(patient_ids, args.modality, not args.no_delete_confirm, args.keep_nifti, logger)
        elif step == 'check':
            check_type = 'ac' if args.all_check else (
                'sc' if args.segmentation_check else (
                    'rc' if args.registration_check else (
                        'mc' if args.mask_check else 'none'
                    )
                )
            )
            return run_check_step(patient_ids, check_type, logger)
        elif step == 'clear':
            return run_clear_step(patient_ids, logger)
        else:
            logger.error(f"❌ 未知的处理步骤: {step}")
            return {patient_id: {'success': False, 'error': f'未知的处理步骤: {step}'} for patient_id in patient_ids}
            
    except Exception as e:
        logger.error(f"❌ 执行步骤 {step} 时发生错误: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return {patient_id: {'success': False, 'error': str(e)} for patient_id in patient_ids}

def main() -> int:
    """主函数"""
    # 解析命令行参数
    args = parse_arguments()
    
    # 设置环境和日志
    logger = setup_environment()
    
    # 获取患者ID列表
    patient_ids = get_patient_list(args)
    if not patient_ids:
        logger.error("❌ 未提供有效的患者ID")
        return 1
    
    logger.info(f"将处理以下患者: {', '.join(patient_ids)}")
    
    # 检查是否是直接使用检查选项（-sc, -rc, -mc, -ac）
    if args.steps.lower() == 'clear':
        steps = ['clear']
    elif args.segmentation_check or args.registration_check or args.mask_check or args.all_check:
        steps = ['check']
    else:
        # 确定要执行的步骤
        steps = args.steps.lower().split(',')
        if 'all' in steps:
            steps = _get_all_steps()
            logger.info("注意：'all'选项不包含'delete'、'check'和'clear'步骤，如需执行这些步骤，请明确指定。")
        else:
            steps = _validate_steps(steps)
        
    if not steps:
        logger.error("❌ 未提供有效的处理步骤")
        return 1
    
    # 执行各步骤
    results = {}
    start_time = time.time()
    
    for step in steps:
        step_start_time = time.time()
        try:
            results[step] = _run_processing_step(step, patient_ids, args, logger)
            step_duration = time.time() - step_start_time
            logger.info(f"步骤'{step}'耗时: {step_duration:.2f}秒")
        except Exception as e:
            logger.error(f"❌ 执行步骤'{step}'时出错: {e}", exc_info=True)
    
    # 打印总结信息
    total_duration = time.time() - start_time
    logger.info("="*80)
    logger.info(f"🎉 处理完成，总耗时: {total_duration:.2f}秒")
    for step in steps:
        if step in results:
            count = len(results[step])
            logger.info(f"  - {step}: 处理了 {count} 个患者")
    logger.info("="*80)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())