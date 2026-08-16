# modules/registration.py
import os
import logging
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any, Callable
import concurrent.futures
from tqdm import tqdm

from . import utils
import config

logger = logging.getLogger(__name__)

# 常量定义
PET_EXTENSION = '.nii.gz'
MGZ_EXTENSION = '.mgz'

# 配准参数常量
DEFAULT_REG_METHOD = 'mri_coreg'  # 默认配准方法：'bbregister' 或 'mri_coreg'
DEFAULT_INTERP = 'trilin'         # 默认插值方法：'trilin', 'nearest', 'cubic' 等
DEFAULT_INIT = 'header'           # 默认初始化方式：'header', 'fsl', 'spm' 等

# 文件和目录名常量
PET_DIR_NAME = 'pet'              # PET数据目录名
MRI_DIR_NAME = 'mri'              # MRI数据目录名
REG_MATRIX_FILE = 'pet2mri.lta'   # 配准矩阵文件名
REGISTRATED_PET_PREFIX = 'registrated_pet'  # 配准后PET文件前缀

# 文件名模式常量
PET_SUFFIX_LOWER = '_pet'         # PET文件后缀（小写）
PET_SUFFIX_UPPER = '_PET'         # PET文件后缀（大写）

def _get_pet_variant_info(subject_id: str, variant_tag: str = "") -> Tuple[Path, Path, str, str]:
    """
    获取PET变体的相关信息
    
    参数:
        subject_id: 受试者ID
        variant_tag: PET变体标识，例如"-1"或""（空字符串表示标准PET）
        
    返回:
        元组: (变体目录, FreeSurfer主目录, 变体目录名, 文件前缀)
    """
    # 确定主目录
    subject_dir = Path(config.SUBJECTS_DIR) / subject_id
    pet_base_dir = subject_dir / PET_DIR_NAME
    
    # 根据变体标识确定目录和文件名
    if variant_tag:
        variant_dir_name = f"{subject_id}{PET_SUFFIX_LOWER}{variant_tag}"
        pet_file_prefix = f"{subject_id}{PET_SUFFIX_LOWER}{variant_tag}"
    else:
        variant_dir_name = f"{subject_id}{PET_SUFFIX_LOWER}"
        pet_file_prefix = f"{subject_id}{PET_SUFFIX_LOWER}"
    
    # 确定变体专用目录
    pet_variant_dir = pet_base_dir / variant_dir_name
    
    return pet_variant_dir, subject_dir, variant_dir_name, pet_file_prefix

