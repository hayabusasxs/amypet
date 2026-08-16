# modules/recon_processor.py
import os
import logging
from pathlib import Path
from typing import List, Dict, Optional, Union
import concurrent.futures
from tqdm import tqdm  # 进度显示
import subprocess
import tempfile
import json
import sys

from . import utils
import config

logger = logging.getLogger(__name__)

def run_recon_all(subject_id: str, t1_file: Path, flags: List[str] = None) -> bool:
    """
    为指定患者运行recon-all
    
    参数:
        subject_id: 患者ID
        t1_file: T1结构像文件路径
        flags: 附加的recon-all标志
        
    返回:
        成功返回True，失败返回False
    """
    subject_id = utils.format_patient_id(subject_id)
    
    # 检查受试者目录是否已存在
    subj_dir = Path(config.SUBJECTS_DIR) / subject_id
    orig_exists = subj_dir.exists() and (subj_dir / 'mri' / 'orig' / '001.mgz').exists()
    
    # 准备recon-all命令，确保包含-qcache
    cmd = ['recon-all', '-s', subject_id]
    
    # 仅当受试者目录不存在时才添加-i参数
    if not orig_exists:
        cmd.extend(['-i', str(t1_file)])
    
    cmd.extend(['-all', '-qcache'])  # 确保始终包含-qcache
    
    # 如果是FreeSurfer 8.0版本，添加OpenMP线程设置
    if config.IS_FS_8:
        cmd.extend(['-openmp', str(config.FS8_OPENMP_THREADS)])
    
    # 添加可选标志
    if flags:
        cmd.extend(flags)
    
    try:
        # 执行命令
        result = utils.run_freesurfer_command(cmd, subject_id=subject_id)
        
        logger.info(f"✅ recon-all completed for subject {subject_id}")
        logger.debug(result.stdout)
        
        # 检查结果目录是否存在
        if subj_dir.exists():
            return True
        else:
            logger.error(f"❌ recon-all completed but output directory not found: {subj_dir}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error running recon-all for subject {subject_id}: {e}")
        return False

def generate_subject_info_from_range(start_subj: int, end_subj: int, mr_dir: Union[str, Path]) -> Dict[str, Path]:
    """
    根据受试者ID范围生成subject_info字典
    
    参数:
        start_subj: 起始受试者编号(整数)
        end_subj: 结束受试者编号(整数)
        mr_dir: 包含MR数据的目录
        
    返回:
        字典，键为格式化的患者ID，值为T1文件路径
    """
    subject_info = {}
    
    for i in range(start_subj, end_subj + 1):
        subj_id = utils.format_patient_id(i)
        subj_dir = Path(mr_dir) / subj_id
        
        if not subj_dir.exists():
            logger.warning(f"⚠️ 受试者目录不存在: {subj_dir}")
            continue
            
        # 查找特定命名格式的MR NIfTI文件
        mr_nifti = subj_dir / f"{subj_id}_mr.nii.gz"
        if not mr_nifti.exists():
            # 如果没有找到特定命名的文件，尝试查找任何.nii.gz文件
            nifti_files = list(subj_dir.glob("*.nii.gz"))
            if not nifti_files:
                logger.warning(f"⚠️ 未找到NIfTI文件: {subj_dir}")
                continue
            mr_nifti = nifti_files[0]
            logger.warning(f"⚠️ 使用替代NIfTI文件: {mr_nifti.name}")
            
        # 使用找到的NIfTI文件
        subject_info[subj_id] = mr_nifti
        logger.info(f"✅ 已添加受试者 {subj_id}，使用MR文件: {mr_nifti}")
        
    return subject_info

