import os
import logging
import subprocess
from pathlib import Path
import concurrent.futures
import tempfile
from typing import Dict, List, Optional, Tuple, Union, Any, Callable
import csv # 不再需要csv模块
import json
from tqdm import tqdm
import re
import pandas as pd

# 假设 utils, registration 和 config 模块在同一父目录下
# 根据实际项目结构调整导入路径
from . import utils
from . import registration
import config # 假设 config.py 在项目根目录或者可以通过PYTHONPATH访问

logger = logging.getLogger(__name__)

# 常量定义
NIFTI_EXTENSION = '.nii.gz'
CSV_EXTENSION = '.csv' # 不再需要
TXT_EXTENSION = '.txt'
EXCEL_EXTENSION = '.xlsx'
DEFAULT_STATS_PARENT_DIR_NAME = 'stats'  # 父统计目录名，如 data/recon_xxx/00x/stats
DEFAULT_MASK_DIR_NAME = 'mask'    # 掩膜目录名
DEFAULT_PET_DIR_NAME = 'pet'      # PET 目录名

# 默认SUVR阈值
DEFAULT_THRESHOLDS = {
    'wholecerebellum': 1.11,
    'composite': 0.78,
    'composite_fsm8_thr07': 0.78,
    'composite_e1': 0.78,
    'composite_e2': 0.78
}

# CSV文件列定义 (与旧版保持一致，后续按需调整)
CSV_COLUMNS = {
    'subject': ["Subject"],
    'variant_parts': ["vTag1", "vTag2", "vTag3"],
    'target_means': [
        "Composite_Count", "Cingulate_Count", "Frontal_Count",
        "Parietal_Count", "Temporal_Count"
    ],
    'reference_means': [
        "CerebellumGM_Ref", "Brainstem_Ref", "WholeCerebellum_Ref",
        "SubcorticalWM_Ref", "SubcorticalWM_FSM8_Thr07_Ref", "SubcorticalWM_E1_Ref", "SubcorticalWM_E2_Ref",
        "Composite_Ref", "Composite_FSM8_Thr07_Ref", "CompositeE1_Ref", "CompositeE2_Ref"
    ],
    'suvr_values': [
        "CerebellumGM_SUVR", "Brainstem_SUVR", "WholeCerebellum_SUVR",
        "SubcorticalWM_SUVR", "SubcorticalWM_FSM8_Thr07_SUVR", "SubcorticalWM_E1_SUVR", "SubcorticalWM_E2_SUVR",
        "Composite_SUVR", "Composite_FSM8_Thr07_SUVR", "CompositeE1_SUVR", "CompositeE2_SUVR"
    ],
    'judgments': [
        "WholeCerebellum_Status", "Composite_Status", "Composite_FSM8_Thr07_Status",
        "CompositeE1_Status", "CompositeE2_Status"
    ],
    'regional_suvr': [
        "Cingulate_WholeCerebellum_SUVR", "Frontal_WholeCerebellum_SUVR", 
        "Parietal_WholeCerebellum_SUVR", "Temporal_WholeCerebellum_SUVR"
    ]
}


def _get_subject_dir(subject_id: str) -> Path:
    """
    获取受试者根目录路径。

    参数:
        subject_id: 受试者ID。

    返回:
        受试者根目录的Path对象。
    """
    return Path(config.SUBJECTS_DIR) / subject_id


def _get_variant_stats_dir(subject_id: str, variant_tag: str, output_dir_override: Optional[Path] = None) -> Path:
    """
    获取特定PET变体的统计数据输出目录路径。
    新结构: data/recon_xxx/<subject_id>/stats/<variant_tag>/

    参数:
        subject_id: 受试者ID。
        variant_tag: PET变体标识 (例如 "2-3-1", 如果是标准PET，则可能为空或特定标识如 "standard")。
                     如果为空，则使用 "standard" 作为目录名。
        output_dir_override: 可选的自定义父输出目录 (覆盖 config.SUBJECTS_DIR/<subject_id>/stats)。

    返回:
        特定变体的统计数据目录路径。
    """
    logger.debug(f"[CHECKPOINT] _get_variant_stats_dir - Entering for Subject: {subject_id}, Variant: '{variant_tag}', OutputDirOverride: {output_dir_override}")
    subject_base_dir = _get_subject_dir(subject_id)
    # 父统计目录，例如: .../<subject_id>/stats
    parent_stats_dir = output_dir_override if output_dir_override else subject_base_dir / DEFAULT_STATS_PARENT_DIR_NAME

    # 处理变体标识，确保不为空，以便创建子目录
    # 如果原始 variant_tag 是空字符串，我们将其映射到一个明确的目录名，比如 "standard"
    # 如果 variant_tag 是 "-" 或其他以特殊字符开头的，直接使用
    
    # 步骤1: 初始化和初步处理
    temp_tag = variant_tag if variant_tag else "standard"

    # 步骤2: 处理以 "-" 开头的标签
    if temp_tag.startswith('-') and len(temp_tag) > 1:
        processed_variant_name = temp_tag[1:]
    elif temp_tag == "-":
        processed_variant_name = "variant_dash"
    else:
        processed_variant_name = temp_tag

    # 步骤3: 确保最终的目录名不是 "." 或空 (空基本不会发生，但加上更安全)
    if not processed_variant_name or processed_variant_name == ".":
        dir_friendly_variant_tag = "standard"  # 对 "." 或意外的空标签使用 "standard"
    else:
        dir_friendly_variant_tag = processed_variant_name
    
    # 特定变体的统计目录，例如: .../<subject_id>/stats/2-3-1/ 或 .../<subject_id>/stats/standard/
    variant_specific_stats_dir = parent_stats_dir / dir_friendly_variant_tag
    variant_specific_stats_dir.mkdir(parents=True, exist_ok=True)
    logger.debug(f"[CHECKPOINT] _get_variant_stats_dir - Returning VariantSpecificStatsDir: {variant_specific_stats_dir} (parent: {parent_stats_dir}, friendly_tag: {dir_friendly_variant_tag})")
    return variant_specific_stats_dir


def _get_mask_dir(subject_id: str) -> Path:
    """
    获取掩膜目录路径。
    路径: data/recon_xxx/<subject_id>/mask/

    参数:
        subject_id: 受试者ID。

    返回:
        掩膜目录路径。
    """
    return _get_subject_dir(subject_id) / DEFAULT_MASK_DIR_NAME


def _get_pet_variant_dir(subject_id: str, variant_tag: str = "") -> Path:
    """
    获取PET变体原始数据所在目录的路径。
    这通常是配准后的PET文件所在的目录。
    路径: data/recon_xxx/<subject_id>/pet/<subject_id>_pet<variant_tag>/

    参数:
        subject_id: 受试者ID。
        variant_tag: PET变体标识 (例如 "-1", "" 表示标准)。

    返回:
        PET变体目录路径。
    """
    subject_dir = _get_subject_dir(subject_id)
    variant_dir_name = f"{subject_id}_pet{variant_tag}" if variant_tag else f"{subject_id}_pet"
    return subject_dir / DEFAULT_PET_DIR_NAME / variant_dir_name