def registrate_pet_to_mri(subject_id: str, pet_file: Path, variant_tag: str = "", reg_params: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[Path]]:
    """
    将PET图像配准到MRI空间
    
    参数:
        subject_id: 受试者ID
        pet_file: PET NIfTI文件路径
        variant_tag: PET变体标识，例如"-1"或""（空字符串表示标准PET）
        reg_params: 配准参数字典，包含method、interp和init等参数
        
    返回:
        成功标志和配准后的PET文件路径
    """
    subject_id = utils.format_patient_id(subject_id)
    
    # 输入验证
    if not isinstance(pet_file, Path):
        pet_file = Path(pet_file)
        
    if not pet_file.exists():
        logger.error(f"❌ 找不到PET文件: {pet_file}")
        return False, None
    
    # 获取变体信息
    pet_variant_dir, subject_dir, variant_dir_name, pet_file_prefix = _get_pet_variant_info(subject_id, variant_tag)
    
    # 创建必要的目录
    pet_base_dir = subject_dir / PET_DIR_NAME
    pet_base_dir.mkdir(parents=True, exist_ok=True)
    pet_variant_dir.mkdir(parents=True, exist_ok=True)
    
    # 检查FreeSurfer重建是否存在
    if not (subject_dir / MRI_DIR_NAME).exists():
        logger.error(f"❌ 找不到FreeSurfer重建目录: {subject_dir}/{MRI_DIR_NAME}")
        return False, None
    
    # 获取配准参数
    if reg_params is None:
        reg_params = {}
    method = reg_params.get('method', DEFAULT_REG_METHOD)
    interp = reg_params.get('interp', DEFAULT_INTERP)
    init = reg_params.get('init', DEFAULT_INIT)
    
    try:
        logger.info(f"🔄 开始处理患者 {subject_id} 的 PET{variant_tag} 变体...")
        logger.info(f"🔄 使用配准方法: {method}, 插值方法: {interp}, 初始化方式: {init}")
        
        # 1. 转换PET文件格式
        logger.info(f"🔄 转换PET文件格式...")
        pet_mgz = pet_variant_dir / f"{pet_file_prefix}{MGZ_EXTENSION}"
        cmd = ['mri_convert', str(pet_file), str(pet_mgz)]
        utils.run_freesurfer_command(cmd, subject_id=subject_id)
        
        # 2. 生成配准矩阵
        logger.info(f"🔄 生成配准矩阵...")
        lta_file = pet_variant_dir / REG_MATRIX_FILE
        
        if method == 'bbregister':
            cmd = [
                'bbregister', 
                '--s', subject_id,
                '--mov', str(pet_mgz),
                '--reg', str(lta_file),
                '--t1',
                f'--init-{init}'
            ]
        else:  # 使用mri_coreg
            cmd = [
                'mri_coreg', 
                '--s', subject_id,
                '--mov', str(pet_mgz),
                '--reg', str(lta_file)
            ]
        
        utils.run_freesurfer_command(cmd, subject_id=subject_id)
        
        # 3. 将PET配准到MR个体空间
        logger.info(f"🔄 将PET配准到MR个体空间...")
        registrated_pet_mgz = pet_variant_dir / f'{REGISTRATED_PET_PREFIX}{MGZ_EXTENSION}'
        cmd = [
            'mri_vol2vol', 
            '--mov', str(pet_mgz),
            '--reg', str(lta_file),
            '--o', str(registrated_pet_mgz),
            '--fstarg',
            '--interp', interp
        ]
        utils.run_freesurfer_command(cmd, subject_id=subject_id)
        
        # 4. 转换回NIfTI格式
        registrated_pet_nii = pet_variant_dir / f'{REGISTRATED_PET_PREFIX}{PET_EXTENSION}'
        cmd = ['mri_convert', str(registrated_pet_mgz), str(registrated_pet_nii)]
        utils.run_freesurfer_command(cmd, subject_id=subject_id)
        
        logger.info(f"✅ 患者 {subject_id} 的 PET{variant_tag} 配准完成: {registrated_pet_nii}")
        return True, registrated_pet_nii
        
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 患者 {subject_id} 的 PET{variant_tag} 配准命令执行失败: {e}")
        logger.error(f"错误输出: {e.stderr if hasattr(e, 'stderr') else '未知错误'}")
        return False, None
    except Exception as e:
        logger.error(f"❌ 患者 {subject_id} 的 PET{variant_tag} 配准失败: {e}")
        return False, None

def find_pet_variants(subject_id: str) -> List[Tuple[Path, str]]:
    """
    查找患者的所有PET变体及其标识
    
    参数:
        subject_id: 患者ID
        
    返回:
        包含(文件路径, 变体标识)元组的列表
    """
    subject_id = utils.format_patient_id(subject_id)
    results = []
    
    # 患者PET目录
    pet_dir = config.PET_DIR / subject_id
    if not pet_dir.exists():
        logger.warning(f"⚠️ 患者 {subject_id} 的PET目录不存在")
        return []
    
    # 查找标准PET文件（小写）
    standard_pet = pet_dir / f"{subject_id}{PET_SUFFIX_LOWER}{PET_EXTENSION}"
    if standard_pet.exists():
        results.append((standard_pet, ""))
        logger.info(f"找到标准PET文件(小写): {standard_pet}")
    
    # 查找标准PET文件（大写）
    standard_pet_upper = pet_dir / f"{subject_id}{PET_SUFFIX_UPPER}{PET_EXTENSION}"
    if standard_pet_upper.exists() and not standard_pet.exists():
        # 如果小写版本不存在，才添加大写版本（避免重复）
        results.append((standard_pet_upper, ""))
        logger.info(f"找到标准PET文件(大写): {standard_pet_upper}")
    
    # 查找变体PET文件
    variant_patterns = [f"{subject_id}{PET_SUFFIX_LOWER}-*{PET_EXTENSION}", f"{subject_id}{PET_SUFFIX_UPPER}-*{PET_EXTENSION}"]
    for pattern in variant_patterns:
        for pet_file in pet_dir.glob(pattern):
            # 提取正确的变体标识
            if f'{PET_SUFFIX_LOWER}-' in pet_file.name.lower():
                # 从文件名中提取变体标识
                base_name = pet_file.name.lower()
                variant_part = base_name.split(f'{PET_SUFFIX_LOWER}-')[1].split('.')[0]
                variant_tag = f"-{variant_part}"
                
                results.append((pet_file, variant_tag))
                logger.info(f"找到PET变体: {pet_file.name} (变体标识: {variant_tag})")
    
    # 日志汇总
    if not results:
        logger.warning(f"⚠️ 患者 {subject_id} 没有找到任何PET文件")
    else:
        logger.info(f"✅ 患者 {subject_id} 找到 {len(results)} 个PET文件")
        for pet_file, variant in results:
            logger.info(f"  - {pet_file.name} (变体: {variant or '标准'})")
    
    return results