# 将process_subject函数移到外部
def process_subject(subj_id, t1_file, additional_flags=None):
    """处理单个受试者的recon-all"""
    # 检查受试者目录是否已存在
    subj_dir = Path(config.SUBJECTS_DIR) / subj_id
    orig_exists = subj_dir.exists() and (subj_dir / 'mri' / 'orig' / '001.mgz').exists()
    
    try:
        if orig_exists:
            # 继续处理已存在的受试者，跳过-i参数
            logger.info(f"⚠️ 受试者 {subj_id} 已存在，跳过 -i 参数...")
            cmd = ['recon-all', '-s', subj_id, '-all', '-qcache']
        else:
            # 处理新受试者
            logger.info(f"🆕 处理新受试者 {subj_id}...")
            cmd = ['recon-all', '-s', subj_id, '-i', str(t1_file), '-all', '-qcache']
        
        # 如果是FreeSurfer 8.0版本，添加OpenMP线程设置
        if config.IS_FS_8:
            cmd.extend(['-openmp', str(config.FS8_OPENMP_THREADS)])
        
        # 添加其他可选标志
        if additional_flags:
            cmd.extend(additional_flags)
        
        utils.run_freesurfer_command(cmd, subject_id=subj_id)
        logger.info(f"✅ 受试者 {subj_id} 处理完成")
        return True
    except Exception as e:
        logger.error(f"❌ 处理受试者 {subj_id} 时出错: {e}")
        return False

def run_recon_stage(subj_id: str, t1_file: Path, stage_flag: str, additional_flags: Optional[List[str]] = None) -> bool:
    """运行指定recon-all阶段（例如: 'autorecon1', 'autorecon2', 'autorecon3', 'qcache'）。
    - 对于'autorecon1'，若不存在orig数据，则自动添加-i导入
    - 其他阶段不使用-i参数
    - 在FreeSurfer 8.x下自动添加-openmp线程数
    """
    subj_dir = Path(config.SUBJECTS_DIR) / subj_id
    orig_exists = subj_dir.exists() and (subj_dir / 'mri' / 'orig' / '001.mgz').exists()

    cmd: List[str] = ['recon-all', '-s', subj_id]

    # 针对autorecon1处理-i导入
    if stage_flag == 'autorecon1' and not orig_exists:
        cmd.extend(['-i', str(t1_file)])

    # 添加阶段标志
    cmd.append(f'-{stage_flag}')

    # FreeSurfer 8.x 添加OpenMP线程数
    if config.IS_FS_8:
        cmd.extend(['-openmp', str(config.FS8_OPENMP_THREADS)])

    # 附加标志
    if additional_flags:
        cmd.extend(additional_flags)

    try:
        utils.run_freesurfer_command(cmd, subject_id=subj_id)
        logger.info(f"✅ 受试者 {subj_id} 阶段 -{stage_flag} 完成")
        return True
    except Exception as e:
        logger.error(f"❌ 受试者 {subj_id} 阶段 -{stage_flag} 失败: {e}")
        return False