def _get_registrated_pet_file(subject_id: str, variant_tag: str = "") -> Path:
    """
    获取配准后的PET文件路径。

    参数:
        subject_id: 受试者ID。
        variant_tag: PET变体标识。

    返回:
        配准后的PET文件路径。
    """
    pet_dir = _get_pet_variant_dir(subject_id, variant_tag)
    return pet_dir / f'registrated_pet{NIFTI_EXTENSION}'


def _check_required_files(files: List[Path]) -> List[Path]:
    """
    检查必需的文件列表，记录缺失文件并返回存在的文件列表。

    参数:
        files: 文件路径列表。

    返回:
        存在的文件列表。
    """
    existing_files: List[Path] = []
    for f_path in files:
        if f_path.exists():
            existing_files.append(f_path)
        else:
            logger.warning(f"⚠️ 文件不存在: {f_path}")
    return existing_files


def calculate_roi_mean(
    subject_id: str,
    mask_file: Path,
    pet_file: Path,
    variant_tag: str, # 新增：用于确定输出目录
    output_dir_override: Optional[Path] = None
) -> Tuple[bool, Optional[float], Optional[Path], Optional[Path]]:
    """
    使用mri_segstats计算掩膜区域内的PET平均值，并将结果保存到变体特定的统计目录中。

    参数:
        subject_id: 受试者ID。
        mask_file: 掩膜文件路径。
        pet_file: 配准后的PET文件路径。
        variant_tag: PET变体标识，用于确定输出子目录。
        output_dir_override: 可选的自定义父输出目录 (覆盖 config.SUBJECTS_DIR/<subject_id>/stats)。

    返回:
        元组 (成功标志, 区域平均值, 输出均值文件路径, 输出统计文件路径)。
    """
    logger.debug(f"[CHECKPOINT] calculate_roi_mean - Entering for Subject: {subject_id}, Mask: {mask_file.name}, PET: {pet_file.name}, Variant: '{variant_tag}', OutputDirOverride: {output_dir_override}")
    subject_id = utils.format_patient_id(subject_id)

    # 参数验证
    if not mask_file.exists():
        logger.error(f"❌ 掩膜文件不存在: {mask_file} (受试者: {subject_id}, 变体: {variant_tag})")
        return False, None, None, None

    if not pet_file.exists():
        logger.error(f"❌ PET文件不存在: {pet_file} (受试者: {subject_id}, 变体: {variant_tag})")
        return False, None, None, None

    # 获取特定变体的统计目录
    # variant_stats_dir 的路径会是类似 .../stats/2-3-1/
    variant_stats_dir = _get_variant_stats_dir(subject_id, variant_tag, output_dir_override)

    # 生成输出文件名 - 从掩膜文件名中提取基本名称
    mask_name_base = mask_file.name.split('.')[0] # 获取如 "ref_composite_e2" 或 "temporal_mask"

    # 构造符合要求的输出文件名
    # 例如: ref_composite_e2_summary_mean.txt 和 ref_composite_e2_summary_stats.txt
    mean_file = variant_stats_dir / f"{mask_name_base}_summary_mean{TXT_EXTENSION}"
    stats_file = variant_stats_dir / f"{mask_name_base}_summary_stats{TXT_EXTENSION}"
    logger.debug(f"[CHECKPOINT] calculate_roi_mean - Subject: {subject_id}, Variant: '{variant_tag}', Mask: {mask_name_base} -> MeanFile: {mean_file}, StatsFile: {stats_file}")

    try:
        cmd = [
            'mri_segstats',
            '--seg', str(mask_file),
            '--i', str(pet_file),
            '--avgwf', str(mean_file),  # 输出均值文件
            '--sum', str(stats_file)    # 输出统计摘要文件
        ]

        # 注意：utils.run_freesurfer_command 可能需要根据实际情况调整，确保其能正确执行
        utils.run_freesurfer_command(cmd, subject_id=subject_id)

        mean_value: Optional[float] = None
        if mean_file.exists():
            with open(mean_file, 'r') as f:
                lines = f.readlines()
                if lines: # 确保文件不是空的
                    # 均值文件通常第一行包含类似 "# Frame 0 Mean	<value>" 或直接是 "<value>"
                    # 需要根据实际mri_segstats输出格式解析
                    # 假设均值在第一行，并且是空格分隔的第二个字段 (如果存在标签)
                    # 或者如果只有值，则是第一个字段
                    parts = lines[0].strip().split()
                    try:
                        if len(parts) >= 2 and parts[0].startswith("#"):  # 例如 "# Frame 0 Mean	<value>"
                            mean_value = float(parts[-1])  # 通常最后一个是值
                        elif len(parts) >= 2: # 例如 "value1 value2" (无注释头，至少两个值)
                            mean_value = float(parts[1]) # 用户要求读取第二个值
                        elif len(parts) == 1 and not parts[0].startswith("#"): # 例如 "value1" (无注释头，只有一个值)
                            mean_value = float(parts[0]) # 只有一个值，就取这个值
                        else:
                            logger.error(f"❌ 无法从 {mean_file} 解析均值: 行内容格式不符合预期 - '{lines[0].strip()}'")
                            return False, None, mean_file, stats_file # 返回已生成的文件路径
                    except ValueError:
                        logger.error(f"❌ 无法从 {mean_file} 解析均值: 值不是有效的浮点数 - '{lines[0].strip()}'")
                        return False, None, mean_file, stats_file
                else:
                    logger.error(f"❌ 均值文件为空: {mean_file}")
                    # 即使文件为空，命令可能已成功创建了文件，所以返回路径
                    return False, None, mean_file, stats_file

            if mean_value is not None:
                 logger.info(f"✅ 受试者 {subject_id} (变体: {variant_tag}), {mask_name_base} 区域平均值: {mean_value:.4f}")
            # else: mean_value 为 None 时，上面已经有错误日志了

        else:
            logger.error(f"❌ 未能生成均值文件: {mean_file} (受试者: {subject_id}, 变体: {variant_tag})")
            # stats_file 可能也未生成或部分生成
            return False, None, None, stats_file if stats_file.exists() else None

        # 确保 stats_file 也被创建了
        if not stats_file.exists():
            logger.warning(f"⚠️ 统计摘要文件似乎未生成: {stats_file} (受试者: {subject_id}, 变体: {variant_tag})")
            # 即使摘要文件缺失，如果均值计算成功，也可能希望继续
            # 但根据需求，这两个文件都应该生成
            # 如果严格要求，可以返回 False

        return True, mean_value, mean_file, stats_file

    except subprocess.CalledProcessError as e:
        logger.error(f"❌ 计算 {mask_name_base} 区域平均值命令 (mri_segstats) 执行失败 (受试者: {subject_id}, 变体: {variant_tag}): {e}")
        error_output = e.stderr.decode(errors='ignore') if hasattr(e, 'stderr') and e.stderr else '未知错误输出'
        logger.error(f"错误输出: {error_output}")
        # 返回可能已创建的文件路径
        return False, None, mean_file if mean_file.exists() else None, stats_file if stats_file.exists() else None
    except Exception as e:
        logger.error(f"❌ 计算 {mask_name_base} 区域平均值时发生意外错误 (受试者: {subject_id}, 变体: {variant_tag}): {e}")
        return False, None, None, None


