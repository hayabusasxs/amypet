#!/usr/bin/env zsh

# 设置 FreeSurfer 输出目录
export SUBJECTS_DIR=${SUBJECTS_DIR:-$HOME/amypet/data/recon}

# 设定要处理的受试者编号范围（手动修改这里）
START_SUBJ=41
END_SUBJ=41

# 确保 globbing 行为符合预期（适用于 Zsh）
setopt NO_NOMATCH  # 避免 glob 失败时报错
setopt NULL_GLOB   # 让 glob 失败时返回空，而不是通配符本身

# 遍历./mr 目录下指定范围内的受试者
for ((i=START_SUBJ; i<=END_SUBJ; i++)); do
    subj=$(printf "%03d" "$i")  # 格式化为 3 位编号，如 015, 016

    subj_dir="./mr/$subj"
    if [[ ! -d "$subj_dir" ]]; then
        echo "受试者目录不存在：$subj"
        continue
    fi

    # 查找 NIfTI 文件
    nifti_file=(${subj_dir}/*.nii.gz)
    if [[ -z "$nifti_file" ]]; then
        echo "未找到 NIfTI 文件：$subj"
        continue
    fi

    echo "Processing subject: $subj"

    # 运行 recon-all 处理
    recon-all -s "$subj" -i "$nifti_file[1]" -all -qcache -parallel -openmp 8
done

# 等待所有任务完成
wait