def run_recon_all_parallel(subject_info: Dict[str, Path], additional_flags: List[str] = None, max_workers: int = 8) -> Dict[str, bool]:
    """并行运行recon-all处理多个受试者，使用GNU parallel实现并行。
    - 对于FreeSurfer 8.x：采用分阶段策略
      1) 对所有受试者串行执行 -autorecon1 和 -autorecon2（内含-openmp线程设置）
      2) 使用GNU parallel以并发数8执行 -autorecon3 与 -qcache
    - 对于FreeSurfer 7.x：保持原有流程
    """
    if additional_flags is None:
        additional_flags = []

    results: Dict[str, bool] = {}

    # 准备环境
    env = utils.setup_freesurfer_env()

    # 预检测：在任务开始时探测性能核，如严格失败开关开启且获取无效，立即报错
    try:
        perf_cores_probe = _detect_perf_core_count()
        if perf_cores_probe <= 0 or perf_cores_probe is None:
            if getattr(config, 'PERF_DETECT_STRICT_FAIL', False):
                raise RuntimeError("性能核探测失败：未能获取有效的核心数量")
            logger.warning("⚠️ 性能核探测失败，将回退默认逻辑")
        else:
            logger.info(f"🧾 系统性能核: {perf_cores_probe}；全局默认openmp(autorecon1/2): {getattr(config, 'FS8_OPENMP_THREADS', 'N/A')}；最大并行(max_workers): {max_workers}")
    except Exception as e:
        if getattr(config, 'PERF_DETECT_STRICT_FAIL', False):
            logger.error(f"❌ 预检测失败：{e}")
            raise
        logger.warning(f"⚠️ 预检测出现异常但已忽略：{e}")

    # FreeSurfer 8.x 分阶段策略
    if config.IS_FS_8:
        logger.info("⚠️ 检测到FreeSurfer 8.x，采用分阶段编排：autorecon1/2 串行，autorecon3+qcache 并行(并发=8)...")

        # 第一阶段：对所有受试者串行执行 autorecon1 与 autorecon2
        with tqdm(total=len(subject_info) * 2, desc="autorecon1/2 串行阶段") as pbar:
            stage12_success: Dict[str, bool] = {}
            for subj_id, t1_file in subject_info.items():
                # autorecon1
                ok1 = run_recon_stage(subj_id, t1_file, 'autorecon1', additional_flags)
                pbar.update(1)
                if not ok1:
                    stage12_success[subj_id] = False
                    results[subj_id] = False
                    # autorecon2将跳过
                    pbar.update(1)
                    continue

                # autorecon2
                ok2 = run_recon_stage(subj_id, t1_file, 'autorecon2', additional_flags)
                pbar.update(1)
                stage12_success[subj_id] = ok2
                results[subj_id] = ok2

        # 第二阶段：对第一阶段成功的受试者，使用GNU parallel并发=8执行 autorecon3 + qcache
        runnable_subjects = [sid for sid, ok in results.items() if ok]
        if not runnable_subjects:
            logger.error("❌ 无受试者通过autorecon1/2，无法进入autorecon3/qcache阶段")
            success_count = sum(1 for success in results.values() if success)
            logger.info(f"🎉 处理结束，成功: {success_count}，失败: {len(results) - success_count}")
            return results

        logger.info(f"🚀 进入autorecon3+qcache 并行阶段，受试者数量: {len(runnable_subjects)}，并发=8")

        with tempfile.TemporaryDirectory() as temp_dir:
            # 动态选择phase2的并发与openmp值
            perf_cores = _detect_perf_core_count()
            parallel_jobs = min(max_workers if max_workers else 8, len(runnable_subjects))
            phase2_openmp = _choose_phase2_openmp(parallel_jobs, perf_cores)
            logger.info(f"🧠 phase2 并发={parallel_jobs}，openmp={phase2_openmp}（性能核={perf_cores}）")
            results_file = Path(temp_dir) / "results_phase2.txt"
            script_files: List[Path] = []

            for subj_id in runnable_subjects:
                script_path = Path(temp_dir) / f"phase2_{subj_id}.sh"
                with open(script_path, 'w') as script:
                    script.write("#!/bin/bash\n\n")
                    script.write(f"export SUBJECTS_DIR={config.SUBJECTS_DIR}\n")
                    script.write(f"export FREESURFER_HOME={os.environ.get('FREESURFER_HOME', '')}\n")
                    script.write("export PATH=${FREESURFER_HOME}/bin:$PATH\n\n")

                    # 组合命令：在一条指令中运行 autorecon3 + qcache
                    cmd_combined = f"recon-all -s {subj_id} -autorecon3 -qcache -openmp {phase2_openmp}"
                    if additional_flags:
                        cmd_combined = f"{cmd_combined} {' '.join(additional_flags)}"

                    script.write(f"echo '▶️ autorecon3+qcache: {subj_id}'\n")
                    script.write(f"if {cmd_combined}; then\n")
                    script.write(f"  echo '{subj_id}:true' >> '{results_file}'\n")
                    script.write("  exit 0\n")
                    script.write("else\n")
                    script.write(f"  echo '{subj_id}:false' >> '{results_file}'\n")
                    script.write("  exit 1\n")
                    script.write("fi\n")

                os.chmod(script_path, 0o755)
                script_files.append(script_path)

            try:
                cmd = [
                    "parallel",
                    "--jobs", str(parallel_jobs),
                    "--bar",
                    ":::",
                ] + [str(s) for s in script_files]

                logger.info(f"执行并行命令: {' '.join(cmd)}")
                subprocess.run(cmd, check=True)

                # 读取结果并与阶段1/2结果合并
                if results_file.exists():
                    with open(results_file, 'r') as f:
                        for line in f:
                            if ":" in line:
                                sid, rstr = line.strip().split(":", 1)
                                phase2_ok = rstr.lower() == "true"
                                # 最终结果 = 阶段1/2结果 AND 阶段2结果
                                results[sid] = results.get(sid, False) and phase2_ok
                else:
                    logger.error(f"❌ 结果文件不存在: {results_file}")
            except Exception as e:
                logger.error(f"❌ autorecon3/qcache 并行阶段出错: {e}")

        success_count = sum(1 for success in results.values() if success)
        logger.info(f"🎉 分阶段处理完成，成功: {success_count}，失败: {len(results) - success_count}")
        return results

    # ===== 7.x 原有路径，保持不变 =====
    if not config.USE_PROCESS_POOL:
        logger.info("⚠️ 检测到不使用进程池，使用顺序处理以避免系统崩溃...")
        with tqdm(total=len(subject_info), desc="处理进度") as pbar:
            for subj_id, t1_file in subject_info.items():
                try:
                    results[subj_id] = process_subject(subj_id, t1_file, additional_flags)
                except Exception as e:
                    logger.error(f"❌ 受试者 {subj_id} 生成异常: {e}")
                    results[subj_id] = False
                pbar.update(1)
    else:
        # 使用GNU parallel进行并行处理（保持原有实现）
        logger.info(f"🚀 使用GNU parallel并行处理{len(subject_info)}个受试者，最大并行数: {max_workers}")
        
        # 创建临时工作目录
        with tempfile.TemporaryDirectory() as temp_dir:
            # 创建结果文件路径
            results_file = Path(temp_dir) / "results.txt"
            
            # 为每个受试者创建一个独立的脚本
            script_files = []
            for subj_id, t1_file in subject_info.items():
                script_path = Path(temp_dir) / f"process_{subj_id}.sh"
                
                with open(script_path, 'w') as script:
                    # 写入脚本头部
                    script.write("#!/bin/bash\n\n")
                    script.write(f"export SUBJECTS_DIR={config.SUBJECTS_DIR}\n")
                    script.write(f"export FREESURFER_HOME={os.environ.get('FREESURFER_HOME', '')}\n")
                    script.write("export PATH=${FREESURFER_HOME}/bin:$PATH\n\n")
                    
                    # 处理单个受试者
                    script.write(f"echo \"🔄 处理受试者: {subj_id} 使用文件: {t1_file}\"\n\n")
                    
                    # 检查受试者目录是否已存在
                    script.write(f"# 检查受试者目录是否已存在\n")
                    script.write(f"subj_dir=\"$SUBJECTS_DIR/{subj_id}\"\n")
                    script.write("if [ -d \"$subj_dir\" ] && [ -f \"$subj_dir/mri/orig/001.mgz\" ]; then\n")
                    script.write(f"    echo \"⚠️ 受试者 {subj_id} 已存在，跳过 -i 参数...\"\n")
                    script.write(f"    cmd=\"recon-all -s {subj_id} -all -qcache\"\n")
                    script.write("else\n")
                    script.write(f"    echo \"🆕 处理新受试者 {subj_id}...\"\n")
                    script.write(f"    cmd=\"recon-all -s {subj_id} -i \\\"{t1_file}\\\" -all -qcache\"\n")
                    script.write("fi\n\n")
                    
                    # 添加FreeSurfer 8.0特有参数
                    if config.IS_FS_8:
                        script.write(f"cmd=\"$cmd -openmp {config.FS8_OPENMP_THREADS}\"\n\n")
                    
                    # 添加额外标志
                    if additional_flags:
                        flags_str = ' '.join(additional_flags)
                        script.write(f"cmd=\"$cmd {flags_str}\"\n\n")
                    
                    # 执行命令并记录结果
                    script.write("echo \"执行命令: $cmd\"\n")
                    script.write("if eval $cmd; then\n")
                    script.write(f"    echo \"✅ 受试者 {subj_id} 处理成功\"\n")
                    script.write(f"    echo \"{subj_id}:true\" >> \"{results_file}\"\n")
                    script.write("    exit 0\n")
                    script.write("else\n")
                    script.write(f"    echo \"❌ 受试者 {subj_id} 处理失败\"\n")
                    script.write(f"    echo \"{subj_id}:false\" >> \"{results_file}\"\n")
                    script.write("    exit 1\n")
                    script.write("fi\n")
                
                # 设置脚本为可执行
                os.chmod(script_path, 0o755)
                script_files.append(script_path)
            
            try:
                # 构建parallel命令
                cmd = [
                    "parallel",
                    "--jobs", str(max_workers),
                    "--bar",
                ]
                
                # 添加":::"参数表示输入列表的开始
                cmd.append(":::")
                
                # 添加脚本路径作为参数
                cmd.extend([str(script) for script in script_files])
                
                # 执行命令
                logger.info(f"执行并行命令: {' '.join(cmd)}")
                subprocess.run(cmd, check=True)
                
                # 读取结果文件
                if results_file.exists():
                    with open(results_file, 'r') as f:
                        for line in f:
                            if ":" in line:
                                subj_id, result_str = line.strip().split(":", 1)
                                results[subj_id] = result_str.lower() == "true"
                else:
                    logger.error(f"❌ 结果文件不存在: {results_file}")
                
            except Exception as e:
                logger.error(f"❌ 并行处理时出错: {e}")
    
    # 总结结果
    success_count = sum(1 for success in results.values() if success)
    logger.info(f"🎉 并行处理完成，成功: {success_count}，失败: {len(results) - success_count}")
    return results