def _get_mask_files(subject_id: str) -> Tuple[List[Path], List[Path]]:
    """
    获取用于计算的靶区和参考区域掩膜文件列表。
    与旧版逻辑类似，只是路径获取方式可能更新。

    参数:
        subject_id: 受试者ID。

    返回:
        元组 (靶区掩膜列表, 参考区域掩膜列表)。
    """
    mask_dir = _get_mask_dir(subject_id) # mask目录保持在 subject_id/mask/

    # 靶区掩膜 (文件名基于旧版)
    target_masks = [
        mask_dir / f'composite{NIFTI_EXTENSION}',       # 复合皮质区
        mask_dir / f'cingulate_mask{NIFTI_EXTENSION}',  # 扣带回
        mask_dir / f'frontal_mask{NIFTI_EXTENSION}',    # 额叶
        mask_dir / f'parietal_mask{NIFTI_EXTENSION}',   # 顶叶
        mask_dir / f'temporal_mask{NIFTI_EXTENSION}'    # 颞叶
    ]

    # 参考区域掩膜
    reference_masks = [
        mask_dir / f'ref_cerebellumgm{NIFTI_EXTENSION}',            # 小脑灰质
        mask_dir / f'ref_brainstem{NIFTI_EXTENSION}',               # 脑干
        mask_dir / f'ref_wholecerebellum{NIFTI_EXTENSION}',         # 全小脑
        mask_dir / f'ref_subcorticalwm{NIFTI_EXTENSION}',           # 原始皮质下白质
        mask_dir / f'ref_subcorticalwm_fsm8_thr07{NIFTI_EXTENSION}',  # 平滑阈值化皮质下白质
        mask_dir / f'ref_subcorticalwm_erode1{NIFTI_EXTENSION}',    # 腐蚀1次皮质下白质
        mask_dir / f'ref_subcorticalwm_erode2{NIFTI_EXTENSION}',    # 腐蚀2次皮质下白质
        mask_dir / f'ref_composite{NIFTI_EXTENSION}',               # 复合参考区域（基于原始皮质下白质）
        mask_dir / f'ref_composite_fsm8_thr07{NIFTI_EXTENSION}',    # 复合参考区域（基于平滑阈值化皮质下白质）
        mask_dir / f'ref_composite_e1{NIFTI_EXTENSION}',            # 复合参考区域E1（基于侵蚀1次皮质下白质）
        mask_dir / f'ref_composite_e2{NIFTI_EXTENSION}'             # 复合参考区域E2（基于侵蚀2次皮质下白质）
    ]

    return target_masks, reference_masks


def _make_judgments(suvr_values: Dict[str, float], thresholds: Dict[str, float]) -> Dict[str, str]:
    """
    根据SUVR值和阈值进行判断。

    参数:
        suvr_values: SUVR值字典。
        thresholds: 阈值字典。

    返回:
        判断结果字典 (例如: {'wholecerebellum': '+'})。
    """
    judgments: Dict[str, str] = {}
    for region, threshold_val in thresholds.items():
        # suvr_values 的键应该是简化后的区域名，如 'wholecerebellum'
        suvr_value = suvr_values.get(region)
        if suvr_value is not None:
            judgments[region] = "+" if suvr_value >= threshold_val else "-"
        else:
            # 如果某个阈值对应的区域没有计算出SUVR值，可以选择记录或跳过
            logger.debug(f"区域 {region} 在SUVR值中未找到，无法进行判断。")
    return judgments


def _write_suvr_results_to_file(
    subject_id: str,
    results: Dict[str, Any],
    variant_tag: str,
    output_dir_override: Optional[Path] = None
) -> Optional[Path]:
    """
    将SUVR计算的详细结果写入到特定变体的统计目录中的文本文件。
    文件名格式: suvr_results-<variant_tag>.txt

    参数:
        subject_id: 受试者ID。
        results: SUVR计算结果字典，包含 'target_means', 'reference_means', 'suvr_values', 'judgments'。
        variant_tag: PET变体标识 (例如 "-1", "-2-3-1")。如果为空，则文件名中不包含变体部分或使用 "standard"。
        output_dir_override: 可选的自定义父输出目录。

    返回:
        成功写入则返回结果文件路径，否则返回None。
    """
    logger.debug(f"[CHECKPOINT] _write_suvr_results_to_file - Entering for Subject: {subject_id}, Variant: '{variant_tag}', OutputDirOverride: {output_dir_override}")
    variant_stats_dir = _get_variant_stats_dir(subject_id, variant_tag, output_dir_override)

    # 处理文件名中的 variant_tag
    # 如果 variant_tag 是 "-2-3-1"，文件名是 suvr_results-2-3-1.txt
    # 如果 variant_tag 是 "" (标准)，文件名可以是 suvr_results-standard.txt 或 suvr_results.txt
    # 我们采用 suvr_results-<processed_variant_tag>.txt 的形式，其中 processed_variant_tag 不以'-'开头
    file_variant_suffix = variant_tag if variant_tag else "standard"
    if file_variant_suffix.startswith('-') and len(file_variant_suffix) > 1:
        file_variant_suffix = file_variant_suffix[1:] # 移除开头的 '-'
    elif file_variant_suffix == "-":
        file_variant_suffix = "dash" # 对于单个 '-' 的特殊处理

    # 如果原始variant_tag为空，且我们希望文件名是 suvr_results.txt (不含standard)
    # 可以这样调整：
    # result_file_name = f"suvr_results{TXT_EXTENSION}" if not variant_tag else f"suvr_results-{file_variant_suffix}{TXT_EXTENSION}"
    # 但为了统一和明确，这里统一使用带处理后tag的后缀
    result_file_name = f"suvr_results-{file_variant_suffix}{TXT_EXTENSION}"

    result_file_path = variant_stats_dir / result_file_name
    logger.debug(f"[CHECKPOINT] _write_suvr_results_to_file - Subject: {subject_id}, Variant: '{variant_tag}' -> ResultFile: {result_file_path}")

    try:
        with open(result_file_path, 'w') as f:
            f.write(f"# SUVr_summary (Subject: {subject_id}, Variant: {variant_tag if variant_tag else 'standard'}) - {utils.get_datetime()}\n")

            f.write("\n# Target Area Original Mean Values:\n")
            if 'target_means' in results:
                for target_name, target_mean in results['target_means'].items():
                    # target_name 可能是如 'composite', 'cingulate_mask'
                    f.write(f"{target_name}: {target_mean:.4f}\n" if isinstance(target_mean, float) else f"{target_name}: N/A\n")
            else:
                f.write("No target means data available.\n")

            f.write("\n# Reference Area Original Mean Values:\n")
            if 'reference_means' in results:
                for ref_name, ref_mean in results['reference_means'].items():
                    # ref_name 可能是如 'ref_cerebellumgm', 'ref_brainstem'
                    # 在文件中写入时，通常去掉 'ref_' 前缀
                    simple_ref_name = ref_name.replace("ref_", "")
                    f.write(f"{simple_ref_name}: {ref_mean:.4f}\n" if isinstance(ref_mean, float) else f"{simple_ref_name}: N/A\n")
            else:
                f.write("No reference means data available.\n")

            f.write("\n# SUVr Values:\n")
            if 'suvr_values' in results:
                for ref_name, suvr_value in results['suvr_values'].items():
                    # ref_name 是简化后的，如 'cerebellumgm', 'wholecerebellum'
                    judgment_str = ""
                    if 'judgments' in results and ref_name in results['judgments']:
                        judgment_str = f" ({results['judgments'][ref_name]})"
                    f.write(f"{ref_name}: {suvr_value:.4f}{judgment_str}\n" if isinstance(suvr_value, float) else f"{ref_name}: N/A{judgment_str}\n")
            else:
                f.write("No SUVr values data available.\n")

        logger.info(f"✅ SUVR 详细结果已保存到: {result_file_path}")
        return result_file_path
    except IOError as e:
        logger.error(f"❌ 写入SUVR结果文件 {result_file_path} 失败: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ 写入SUVR结果文件时发生意外错误: {e}")
        return None


