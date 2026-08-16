# modules/clear.py
import os
import logging
from pathlib import Path
from typing import List, Dict, Callable, Union
import shutil

from . import utils
from . import registration  # 用于查找变体
import config

logger = logging.getLogger(__name__)

# ========== 通用变体目录发现函数 ==========

def _discover_recon_variant_dirs(subject_id: str, child_dir_name: str) -> List[Path]:
    """
    在重建目录中发现指定子目录（如 'pet' 或 'pet_pvc'）下的变体目录，
    优先基于原始PET文件推导；若未找到原始文件，则回退直接扫描变体目录。

    参数:
        subject_id: 三位患者ID，例如 "024"
        child_dir_name: 子目录名，'pet' 或 'pet_pvc'

    返回:
        变体目录的路径列表（存在的目录）
    """
    subject_id = utils.format_patient_id(subject_id)
    variant_dirs: List[Path] = []

    # 尝试通过 data/pet 下原始PET文件推导
    pet_variants = registration.find_pet_variants(subject_id)

    if pet_variants:
        # pet 下的变体目录可以直接通过内部函数获取
        if child_dir_name == 'pet':
            for _, variant_tag in pet_variants:
                pet_variant_dir, _, _, _ = registration._get_pet_variant_info(subject_id, variant_tag)
                if pet_variant_dir.is_dir():
                    variant_dirs.append(pet_variant_dir)
        # pet_pvc 下的变体目录名来自PET文件名（去掉 .nii.gz）
        elif child_dir_name == 'pet_pvc':
            for pet_file_path, _ in pet_variants:
                variant_dir_name = pet_file_path.name.removesuffix('.nii.gz')
                pvc_variant_dir = config.RECON_DIR / subject_id / 'pet_pvc' / variant_dir_name
                if pvc_variant_dir.is_dir():
                    variant_dirs.append(pvc_variant_dir)
    
    # 如果未通过原始PET推导到任何目录，则回退：直接扫描重建目录
    if not variant_dirs:
        base_dir = Path(config.SUBJECTS_DIR) / subject_id / child_dir_name
        if base_dir.is_dir():
            for sub in base_dir.iterdir():
                if sub.is_dir():
                    variant_dirs.append(sub)
        else:
            logger.debug(f"患者 {subject_id} 的重建{child_dir_name}目录不存在：{base_dir}")

    return variant_dirs


def _confirm_deletion(files_to_delete: List[Path], is_dir: bool = False) -> bool:
    """
    显示待删除文件或目录列表并请求用户确认。
    
    参数:
        files_to_delete: 待删除文件或目录的Path对象列表
        is_dir: 标记删除的是否为目录
        
    返回:
        如果用户确认删除则返回True，否则返回False
    """
    if not files_to_delete:
        print("没有找到需要清理的内容。")
        return False

    item_type = "目录" if is_dir else "文件"
    print(f"\n将要删除以下{item_type}:")
    print("=" * 60)
    
    # 如果文件过多，进行分页或摘要显示
    if len(files_to_delete) > 20:
        print(f"总共将删除 {len(files_to_delete)} 个{item_type}。")
        print("部分列表如下:")
        for path in files_to_delete[:10]:
            print(f" - {path}")
        print("...")
        for path in files_to_delete[-5:]:
            print(f" - {path}")
        
        try:
            show_all = input(f"\n是否要查看所有待删除{item_type}的完整列表? (y/n): ").lower()
            if show_all == 'y':
                print("-" * 60)
                for i, path in enumerate(files_to_delete):
                    print(f" - {path}")
                    if (i + 1) % 20 == 0 and i + 1 < len(files_to_delete):
                        input("--- 按Enter键继续 ---")
        except KeyboardInterrupt:
            print("\n操作已取消。")
            return False
    else:
        for path in files_to_delete:
            print(f" - {path}")

    print("=" * 60)
    
    try:
        confirm = input(f"确认要删除这些{item_type}吗? (y/n): ").lower()
        return confirm == 'y'
    except KeyboardInterrupt:
        print("\n操作已取消。")
        return False


def _find_registrated_pet_mgz(patient_ids: List[str]) -> List[Path]:
    """
    为指定患者查找所有 'registrated_pet.mgz' 文件。
    """
    files_to_find = []
    logger.info(f"正在为 {len(patient_ids)} 个患者查找 'registrated_pet.mgz' 文件...")
    
    for pid in patient_ids:
        subject_id = utils.format_patient_id(pid)

        # 统一使用通用发现函数，包含回退逻辑
        pet_variant_dirs = _discover_recon_variant_dirs(subject_id, 'pet')
        if not pet_variant_dirs:
            logger.debug(f"患者 {subject_id} 未找到任何PET变体目录，跳过。")
            continue

        for pet_variant_dir in pet_variant_dirs:
            file_path = pet_variant_dir / 'registrated_pet.mgz'
            if file_path.exists():
                files_to_find.append(file_path)

    return files_to_find