def run_recon_all_batch_from_range(start_subj: int, end_subj: int, mr_dir: Union[str, Path] = None, max_workers: int = None, additional_flags: List[str] = None) -> Dict[str, bool]:
    """
    根据受试者ID范围批量运行recon-all，是对run_recon_all_parallel的更高级封装，简化了用户接口，让用户可以直接指定ID范围而不必手动构建详细的受试者信息字典
    
    参数:
        start_subj: 起始受试者编号(整数)
        end_subj: 结束受试者编号(整数)
        mr_dir: 包含MR数据的目录，默认使用config.MR_DIR
        max_workers: 最大并行处理数，默认使用config.DEFAULT_MAX_WORKERS
        additional_flags: 除-all -qcache外的附加recon-all标志列表
        
    返回:
        字典，键为患者ID，值为成功状态
    """
    if mr_dir is None:
        mr_dir = config.MR_DIR
        
    # 设置默认max_workers
    if max_workers is None:
        max_workers = config.DEFAULT_MAX_WORKERS
        
    # 生成subject_info
    subject_info = generate_subject_info_from_range(start_subj, end_subj, mr_dir)
    
    if not subject_info:
        logger.error(f"❌ 未找到符合条件的受试者，范围: {start_subj}-{end_subj}")
        return {}
        
    logger.info(f"🚀 找到 {len(subject_info)} 个受试者需要处理")
    
    # 运行并行处理
    return run_recon_all_parallel(subject_info, additional_flags, max_workers)