def _process_batch_registration(
    patient_ids: List[str],
    max_workers: int,
    reg_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Dict]:
    """
    批量处理患者PET配准的通用逻辑
    
    参数:
        patient_ids: 格式化的患者ID列表
        max_workers: 最大并行处理数
        reg_params: 配准参数字典，包含method、interp和init等参数
        
    返回:
        包含每个患者处理结果的字典
    """
    # 参数验证
    if not patient_ids:
        logger.warning("⚠️ 未提供任何患者ID，无法进行处理")
        return {}

    # 首先收集所有需要处理的任务
    all_tasks_to_process = []
    for pid in patient_ids:
        pet_variants = find_pet_variants(pid)
        for pet_file, variant_tag in pet_variants:
            all_tasks_to_process.append((pid, pet_file, variant_tag))
            
    total_tasks = len(all_tasks_to_process)
    
    if total_tasks == 0:
        logger.warning("⚠️ 未找到任何需要处理的PET文件")
        return {}

    # 限制工作线程数量，基于总任务数
    cpu_count = os.cpu_count() or 4
    optimal_workers = min(max_workers, cpu_count, total_tasks)
    if optimal_workers != max_workers:
        logger.info(f"ℹ️ 调整并行处理数量: {max_workers} → {optimal_workers}")
    
    results = {}
    futures_map = {}
    
    # 日志记录配准参数
    if reg_params:
        method = reg_params.get('method', DEFAULT_REG_METHOD)
        interp = reg_params.get('interp', DEFAULT_INTERP)
        init = reg_params.get('init', DEFAULT_INIT)
        logger.info(f"使用配准参数: 方法={method}, 插值={interp}, 初始化={init}")
    else:
        logger.info(f"使用默认配准参数: 方法={DEFAULT_REG_METHOD}, 插值={DEFAULT_INTERP}, 初始化={DEFAULT_INIT}")
    
    # 并行处理
    with tqdm(total=total_tasks, desc="PET配准进度") as pbar:
        with concurrent.futures.ProcessPoolExecutor(max_workers=optimal_workers) as executor:
            # 提交所有任务
            for pid, pet_file, variant_tag in all_tasks_to_process:
                # 提交处理任务
                future = executor.submit(registrate_pet_to_mri, pid, pet_file, variant_tag, reg_params)
                futures_map[future] = (pid, variant_tag)
            
            # 处理任务结果
            for future in concurrent.futures.as_completed(futures_map):
                pid, variant_tag = futures_map[future]
                try:
                    success, registrated_file = future.result()
                    
                    # 确保结果字典初始化
                    if pid not in results:
                        results[pid] = {}
                    
                    # 存储变体结果
                    results[pid][variant_tag] = {
                        'success': success,
                        'registrated_file': str(registrated_file) if registrated_file else None
                    }
                except concurrent.futures.CancelledError:
                    logger.error(f"❌ 患者 {pid} 的 PET{variant_tag} 任务被取消")
                    _add_error_result(results, pid, variant_tag, "任务被取消")
                except Exception as e:
                    logger.error(f"❌ 处理患者 {pid} 的 PET{variant_tag} 时出错: {e}")
                    _add_error_result(results, pid, variant_tag, str(e))
                finally:
                    pbar.update(1)
    
    # 统计结果
    _log_registration_results(results)
    
    return results

