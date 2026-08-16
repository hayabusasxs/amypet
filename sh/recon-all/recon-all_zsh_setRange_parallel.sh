#!/usr/bin/env zsh
#该脚本运行起来很爽！！终于成了
# 设置 FreeSurfer 输出目录
export SUBJECTS_DIR=${SUBJECTS_DIR:-$HOME/amypet/data/recon}

# 设定要处理的受试者编号范围（手动修改这里）
START_SUBJ=135
END_SUBJ=140

# 最大并行任务数（建议设为 CPU 核心数的 2/3）
MAX_JOBS=8

# 确保 globbing 行为符合预期（适用于 Zsh）
setopt NO_NOMATCH  # 避免 glob 失败时报错
setopt NULL_GLOB   # 让 glob 失败时返回空，而不是通配符本身

# 生成受试者列表
subject_list=()
for ((i=START_SUBJ; i<=END_SUBJ; i++)); do
    subj=$(printf "%03d" "$i")  # 格式化为 3 位编号，如 016, 017
    subj_dir="./mr/$subj"
    
    # 检查目录是否存在
    if [[ -d "$subj_dir" ]]; then
        nifti_file=(${subj_dir}/*.nii.gz)  # 获取 NIfTI 文件
        if [[ -n "$nifti_file" ]]; then
            subject_list+=("$subj")
        else
            echo "❌ 未找到 NIfTI 文件：$subj，跳过..."
        fi
    else
        echo "⚠️ 受试者目录不存在：$subj，跳过..."
    fi
done

# 并行执行 recon-all
echo "🚀 Processing subjects: ${#subject_list[@]} ，parallel jobs: $MAX_JOBS"

# 避免重复执行相同受试者任务
parallel --jobs $MAX_JOBS --no-run-if-empty "
    subj={};
    nii_file=\$(ls ./mr/\$subj/*.nii.gz | head -n 1);  # 仅选择一个 NIfTI 文件
    subj_dir=\"\$SUBJECTS_DIR/\$subj\";

    if [[ -d \"\$subj_dir\" ]]; then
        echo \"⚠️ 受试者 \$subj 已存在，跳过 -i 参数...\"
        recon-all -s \$subj -all -qcache
    else
        echo \"🆕 处理新受试者 \$subj...\"
        recon-all -s \$subj -i \"\$nii_file\" -all -qcache
    fi
" ::: "${subject_list[@]}"

echo "🎉 Congratulations!All done!!"