def _detect_perf_core_count() -> int:
    """检测可用于并行的性能核数量。
    - macOS 优先使用 hw.perflevel0.physicalcpu，其次 hw.physicalcpu
    - 其他平台回退到 os.cpu_count()
    使用 config.PERF_DETECT_TIMEOUT_SEC 控制sysctl超时。
    """
    timeout_sec = getattr(config, 'PERF_DETECT_TIMEOUT_SEC', 2.0)
    try:
        if sys.platform == 'darwin':
            try:
                out = subprocess.run(['sysctl', '-n', 'hw.perflevel0.physicalcpu'], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)
                val = int((out.stdout or '').strip())
                if val > 0:
                    return val
            except Exception:
                pass
            try:
                out2 = subprocess.run(['sysctl', '-n', 'hw.physicalcpu'], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)
                val2 = int((out2.stdout or '').strip())
                if val2 > 0:
                    return val2
            except Exception:
                pass
    except Exception:
        pass
    # 回退
    try:
        cpu_cnt = os.cpu_count() or 0
        return max(1, cpu_cnt)
    except Exception:
        return 1

def _choose_phase2_openmp(parallel_jobs: int, perf_cores: int) -> int:
    """根据并发数J选择phase2的-openmp O（固定映射优先）。
    建议映射：
    J=8 → O=1
    J=4 → O=2
    J=3 → O=2
    J=2 → O=4（上限4）
    J=1 → O=6–8（取min(8, perf_cores)）
    其他J走回退：min(4, max(1, perf_cores // J))
    """
    if parallel_jobs >= 8:
        return 1
    if parallel_jobs == 4:
        return 2
    if parallel_jobs == 3:
        return 2
    if parallel_jobs == 2:
        return min(4, perf_cores)
    if parallel_jobs == 1:
        return min(8, perf_cores)
    # 回退
    return max(1, min(4, perf_cores // max(1, parallel_jobs)))