def _add_error_result(results: Dict[str, Dict], pid: str, variant_tag: str, error_msg: str) -> None:
    """
    添加错误结果到结果字典
    
    参数:
        results: 结果字典
        pid: 患者ID
        variant_tag: 变体标识
        error_msg: 错误信息
    """
    if pid not in results:
        results[pid] = {}
        
    results[pid][variant_tag] = {
        'success': False,
        'error': error_msg
    }

def _log_registration_results(results: Dict[str, Dict]) -> None:
    """
    记录配准结果统计
    
    参数:
        results: 配准结果字典
    """
    if not results:
        logger.warning("⚠️ 未处理任何患者数据")
        return
        
    success_count = sum(1 for r in results.values() for v in r.values() if v.get('success', False))
    total = sum(len(r) for r in results.values())
    success_rate = (success_count / total * 100) if total > 0 else 0
    
    # 统计患者级别成功率
    patients_total = len(results)
    patients_with_success = sum(1 for r in results.values() if any(v.get('success', False) for v in r.values()))
    patients_rate = (patients_with_success / patients_total * 100) if patients_total > 0 else 0
    
    logger.info(f"🎉 PET配准完成:")
    logger.info(f"   - 总任务: {total}个, 成功: {success_count}个 ({success_rate:.1f}%)")
    logger.info(f"   - 患者数: {patients_total}个, 至少一个变体成功: {patients_with_success}个 ({patients_rate:.1f}%)")
    
    # 如果有失败，记录失败的变体
    if success_count < total:
        failed_variants = []
        for pid, variants in results.items():
            for tag, result in variants.items():
                if not result.get('success', False):
                    variant_name = f"{pid}{PET_SUFFIX_LOWER}{tag}" if tag else f"{pid}{PET_SUFFIX_LOWER}"
                    failed_variants.append(variant_name)
        
        # 只显示前10个失败的变体
        if failed_variants:
            logger.warning(f"⚠️ 以下变体配准失败: {', '.join(failed_variants[:10])}")
            if len(failed_variants) > 10:
                logger.warning(f"   以及其他 {len(failed_variants) - 10} 个变体")

def registrate_patient_range(
    start_subj: int,
    end_subj: int,
    max_workers: int = 8
) -> Dict[str, Dict]:
    """
    批量处理指定范围内患者的PET配准
    
    参数:
        start_subj: 起始患者编号
        end_subj: 结束患者编号
        max_workers: 最大并行处理数
        
    返回:
        包含每个患者处理结果的字典
    """
    # 参数验证
    if start_subj > end_subj:
        logger.error(f"❌ 无效的患者范围: {start_subj}-{end_subj}")
        return {}
    
    # 生成患者ID列表
    patient_ids = [utils.format_patient_id(i) for i in range(start_subj, end_subj + 1)]
    logger.info(f"开始处理患者范围 {start_subj}-{end_subj}，共 {len(patient_ids)} 个患者")
    
    # 使用通用处理逻辑
    return _process_batch_registration(patient_ids, max_workers)

def registrate_patient_ids(
    patient_ids: List[str],
    max_workers: int = 8,
    reg_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Dict]:
    """
    批量处理指定ID列表患者的PET配准
    
    参数:
        patient_ids: 患者ID列表
        max_workers: 最大并行处理数
        reg_params: 配准参数字典，包含method、interp和init等参数
        
    返回:
        包含每个患者处理结果的字典
    """
    # 参数验证
    if not patient_ids:
        logger.warning("⚠️ 未提供任何患者ID，无法进行处理")
        return {}
    
    # 格式化患者ID
    formatted_ids = [utils.format_patient_id(pid) for pid in patient_ids]
    logger.info(f"开始处理 {len(formatted_ids)} 个指定患者")
    
    # 使用通用处理逻辑
    return _process_batch_registration(formatted_ids, max_workers, reg_params)