def calculate_suvr_values(
    subject_id: str,
    pet_file: Path,
    variant_tag: str, # 变体标识，会传递给 calculate_roi_mean 和 _write_suvr_results_to_file
    custom_thresholds: Optional[Dict[str, float]] = None,
    output_dir_override: Optional[Path] = None # 允许覆盖顶层统计目录
) -> Dict[str, Any]: # 返回类型与旧版类似，包含成功标志和结果
    """
    计算给定PET文件和变体的SUVR值，并将所有相关文件保存到变体特定的子目录中。

    参数:
        subject_id: 受试者ID。
        pet_file: 配准后的PET文件路径。
        variant_tag: PET变体标识 (例如 "-1", "", "custom").
        custom_thresholds: 可选的自定义阈值字典。
        output_dir_override: 可选的自定义父输出目录 (覆盖 config.SUBJECTS_DIR/<subject_id>/stats)。

    返回:
        包含计算结果的字典，包括 'success', 'target_means', 'reference_means', 'suvr_values', 'judgments', 和 'result_file' (指向suvr_results-.txt)。
    """
    subject_id = utils.format_patient_id(subject_id)

    # 参数验证
    if not pet_file.exists():
        logger.error(f"❌ PET文件不存在于 {pet_file} (受试者: {subject_id}, 变体: {variant_tag})")
        return {'success': False, 'error': f"PET文件不存在: {pet_file}"}

    # 设置阈值 (合并默认阈值和自定义阈值)
    thresholds = DEFAULT_THRESHOLDS.copy()
    if custom_thresholds:
        thresholds.update(custom_thresholds)

    # 获取掩膜文件路径列表
    target_masks_paths, reference_masks_paths = _get_mask_files(subject_id)

    # 检查必需的掩膜文件是否存在
    # 注意：如果掩膜文件缺失，我们仍然尝试处理存在的，但会记录警告
    existing_target_masks = _check_required_files(target_masks_paths)
    existing_reference_masks = _check_required_files(reference_masks_paths)

    if not existing_target_masks and not existing_reference_masks:
        logger.error(f"❌ 受试者 {subject_id} 没有任何可用的靶区或参考区掩膜文件。无法继续计算SUVR。")
        return {'success': False, 'error': "没有可用的掩膜文件"}

    # 初始化结果存储字典
    results: Dict[str, Any] = {
        'success': False,
        'target_means': {},        # 存储 {mask_base_name: mean_value}
        'reference_means': {},     # 存储 {mask_base_name: mean_value}
        'suvr_values': {},         # 存储 {simple_ref_name: suvr}
        'judgments': {},
        'output_files': []        # 存储所有生成的 roi_mean 和 roi_stats 文件路径
    }

    # --------------------------------------------------------------------------
    # 1. 计算所有靶区掩膜和参考区掩膜内的平均值
    #    并将 _summary_mean.txt 和 _summary_stats.txt 保存到变体特定目录
    # --------------------------------------------------------------------------
    logger.info(f"受试者 {subject_id} (变体: {variant_tag}): 开始计算ROI均值...")

    # 处理靶区
    for mask_path in existing_target_masks:
        mask_base_name = mask_path.name.split('.')[0] # 例如: "composite", "cingulate_mask"
        # 调用新的 calculate_roi_mean，传递 variant_tag
        success, mean_val, mean_f, stats_f = calculate_roi_mean(
            subject_id, mask_path, pet_file, variant_tag, output_dir_override
        )
        if success and mean_val is not None:
            results['target_means'][mask_base_name] = mean_val
        if mean_f: results['output_files'].append(str(mean_f))
        if stats_f: results['output_files'].append(str(stats_f))

    # 处理参考区
    for mask_path in existing_reference_masks:
        mask_base_name = mask_path.name.split('.')[0] # 例如: "ref_cerebellumgm"
        success, mean_val, mean_f, stats_f = calculate_roi_mean(
            subject_id, mask_path, pet_file, variant_tag, output_dir_override
        )
        if success and mean_val is not None:
            results['reference_means'][mask_base_name] = mean_val
        if mean_f: results['output_files'].append(str(mean_f))
        if stats_f: results['output_files'].append(str(stats_f))

    # 检查是否成功计算了任何均值，特别是复合靶区均值，它是计算SUVR的核心
    composite_target_mean = results['target_means'].get('composite')
    if composite_target_mean is None:
        error_msg = f"无法获取关键的 'composite' 靶区平均值 (受试者: {subject_id}, 变体: {variant_tag})。SUVR计算无法进行。"
        logger.error(f"❌ {error_msg}")
        results['error'] = error_msg
        # 即使 composite mean 失败，之前的 roi mean/stats 文件也已生成，这里不将 success 设为 True
        return results

    # --------------------------------------------------------------------------
    # 2. 计算SUVR值 (基于 'composite' 靶区均值和各参考区均值)
    # --------------------------------------------------------------------------
    logger.info(f"受试者 {subject_id} (变体: {variant_tag}): 计算SUVR值...")
    for ref_mask_base_name, ref_mean_val in results['reference_means'].items():
        # ref_mask_base_name 是如 "ref_cerebellumgm"
        # 用于 SUVR 字典的键应该是简化名，如 "cerebellumgm"
        simple_ref_name = ref_mask_base_name.replace("ref_", "")

        if ref_mean_val is not None and ref_mean_val > 1e-9: # 避免除以零或非常小的值
            suvr = composite_target_mean / ref_mean_val
            results['suvr_values'][simple_ref_name] = suvr
        else:
            logger.warning(
                f"⚠️ 参考区 {simple_ref_name} 的平均值为零或无效 ({ref_mean_val})，无法计算其SUVR (受试者: {subject_id}, 变体: {variant_tag})"
            )
            results['suvr_values'][simple_ref_name] = None # 或者标记为 'N/A'

    # --------------------------------------------------------------------------
    # 2.5. 计算各个脑区相对于全小脑的SUVR值
    # --------------------------------------------------------------------------
    logger.info(f"受试者 {subject_id} (变体: {variant_tag}): 计算各脑区相对于全小脑的SUVR值...")
    wholecerebellum_mean = results['reference_means'].get('ref_wholecerebellum')
    if wholecerebellum_mean is not None and wholecerebellum_mean > 1e-9:
        target_regions = ['cingulate_mask', 'frontal_mask', 'parietal_mask', 'temporal_mask']
        for target_region in target_regions:
            target_mean = results['target_means'].get(target_region)
            if target_mean is not None and target_mean > 1e-9:
                region_name = target_region.replace('_mask', '')  # cingulate_mask -> cingulate
                suvr_key = f"{region_name}_wholecerebellum"
                suvr = target_mean / wholecerebellum_mean
                results['suvr_values'][suvr_key] = suvr
            else:
                region_name = target_region.replace('_mask', '')
                suvr_key = f"{region_name}_wholecerebellum"
                logger.warning(
                    f"⚠️ 靶区 {region_name} 的平均值为零或无效 ({target_mean})，无法计算其相对于全小脑的SUVR (受试者: {subject_id}, 变体: {variant_tag})"
                )
                results['suvr_values'][suvr_key] = None
    else:
        logger.warning(
            f"⚠️ 全小脑参考区的平均值为零或无效 ({wholecerebellum_mean})，无法计算各脑区相对于全小脑的SUVR (受试者: {subject_id}, 变体: {variant_tag})"
        )
        # 为各脑区设置None值
        target_regions = ['cingulate', 'frontal', 'parietal', 'temporal']
        for region_name in target_regions:
            suvr_key = f"{region_name}_wholecerebellum"
            results['suvr_values'][suvr_key] = None

    # --------------------------------------------------------------------------
    # 3. 进行判断 (基于计算出的SUVR值和阈值)
    # --------------------------------------------------------------------------
    results['judgments'] = _make_judgments(results['suvr_values'], thresholds)

    # --------------------------------------------------------------------------
    # 4. 将SUVR的详细汇总结果写入文件 (例如 suvr_results-2-3-1.txt)
    # --------------------------------------------------------------------------
    # variant_tag 用于文件名和文件内容
    suvr_summary_file_path = _write_suvr_results_to_file(
        subject_id, results, variant_tag, output_dir_override
    )

    if suvr_summary_file_path:
        results['result_file'] = str(suvr_summary_file_path)
        results['output_files'].append(str(suvr_summary_file_path))
        results['success'] = True # 标记整个SUVR计算流程成功
        logger.info(f"✅ 受试者 {subject_id} (变体: {variant_tag}): SUVR 计算成功完成。摘要: {suvr_summary_file_path}")
    else:
        # 如果写入汇总文件失败，整个过程也视为部分失败
        logger.error(f"❌ 未能写入SUVR汇总文件 (受试者: {subject_id}, 变体: {variant_tag})。")
        results['error'] = results.get('error', "") + " 未能写入SUVR汇总文件。"
        # success 保持 False

    # --------------------------------------------------------------------------
    # 5. 更新CSV汇总文件 (这一步将在高层函数中处理，这里只返回计算结果)
    #    旧代码中的 update_suvr_summary 将在 process_subject_suvr 或更高层调用
    # --------------------------------------------------------------------------

    return results