def clean_registrated_pet_mgz(patient_ids: List[str]):
    """
    清理 'registrated_pet.mgz' 文件。
    """
    files_to_delete = _find_registrated_pet_mgz(patient_ids)
    
    if _confirm_deletion(files_to_delete):
        deleted_count = 0
        failed_count = 0
        print("\n正在删除文件...")
        for file_path in files_to_delete:
            try:
                file_path.unlink()
                deleted_count += 1
                logger.debug(f"已删除: {file_path}")
            except OSError as e:
                failed_count += 1
                logger.error(f"删除文件失败: {file_path}, 错误: {e}")
        
        print("\n清理完成。")
        print(f"✅ 成功删除 {deleted_count} 个文件。")
        if failed_count > 0:
            print(f"❌ 删除失败 {failed_count} 个文件。详情请查看日志。")
    else:
        print("\n操作已取消，未删除任何文件。")


def _find_pvc_aux_folders(patient_ids: List[str]) -> List[Path]:
    """
    为指定患者查找所有 'aux' 文件夹。
    这些文件夹由 pvc_suvr_calculator.py 生成。
    """
    dirs_to_find = []
    logger.info(f"正在为 {len(patient_ids)} 个患者查找 'aux' 文件夹...")

    for pid in patient_ids:
        subject_id = utils.format_patient_id(pid)
        
        # 使用通用发现函数找到 pet_pvc 下的变体目录（带回退逻辑）
        pvc_variant_dirs = _discover_recon_variant_dirs(subject_id, 'pet_pvc')
        if not pvc_variant_dirs:
            logger.debug(f"患者 {subject_id} 未找到任何PVC变体目录，跳过。")
            continue

        # 遍历变体目录下的所有PSF输出目录，查找 aux
        for variant_pvc_dir in pvc_variant_dirs:
            for psf_dir in variant_pvc_dir.iterdir():
                if not psf_dir.is_dir():
                    continue
                aux_dir = psf_dir / 'aux'
                if aux_dir.is_dir():
                    dirs_to_find.append(aux_dir)

    return dirs_to_find


def clean_pvc_aux_folders(patient_ids: List[str]):
    """
    清理由pvc_suvr_calculator.py生成的 'aux' 临时文件夹。
    """
    dirs_to_delete = _find_pvc_aux_folders(patient_ids)
    
    if _confirm_deletion(dirs_to_delete, is_dir=True):
        deleted_count = 0
        failed_count = 0
        print("\n正在删除目录...")
        for dir_path in dirs_to_delete:
            try:
                shutil.rmtree(dir_path)
                deleted_count += 1
                logger.debug(f"已删除目录: {dir_path}")
            except OSError as e:
                failed_count += 1
                logger.error(f"删除目录失败: {dir_path}, 错误: {e}")
        
        print("\n清理完成。")
        print(f"✅ 成功删除 {deleted_count} 个目录。")
        if failed_count > 0:
            print(f"❌ 删除失败 {failed_count} 个目录。详情请查看日志。")
    else:
        print("\n操作已取消，未删除任何目录。")


def placeholder_function(patient_ids: List[str]):
    """
    未来功能的占位符。
    """
    print("\n此功能正在开发中，敬请期待。")


# 清理选项字典，用于构建菜单和分派任务
CLEAN_OPTIONS: Dict[str, Dict[str, Union[str, Callable]]] = {
    '1': {
        'description': "清理重建目录 pet/ 下的 'registrated_pet.mgz' 临时文件",
        'function': clean_registrated_pet_mgz
    },
    '2': {
        'description': "清理由PVC SUVR计算器生成的 'aux' 临时文件夹",
        'function': clean_pvc_aux_folders
    },
    '3': {
        'description': "内容待添加...",
        'function': placeholder_function
    }
}


def run_clear_interactive(patient_ids: List[str]):
    """
    显示交互式清理菜单并执行所选操作。
    这是该模块的主入口函数。
    
    参数:
        patient_ids: 从主程序传入的患者ID列表
    """
    while True:
        print("\n===== 文件清理模块 =====")
        for key, value in CLEAN_OPTIONS.items():
            print(f"{key}. {value['description']}")
        print("q. 退出清理模块")
        print("=========================")
        
        try:
            choice = input("请输入选项: ").strip().lower()
            
            if choice == 'q':
                print("已退出清理模块。")
                break
                
            if choice in CLEAN_OPTIONS:
                selected_option = CLEAN_OPTIONS[choice]
                print(f"\n你选择了: {selected_option['description']}")
                # 调用与选项关联的函数
                selected_option['function'](patient_ids)
                input("\n--- 按Enter键返回主菜单 ---")
            else:
                print("\n无效的选项，请重试。")
        
        except KeyboardInterrupt:
            print("\n\n操作已由用户中断。退出清理模块。")
            break