def _initialize_csv_file(csv_file: Path, include_variant_column: bool = False) -> None:
    """
    初始化CSV文件。如果文件不存在，则创建并写入表头。
    如果文件已存在，则不执行任何操作，以避免重复写入表头。

    参数:
        csv_file: CSV文件路径。
        include_variant_column: 是否在表头中包含 'vTag1, vTag2, vTag3' 列。
    """
    try:
        if not csv_file.parent.exists():
            csv_file.parent.mkdir(parents=True, exist_ok=True)
            logger.info(f"创建目录: {csv_file.parent}")

        if not csv_file.exists(): # 关键：仅在文件不存在时写入表头
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                header = []
                header.extend(CSV_COLUMNS['subject'])
                if include_variant_column:
                    header.extend(CSV_COLUMNS['variant_parts']) # 使用新的vTag列名
                for group_key in ['target_means', 'reference_means', 'suvr_values', 'judgments', 'regional_suvr']:
                    header.extend(CSV_COLUMNS[group_key])
                writer.writerow(header)
                logger.info(f"✅ 初始化CSV文件并写入表头: {csv_file}")
    except Exception as e:
        logger.error(f"❌ 初始化CSV文件 {csv_file} 失败: {e}", exc_info=True)

def _prepare_csv_row(subject_id: str, results: Dict[str, Any], variant_tag_for_csv: Optional[str] = None) -> List[str]:
    """
    根据SUVR计算结果准备用于写入CSV文件的一行数据。
    变体标签将被拆分为vTag1, vTag2, vTag3。

    参数:
        subject_id: 受试者ID。
        results: SUVR计算结果字典。
        variant_tag_for_csv: 原始的PET变体标识。如果为None，则不添加vTag列。

    返回:
        准备好的数据行列表。
    """
    row: List[str] = [subject_id]

    if variant_tag_for_csv is not None:
        v1, v2, v3 = "", "", ""
        original_tag = variant_tag_for_csv

        if not original_tag:  # 原始标签是空字符串
            v1 = "standard"
        else:
            tag_to_split = original_tag
            if original_tag.startswith('-') and len(original_tag) > 1:
                tag_to_split = original_tag[1:]
            elif original_tag == '-':
                tag_to_split = "dash" # 特殊处理单个连字符
            
            parts = tag_to_split.split('-', 2) # 最多分割2次，得到3个部分

            if len(parts) >= 1:
                v1 = parts[0]
            if len(parts) >= 2:
                v2 = parts[1]
            if len(parts) >= 3:
                v3 = parts[2]
        
        row.extend([v1, v2, v3])
    # 如果 variant_tag_for_csv is None，则不添加这三列，
    # 这与 _initialize_csv_file 中 include_variant_column=False 时表头不包含这些列对应

    # ... (其余部分的映射逻辑保持不变，追加到row列表)
    target_means_map = {
        "Composite_Count": "composite", "Cingulate_Count": "cingulate_mask",
        "Frontal_Count": "frontal_mask", "Parietal_Count": "parietal_mask",
        "Temporal_Count": "temporal_mask"
    }
    for csv_col_name in CSV_COLUMNS['target_means']:
        result_key = target_means_map.get(csv_col_name)
        value = results.get('target_means', {}).get(result_key)
        row.append(f"{value:.4f}" if isinstance(value, float) else (str(value) if value is not None else ''))

    reference_means_map = {
        "CerebellumGM_Ref": "ref_cerebellumgm", "Brainstem_Ref": "ref_brainstem",
        "WholeCerebellum_Ref": "ref_wholecerebellum", "SubcorticalWM_Ref": "ref_subcorticalwm",
        "SubcorticalWM_FSM8_Thr07_Ref": "ref_subcorticalwm_fsm8_thr07", "SubcorticalWM_E1_Ref": "ref_subcorticalwm_erode1",
        "SubcorticalWM_E2_Ref": "ref_subcorticalwm_erode2", "Composite_Ref": "ref_composite",
        "Composite_FSM8_Thr07_Ref": "ref_composite_fsm8_thr07", "CompositeE1_Ref": "ref_composite_e1",
        "CompositeE2_Ref": "ref_composite_e2"
    }
    for csv_col_name in CSV_COLUMNS['reference_means']:
        result_key = reference_means_map.get(csv_col_name)
        value = results.get('reference_means', {}).get(result_key)
        row.append(f"{value:.4f}" if isinstance(value, float) else (str(value) if value is not None else ''))

    suvr_values_map = {
        "CerebellumGM_SUVR": "cerebellumgm", "Brainstem_SUVR": "brainstem",
        "WholeCerebellum_SUVR": "wholecerebellum", "SubcorticalWM_SUVR": "subcorticalwm",
        "SubcorticalWM_FSM8_Thr07_SUVR": "subcorticalwm_fsm8_thr07", "SubcorticalWM_E1_SUVR": "subcorticalwm_erode1",
        "SubcorticalWM_E2_SUVR": "subcorticalwm_erode2", "Composite_SUVR": "composite",
        "Composite_FSM8_Thr07_SUVR": "composite_fsm8_thr07", "CompositeE1_SUVR": "composite_e1",
        "CompositeE2_SUVR": "composite_e2"
    }
    for csv_col_name in CSV_COLUMNS['suvr_values']:
        result_key = suvr_values_map.get(csv_col_name)
        value = results.get('suvr_values', {}).get(result_key)
        row.append(f"{value:.4f}" if isinstance(value, float) else (str(value) if value is not None else ''))

    judgments_map = {
        "WholeCerebellum_Status": "wholecerebellum", "Composite_Status": "composite",
        "Composite_FSM8_Thr07_Status": "composite_fsm8_thr07",
        "CompositeE1_Status": "composite_e1", "CompositeE2_Status": "composite_e2"
    }
    for csv_col_name in CSV_COLUMNS['judgments']:
        result_key = judgments_map.get(csv_col_name)
        value = results.get('judgments', {}).get(result_key)
        row.append(str(value) if value is not None else '')

    regional_suvr_map = {
        "Cingulate_WholeCerebellum_SUVR": "cingulate_wholecerebellum",
        "Frontal_WholeCerebellum_SUVR": "frontal_wholecerebellum", 
        "Parietal_WholeCerebellum_SUVR": "parietal_wholecerebellum",
        "Temporal_WholeCerebellum_SUVR": "temporal_wholecerebellum"
    }
    for csv_col_name in CSV_COLUMNS['regional_suvr']:
        result_key = regional_suvr_map.get(csv_col_name)
        value = results.get('suvr_values', {}).get(result_key)
        row.append(f"{value:.4f}" if isinstance(value, float) else (str(value) if value is not None else ''))

    return row


def update_suvr_summary(
    subject_id: str,
    results_for_variant: Dict[str, Any],
    variant_tag: str, 
    sheet_dir_override: Optional[Path] = None
) -> bool:
    """
    更新三种SUVR汇总CSV文件。
    如果CSV文件不存在，则创建并写入表头；否则，直接追加数据行。

    参数:
        subject_id: 受试者ID。
        results_for_variant: 单个变体的SUVR计算结果。
        variant_tag: 原始的PET变体标识。
        sheet_dir_override: 可选的自定义CSV输出目录。

    返回:
        如果所有CSV更新都成功，则返回True，否则返回False。
    """
    overall_success = True
    csv_output_dir = sheet_dir_override if sheet_dir_override else Path(config.SHEET_DIR)
    csv_output_dir.mkdir(parents=True, exist_ok=True) # 确保目录存在

    # --- 模式1: 按变体汇总 (all_subjects_suvr-<processed_variant_tag>.csv) ---
    file_variant_suffix_mode1 = variant_tag if variant_tag else "standard"
    if file_variant_suffix_mode1.startswith('-') and len(file_variant_suffix_mode1) > 1:
        file_variant_suffix_mode1 = file_variant_suffix_mode1[1:]
    elif file_variant_suffix_mode1 == "-":
        file_variant_suffix_mode1 = "dash"
    
    per_variant_csv_filename = f"all_subjects_suvr-{file_variant_suffix_mode1}{CSV_EXTENSION}"
    per_variant_csv_file = csv_output_dir / per_variant_csv_filename
    try:
        _initialize_csv_file(per_variant_csv_file, include_variant_column=False) # 表头不包含vTag列
        row_data_mode1 = _prepare_csv_row(subject_id, results_for_variant, variant_tag_for_csv=None) # 数据不包含vTag
        with open(per_variant_csv_file, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(row_data_mode1)
        logger.info(f"✅ (模式1) 受试者 {subject_id} (变体: {file_variant_suffix_mode1}) SUVR结果已更新/添加至: {per_variant_csv_file}")
    except Exception as e:
        logger.error(f"❌ (模式1) 更新CSV文件 {per_variant_csv_file} 失败: {e}", exc_info=True)
        overall_success = False

    # --- 模式2: 按患者ID分类 ({patient_id}_suvr_summary.csv) ---
    per_patient_csv_filename = f"{subject_id}_suvr_summary{CSV_EXTENSION}"
    per_patient_csv_file = csv_output_dir / per_patient_csv_filename
    try:
        _initialize_csv_file(per_patient_csv_file, include_variant_column=True) # 表头包含vTag列
        row_data_mode2 = _prepare_csv_row(subject_id, results_for_variant, variant_tag_for_csv=variant_tag) # 数据包含vTag
        with open(per_patient_csv_file, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(row_data_mode2)
        logger.info(f"✅ (模式2) 受试者 {subject_id} (变体: {variant_tag if variant_tag else 'standard'}) SUVR结果已更新/添加至: {per_patient_csv_file}")
    except Exception as e:
        logger.error(f"❌ (模式2) 更新CSV文件 {per_patient_csv_file} 失败: {e}", exc_info=True)
        overall_success = False

    # --- 模式3: 单一全体汇总 (all_patients_all_variants_suvr.csv) ---
    all_variants_csv_filename = f"all_patients_all_variants_suvr{CSV_EXTENSION}"
    all_variants_csv_file = csv_output_dir / all_variants_csv_filename
    try:
        _initialize_csv_file(all_variants_csv_file, include_variant_column=True) # 表头包含vTag列
        row_data_mode3 = _prepare_csv_row(subject_id, results_for_variant, variant_tag_for_csv=variant_tag) # 数据包含vTag
        with open(all_variants_csv_file, 'a', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(row_data_mode3)
        logger.info(f"✅ (模式3) 受试者 {subject_id} (变体: {variant_tag if variant_tag else 'standard'}) SUVR结果已更新/添加至: {all_variants_csv_file}")
    except Exception as e:
        logger.error(f"❌ (模式3) 更新CSV文件 {all_variants_csv_file} 失败: {e}", exc_info=True)
        overall_success = False

    return overall_success


def process_subject_variant_suvr(
    subject_id: str,
    variant_tag: str,
    custom_thresholds: Optional[Dict[str, float]] = None,
    output_dir_override: Optional[Path] = None, # 父统计目录，例如 .../stats/
    sheet_dir_override: Optional[Path] = None  # CSV输出目录
) -> Dict[str, Any]:
    """
    处理单个受试者的单个PET变体的SUVR计算，并更新CSV。

    参数:
        subject_id: 受试者ID。
        variant_tag: PET变体标识 (例如 "-1", "" 表示标准)。
        custom_thresholds: 可选的自定义阈值。
        output_dir_override: 可选的自定义父输出目录 (用于保存 .txt 文件，例如 .../stats/ )。
        sheet_dir_override: 可选的自定义CSV输出目录。

    返回:
        包含该变体SUVR计算结果的字典。
    """
    subject_id = utils.format_patient_id(subject_id)
    logger.debug(f"[CHECKPOINT] process_subject_variant_suvr - Entering for Subject: {subject_id}, Variant: '{variant_tag}', OutputDirOverride: {output_dir_override}, SheetDirOverride: {sheet_dir_override}")
    variant_display_name = f"变体 '{variant_tag if variant_tag else 'standard'}'"
    logger.info(f"🔄 开始处理受试者 {subject_id} {variant_display_name} 的SUVR计算...")

    pet_file = _get_registrated_pet_file(subject_id, variant_tag)
    logger.debug(f"[CHECKPOINT] process_subject_variant_suvr - Registered PET file for Subject {subject_id}, Variant '{variant_tag}': {pet_file}")
    if not pet_file.exists():
        error_msg = f"注册后的PET文件不存在: {pet_file}"
        logger.error(f"❌ {error_msg} (受试者: {subject_id}, {variant_display_name}) ")
        return {'success': False, 'error': error_msg, 'variant_tag': variant_tag}

    # 调用核心SUVR计算函数，传递 output_dir_override (这是父统计目录)
    # calculate_suvr_values 内部会使用 variant_tag 和这个父目录来创建子目录
    variant_results = calculate_suvr_values(
        subject_id, pet_file, variant_tag, custom_thresholds, output_dir_override
    )

    if variant_results.get('success'):
        logger.info(f"✅ 受试者 {subject_id} {variant_display_name} SUVR计算成功。")
        
        # 更新CSV汇总文件
        csv_update_success = update_suvr_summary(
            subject_id, variant_results, variant_tag, sheet_dir_override
        )
        if not csv_update_success:
            logger.warning(f"⚠️ 受试者 {subject_id} {variant_display_name} 的部分CSV更新可能失败。")
            # 即使CSV更新失败，SUVR计算本身是成功的
        variant_results['csv_update_attempted'] = True
        variant_results['csv_update_success_all'] = csv_update_success
        
        # 检查输出文件的完整性
        files_check_result = check_variant_output_files(subject_id, variant_tag, output_dir_override)
        variant_results['files_check'] = files_check_result
        if not files_check_result['success']:
            logger.warning(f"⚠️ 受试者 {subject_id} {variant_display_name} 的输出文件不完整，可能需要重新处理。")
            # 即使文件检查显示不完整，整体计算过程可能仍然成功
            # 只是通过files_check字段提供更多信息，不影响主success标志
    else:
        logger.error(f"❌ 受试者 {subject_id} {variant_display_name} SUVR计算失败。错误: {variant_results.get('error')}")

    variant_results['variant_tag'] = variant_tag # 确保返回结果中包含原始variant_tag
    return variant_results


def _get_optimal_workers(requested_workers: int, task_count: int) -> int:
    """
    根据请求的worker数量、CPU核心数和任务数量确定最优的并行worker数量。
    """
    cpu_count = os.cpu_count() or 1 # 至少为1
    # 确保 worker 数量不超过 CPU核心数 或 任务数
    optimal_workers = min(requested_workers, cpu_count, task_count)
    # 避免使用所有核心，为系统保留一些资源，特别是当CPU核心较多时
    if cpu_count > 2 and optimal_workers == cpu_count:
        optimal_workers = cpu_count - 1
    optimal_workers = max(1, optimal_workers) # 至少有一个worker

    if optimal_workers != requested_workers:
        logger.info(f"ℹ️ 并行worker数量调整: 请求 {requested_workers} -> 优化为 {optimal_workers} (CPU核心: {cpu_count}, 任务数: {task_count})")
    return optimal_workers


def calculate_suvr_for_patients(
    patient_ids: List[str],
    max_workers: int = 4,
    custom_thresholds: Optional[Dict[str, float]] = None,
    output_dir_override: Optional[Path] = None, # 父统计目录，如 .../00x/stats/
    sheet_dir_override: Optional[Path] = None   # CSV输出目录，如 .../recon_stats_sheets/
) -> Dict[str, Dict[str, Any]]:
    """
    为列表中的多个受试者并行计算所有PET变体的SUVR。

    参数:
        patient_ids: 受试者ID列表。
        max_workers: 最大并行工作进程数。
        custom_thresholds: 可选的自定义阈值，将应用于所有受试者和变体。
        output_dir_override: 可选的自定义父统计输出目录 (用于 .txt 文件)。
        sheet_dir_override: 可选的自定义CSV输出目录。

    返回:
        一个字典，键是受试者ID，值是另一个字典，
        该字典的键是变体标识('standard'或原始tag)，值是该变体的SUVR计算结果。
    """
    if not patient_ids:
        logger.warning("⚠️ 未提供受试者ID，不执行SUVR计算。")
        return {}

    formatted_patient_ids = [utils.format_patient_id(pid) for pid in patient_ids]
    logger.info(f"准备为 {len(formatted_patient_ids)} 个受试者计算SUVR (最多 {max_workers} 个并行进程)..." )

    # 收集所有任务 (subject_id, variant_tag)
    tasks_to_run: List[Tuple[str, str]] = []
    for pid in formatted_patient_ids:
        # 使用 registration.find_pet_variants 获取该受试者的所有PET变体及其原始数据路径
        # find_pet_variants 应该返回 List[Tuple[Path, str]], Path是PET文件路径, str是variant_tag
        pet_variants_info = registration.find_pet_variants(pid)
        logger.debug(f"[CHECKPOINT] Subject {pid} - Found PET variants info: {pet_variants_info}")
        if not pet_variants_info:
            logger.warning(f"⚠️ 受试者 {pid} 未找到可处理的PET变体。跳过该受试者。")
            continue
        for _, variant_tag in pet_variants_info:
            tasks_to_run.append((pid, variant_tag))

    if not tasks_to_run:
        logger.warning("⚠️ 没有找到任何可处理的受试者-变体组合。")
        return {}

    optimal_workers = _get_optimal_workers(max_workers, len(tasks_to_run))
    all_results: Dict[str, Dict[str, Any]] = {pid: {} for pid in formatted_patient_ids}

    with tqdm(total=len(tasks_to_run), desc="SUVR计算进度", unit="变体") as pbar:
        with concurrent.futures.ProcessPoolExecutor(max_workers=optimal_workers) as executor:
            future_to_task: Dict[concurrent.futures.Future, Tuple[str, str]] = {}
            for subject_id, variant_tag in tasks_to_run:
                future = executor.submit(
                    process_subject_variant_suvr,
                    subject_id,
                    variant_tag,
                    custom_thresholds,
                    output_dir_override, # 父统计目录
                    sheet_dir_override   # CSV输出目录
                )
                future_to_task[future] = (subject_id, variant_tag)

            for future in concurrent.futures.as_completed(future_to_task):
                subject_id, variant_tag = future_to_task[future]
                try:
                    variant_result = future.result()
                    # 使用原始 variant_tag 或 'standard' (如果为空) 作为结果字典的键
                    result_variant_key = variant_tag if variant_tag else 'standard'
                    all_results.setdefault(subject_id, {})[result_variant_key] = variant_result
                except Exception as e:
                    logger.error(f"❌ 处理受试者 {subject_id} (变体: {variant_tag}) 时发生严重错误: {e}", exc_info=True)
                    result_variant_key = variant_tag if variant_tag else 'standard'
                    all_results.setdefault(subject_id, {})[result_variant_key] = {
                        'success': False,
                        'error': f'并行处理中发生意外错误: {str(e)}',
                        'variant_tag': variant_tag
                    }
                finally:
                    pbar.update(1)

    _log_processing_summary(all_results)
    return all_results


def _log_processing_summary(all_results: Dict[str, Dict[str, Any]]) -> None:
    """
    记录SUVR处理结果的摘要信息。
    """
    if not all_results:
        logger.info("SUVR处理完成，没有处理任何数据。")
        return

    total_subjects_processed = 0
    successful_subjects = 0
    total_variants_processed = 0
    successful_variants = 0
    failed_subject_variants: List[str] = []

    for subject_id, variant_results_map in all_results.items():
        if not variant_results_map: # 如果某个subject_id没有变体数据 (可能因为最初就没找到变体)
            continue

        total_subjects_processed +=1
        subject_had_at_least_one_success = False
        for variant_tag_key, result in variant_results_map.items():
            total_variants_processed += 1
            if result.get('success'):
                successful_variants += 1
                subject_had_at_least_one_success = True
            else:
                failed_subject_variants.append(f"{subject_id} (变体: {variant_tag_key})")

        if subject_had_at_least_one_success:
            successful_subjects += 1

    logger.info("🎉 SUVR 批量处理完成统计:")
    if total_subjects_processed > 0:
        success_rate_subjects = (successful_subjects / total_subjects_processed) * 100
        logger.info(f"  - 受试者: {successful_subjects}/{total_subjects_processed} 处理成功 ({success_rate_subjects:.1f}%)")
    else:
        logger.info("  - 受试者: 0/0 (未处理任何受试者)")

    if total_variants_processed > 0:
        success_rate_variants = (successful_variants / total_variants_processed) * 100
        logger.info(f"  - PET变体: {successful_variants}/{total_variants_processed} 处理成功 ({success_rate_variants:.1f}%)")
    else:
        logger.info("  - PET变体: 0/0 (未处理任何变体)")

    if failed_subject_variants:
        logger.warning("⚠️ 以下受试者-变体组合处理失败:")
        for item in failed_subject_variants[:10]: # 最多显示10条
            logger.warning(f"    - {item}")
        if len(failed_subject_variants) > 10:
            logger.warning(f"    ... 以及其他 {len(failed_subject_variants) - 10} 个失败项。")


def check_variant_output_files(
    subject_id: str,
    variant_tag: str,
    output_dir_override: Optional[Path] = None
) -> Dict[str, Any]:
    """
    检查特定受试者、特定变体的SUVR处理输出文件是否完整。

    参数:
        subject_id: 受试者ID。
        variant_tag: PET变体标识 (例如 "-1", "2-3-1", "")。
        output_dir_override: 可选的自定义父输出目录 (覆盖 config.SUBJECTS_DIR/<subject_id>/stats)。

    返回:
        包含检查结果的字典，包括 'success', 'missing_files' 等信息。
    """
    subject_id = utils.format_patient_id(subject_id)
    
    # 获取变体特定的统计目录路径
    variant_stats_dir = _get_variant_stats_dir(subject_id, variant_tag, output_dir_override)
    variant_display = variant_tag if variant_tag else "standard"
    
    # 定义应该生成的文件列表
    expected_files = [
        # 参考区域平均值/统计文件
        "ref_composite_e2_summary_stats.txt", "ref_composite_e2_summary_mean.txt",
        "ref_composite_e1_summary_stats.txt", "ref_composite_e1_summary_mean.txt",
        "ref_composite_fsm8_thr07_summary_stats.txt", "ref_composite_fsm8_thr07_summary_mean.txt",
        "ref_composite_summary_stats.txt", "ref_composite_summary_mean.txt",
        "ref_subcorticalwm_summary_stats.txt", "ref_subcorticalwm_summary_mean.txt",
        "ref_subcorticalwm_fsm8_thr07_summary_stats.txt", "ref_subcorticalwm_fsm8_thr07_summary_mean.txt",
        "ref_subcorticalwm_erode1_summary_stats.txt", "ref_subcorticalwm_erode1_summary_mean.txt",
        "ref_subcorticalwm_erode2_summary_stats.txt", "ref_subcorticalwm_erode2_summary_mean.txt",
        "ref_wholecerebellum_summary_stats.txt", "ref_wholecerebellum_summary_mean.txt",
        "ref_brainstem_summary_stats.txt", "ref_brainstem_summary_mean.txt",
        "ref_cerebellumgm_summary_stats.txt", "ref_cerebellumgm_summary_mean.txt",
        
        # 靶区平均值/统计文件
        "temporal_mask_summary_stats.txt", "temporal_mask_summary_mean.txt",
        "parietal_mask_summary_stats.txt", "parietal_mask_summary_mean.txt",
        "frontal_mask_summary_stats.txt", "frontal_mask_summary_mean.txt",
        "cingulate_mask_summary_stats.txt", "cingulate_mask_summary_mean.txt",
        "composite_summary_stats.txt", "composite_summary_mean.txt",
    ]
    
    # 添加SUVR结果文件 (名称格式根据变体tag处理)
    file_variant_suffix = variant_tag if variant_tag else "standard"
    if file_variant_suffix.startswith('-') and len(file_variant_suffix) > 1:
        file_variant_suffix = file_variant_suffix[1:]
    elif file_variant_suffix == "-":
        file_variant_suffix = "dash"
    
    expected_files.append(f"suvr_results-{file_variant_suffix}.txt")
    
    # 检查文件是否存在
    missing_files = []
    for file_name in expected_files:
        file_path = variant_stats_dir / file_name
        if not file_path.exists():
            missing_files.append(file_name)
    
    # 准备检查结果
    check_result = {
        'success': len(missing_files) == 0,
        'subject_id': subject_id,
        'variant_tag': variant_tag,
        'variant_stats_dir': str(variant_stats_dir),
        'expected_files_count': len(expected_files),
        'missing_files': missing_files,
        'missing_files_count': len(missing_files)
    }
    
    if check_result['success']:
        logger.info(f"✅ 受试者 {subject_id} (变体: {variant_display}) 的所有 {len(expected_files)} 个预期输出文件都已存在")
    else:
        logger.warning(f"⚠️ 受试者 {subject_id} (变体: {variant_display}) 缺少 {len(missing_files)}/{len(expected_files)} 个预期输出文件")
        if len(missing_files) <= 10:
            logger.warning(f"缺失的文件: {', '.join(missing_files)}")
        else:
            logger.warning(f"缺失的文件(部分): {', '.join(missing_files[:10])}... 等")
    
    return check_result

