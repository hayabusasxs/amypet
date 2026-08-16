#!/bin/zsh

# 设置基础目录
BASE_DIR="${AMYPET_BASE_DIR:-$HOME/amypet/data}"
export SUBJECTS_DIR="${BASE_DIR}/recon"

# 创建日志目录
mkdir -p ${BASE_DIR}/logs

# 获取要处理的受试者范围
echo "请输入要处理的受试者序号范围 (例如: 1-10 或 单个数字):"
read subject_range

# 解析输入范围
if [[ $subject_range == *-* ]]; then
    # 范围格式
    start_id=${subject_range%-*}
    end_id=${subject_range#*-}
else
    # 单个数字
    start_id=$subject_range
    end_id=$subject_range
fi

echo "将处理受试者序号 $start_id 到 $end_id"
sleep 2  # 等待用户确认

# 创建或初始化汇总CSV文件，包括判断状态列
echo "Subject,CerebellumGM_Ref,CerebellumGM_SUVR,Brainstem_Ref,Brainstem_SUVR,WholeCerebellum_Ref,WholeCerebellum_SUVR,SubcorticalWM_Ref,SubcorticalWM_SUVR,Composite_Ref,Composite_SUVR,CompositeE1_Ref,CompositeE1_SUVR,CompositeE2_Ref,CompositeE2_SUVR,WholeCerebellum_Status,Composite_Status,CompositeE1_Status,CompositeE2_Status" > ${BASE_DIR}/all_subjects_suvr.csv

# 记录处理开始时间
start_time=$(date +%s)

# 为每个受试者进行处理
for (( subj_id=$start_id; subj_id<=$end_id; subj_id++ )); do
    # 格式化受试者ID为3位数
    printf -v formatted_id "%03d" $subj_id
    subject="${formatted_id}"
    
    echo "====================================================="
    echo "开始处理受试者: ${subject} ($(date))"
    echo "====================================================="
    
    # 创建日志文件
    LOG_FILE="${BASE_DIR}/logs/${subject}_processing.log"
    echo "处理受试者 ${subject} - 开始于 $(date)" > $LOG_FILE
    
    # 创建目录结构
    mkdir -p ${SUBJECTS_DIR}/${subject}/pet
    mkdir -p ${SUBJECTS_DIR}/${subject}/mask
    
    # 检查PET文件是否存在 - 注意更新了路径结构
    PET_FILE="${BASE_DIR}/pet/${subject}/${subject}_PET.nii.gz"
    if [[ ! -f $PET_FILE ]]; then
        echo "错误: 找不到PET文件 ${PET_FILE}" | tee -a $LOG_FILE
        echo "跳过受试者 ${subject}" | tee -a $LOG_FILE
        continue
    fi
    
    # 检查FreeSurfer重建是否存在
    if [[ ! -d ${SUBJECTS_DIR}/${subject}/mri ]]; then
        echo "错误: 找不到FreeSurfer重建目录 ${SUBJECTS_DIR}/${subject}/mri" | tee -a $LOG_FILE
        echo "跳过受试者 ${subject}" | tee -a $LOG_FILE
        continue
    fi
    
    echo "1. 转换PET文件格式..." | tee -a $LOG_FILE
    mri_convert ${PET_FILE} ${SUBJECTS_DIR}/${subject}/pet/${subject}_PET.mgz >> $LOG_FILE 2>&1
    
    echo "2. 生成配准矩阵..." | tee -a $LOG_FILE
    bbregister --s ${subject} \
               --mov ${SUBJECTS_DIR}/${subject}/pet/${subject}_PET.mgz \
               --reg ${SUBJECTS_DIR}/${subject}/pet/pet2mri.lta \
               --t1 \
               --init-fsl >> $LOG_FILE 2>&1
    
    echo "3. 将PET配准到MR个体空间..." | tee -a $LOG_FILE
    mri_vol2vol --mov ${SUBJECTS_DIR}/${subject}/pet/${subject}_PET.mgz \
                --reg ${SUBJECTS_DIR}/${subject}/pet/pet2mri.lta \
                --o ${SUBJECTS_DIR}/${subject}/pet/registered_pet.mgz \
                --fstarg \
                --interp cubic >> $LOG_FILE 2>&1
    
    mri_convert ${SUBJECTS_DIR}/${subject}/pet/registered_pet.mgz ${SUBJECTS_DIR}/${subject}/pet/registered_pet.nii.gz >> $LOG_FILE 2>&1
    
    echo "4. 创建各种皮层掩码..." | tee -a $LOG_FILE
    
    # 创建前额叶区域掩码
    mri_binarize --i ${SUBJECTS_DIR}/${subject}/mri/aparc+aseg.mgz --match 1003 1012 1014 1018 1019 1020 1027 1028 1032 2003 2012 2014 2018 2019 2020 2027 2028 2032 --o ${SUBJECTS_DIR}/${subject}/mask/frontal_mask.mgz >> $LOG_FILE 2>&1
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/frontal_mask.mgz ${SUBJECTS_DIR}/${subject}/mask/frontal_mask.nii.gz >> $LOG_FILE 2>&1
    
    # 创建前/后扣带回区域掩码
    mri_binarize --i ${SUBJECTS_DIR}/${subject}/mri/aparc+aseg.mgz --match 1002 1010 1023 1026 2002 2010 2023 2026 --o ${SUBJECTS_DIR}/${subject}/mask/cingulate_mask.mgz >> $LOG_FILE 2>&1
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/cingulate_mask.mgz ${SUBJECTS_DIR}/${subject}/mask/cingulate_mask.nii.gz >> $LOG_FILE 2>&1
    
    # 创建外侧顶叶区域掩码
    mri_binarize --i ${SUBJECTS_DIR}/${subject}/mri/aparc+aseg.mgz --match 1008 1025 1029 1031 2008 2025 2029 2031 --o ${SUBJECTS_DIR}/${subject}/mask/parietal_mask.mgz >> $LOG_FILE 2>&1
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/parietal_mask.mgz ${SUBJECTS_DIR}/${subject}/mask/parietal_mask.nii.gz >> $LOG_FILE 2>&1
    
    # 创建颞叶区域掩码
    mri_binarize --i ${SUBJECTS_DIR}/${subject}/mri/aparc+aseg.mgz --match 1009 1015 1030 2009 2015 2030 --o ${SUBJECTS_DIR}/${subject}/mask/temporal_mask.mgz >> $LOG_FILE 2>&1
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/temporal_mask.mgz ${SUBJECTS_DIR}/${subject}/mask/temporal_mask.nii.gz >> $LOG_FILE 2>&1
    
    # 合并所有区域创建皮层汇总区域
    mri_binarize --i ${SUBJECTS_DIR}/${subject}/mri/aparc+aseg.mgz --match 1003 1012 1014 1018 1019 1020 1027 1028 1032 2003 2012 2014 2018 2019 2020 2027 2028 2032 1002 1010 1023 1026 2002 2010 2023 2026 1008 1025 1029 1031 2008 2025 2029 2031 1009 1015 1030 2009 2015 2030 --o ${SUBJECTS_DIR}/${subject}/mask/composite.mgz >> $LOG_FILE 2>&1
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/composite.mgz ${SUBJECTS_DIR}/${subject}/mask/composite.nii.gz >> $LOG_FILE 2>&1
    
    echo "5. 创建参考区域..." | tee -a $LOG_FILE
    
    # 小脑灰质
    mri_binarize --i ${SUBJECTS_DIR}/${subject}/mri/aparc+aseg.mgz --match 8 47 --o ${SUBJECTS_DIR}/${subject}/mask/ref_cerebellumgm.mgz >> $LOG_FILE 2>&1
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/ref_cerebellumgm.mgz ${SUBJECTS_DIR}/${subject}/mask/ref_cerebellumgm.nii.gz >> $LOG_FILE 2>&1
    
    # 整个小脑(灰质+白质)
    mri_binarize --i ${SUBJECTS_DIR}/${subject}/mri/aparc+aseg.mgz --match 7 8 46 47 --o ${SUBJECTS_DIR}/${subject}/mask/ref_wholecerebellum.mgz >> $LOG_FILE 2>&1
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/ref_wholecerebellum.mgz ${SUBJECTS_DIR}/${subject}/mask/ref_wholecerebellum.nii.gz >> $LOG_FILE 2>&1
    
    # 脑干/脑桥
    mri_binarize --i ${SUBJECTS_DIR}/${subject}/mri/aparc+aseg.mgz --match 16 --o ${SUBJECTS_DIR}/${subject}/mask/ref_brainstem.mgz >> $LOG_FILE 2>&1
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/ref_brainstem.mgz ${SUBJECTS_DIR}/${subject}/mask/ref_brainstem.nii.gz >> $LOG_FILE 2>&1
    
    # 皮层下白质
    mri_binarize --i ${SUBJECTS_DIR}/${subject}/mri/aparc+aseg.mgz --match 2 41 --o ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm.mgz >> $LOG_FILE 2>&1
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm.mgz ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm.nii.gz >> $LOG_FILE 2>&1
    
    echo "6. 对皮质下白质进行腐蚀操作..." | tee -a $LOG_FILE
    
    # 使用FSL的平滑
    fslmaths ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm.nii.gz -s 3.39729 ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_fsm8.nii.gz >> $LOG_FILE 2>&1
    
    # 对平滑后的图像进行阈值处理(≥0.7)
    mri_binarize --i ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_fsm8.nii.gz --min 0.7 --o ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_fsm8_eroded07.nii.gz >> $LOG_FILE 2>&1
    
    # 查看处理前后mask的体积变化
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm.nii.gz --sum ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm.txt >> $LOG_FILE 2>&1
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_fsm8.nii.gz --sum ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_fsm8.txt >> $LOG_FILE 2>&1
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_fsm8_eroded07.nii.gz --sum ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_fsm8_eroded07.txt >> $LOG_FILE 2>&1
    
    echo "7. 创建复合参考区域..." | tee -a $LOG_FILE
    
    # 主要复合参考区域
    mri_concat ${SUBJECTS_DIR}/${subject}/mask/ref_wholecerebellum.nii.gz ${SUBJECTS_DIR}/${subject}/mask/ref_brainstem.nii.gz ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_fsm8_eroded07.nii.gz --sum --o ${SUBJECTS_DIR}/${subject}/mask/ref_composite.nii.gz >> $LOG_FILE 2>&1
    
    # 测试不同级别侵蚀的白质区域
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm.nii.gz ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_erode1.nii.gz --erode-seg 1 >> $LOG_FILE 2>&1
    mri_convert ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm.nii.gz ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_erode2.nii.gz --erode-seg 2 >> $LOG_FILE 2>&1
    
    # 创建基于不同侵蚀级别的复合参考区域
    mri_concat ${SUBJECTS_DIR}/${subject}/mask/ref_wholecerebellum.nii.gz ${SUBJECTS_DIR}/${subject}/mask/ref_brainstem.nii.gz ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_erode1.nii.gz --sum --o ${SUBJECTS_DIR}/${subject}/mask/ref_composite_e1.nii.gz >> $LOG_FILE 2>&1
    mri_concat ${SUBJECTS_DIR}/${subject}/mask/ref_wholecerebellum.nii.gz ${SUBJECTS_DIR}/${subject}/mask/ref_brainstem.nii.gz ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_erode2.nii.gz --sum --o ${SUBJECTS_DIR}/${subject}/mask/ref_composite_e2.nii.gz >> $LOG_FILE 2>&1
    
    # 生成对应的mask体积数据
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_composite.nii.gz --sum ${SUBJECTS_DIR}/${subject}/mask/ref_composite.txt >> $LOG_FILE 2>&1
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_composite_e1.nii.gz --sum ${SUBJECTS_DIR}/${subject}/mask/ref_composite_e1.txt >> $LOG_FILE 2>&1
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_composite_e2.nii.gz --sum ${SUBJECTS_DIR}/${subject}/mask/ref_composite_e2.txt >> $LOG_FILE 2>&1
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_erode1.nii.gz --sum ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_erode1.txt >> $LOG_FILE 2>&1
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_erode2.nii.gz --sum ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_erode2.txt >> $LOG_FILE 2>&1

    
    echo "8. 计算不同区域的平均PET值..." | tee -a $LOG_FILE
    
    # 复合皮质区
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/composite.nii.gz --i ${SUBJECTS_DIR}/${subject}/pet/registered_pet.nii.gz --avgwf ${SUBJECTS_DIR}/${subject}/stats/composite_summary_mean.txt --sum ${SUBJECTS_DIR}/${subject}/stats/composite_summary_stats.txt >> $LOG_FILE 2>&1
    
    # 小脑灰质
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_cerebellumgm.nii.gz --i ${SUBJECTS_DIR}/${subject}/pet/registered_pet.nii.gz --avgwf ${SUBJECTS_DIR}/${subject}/stats/ref_cerebellumgm_summary_mean.txt --sum ${SUBJECTS_DIR}/${subject}/stats/ref_cerebellumgm_summary_stats.txt >> $LOG_FILE 2>&1
    
    # 脑干脑桥
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_brainstem.nii.gz --i ${SUBJECTS_DIR}/${subject}/pet/registered_pet.nii.gz --avgwf ${SUBJECTS_DIR}/${subject}/stats/ref_brainstem_summary_mean.txt --sum ${SUBJECTS_DIR}/${subject}/stats/ref_brainstem_summary_stats.txt >> $LOG_FILE 2>&1
    
    # 全小脑
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_wholecerebellum.nii.gz --i ${SUBJECTS_DIR}/${subject}/pet/registered_pet.nii.gz --avgwf ${SUBJECTS_DIR}/${subject}/stats/ref_wholecerebellum_summary_mean.txt --sum ${SUBJECTS_DIR}/${subject}/stats/ref_wholecerebellum_summary_stats.txt >> $LOG_FILE 2>&1
    
    # 侵蚀皮质下白质
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_subcorticalwm_fsm8_eroded07.nii.gz --i ${SUBJECTS_DIR}/${subject}/pet/registered_pet.nii.gz --avgwf ${SUBJECTS_DIR}/${subject}/stats/ref_subcorticalwm_fsm8_eroded07_summary_mean.txt --sum ${SUBJECTS_DIR}/${subject}/stats/ref_subcorticalwm_fsm8_eroded07_summary_stats.txt >> $LOG_FILE 2>&1
    
    # 复合区
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_composite.nii.gz --i ${SUBJECTS_DIR}/${subject}/pet/registered_pet.nii.gz --avgwf ${SUBJECTS_DIR}/${subject}/stats/ref_composite_summary_mean.txt --sum ${SUBJECTS_DIR}/${subject}/stats/ref_composite_summary_stats.txt >> $LOG_FILE 2>&1
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_composite_e1.nii.gz --i ${SUBJECTS_DIR}/${subject}/pet/registered_pet.nii.gz --avgwf ${SUBJECTS_DIR}/${subject}/stats/ref_composite_e1_summary_mean.txt --sum ${SUBJECTS_DIR}/${subject}/stats/ref_composite_e1_summary_stats.txt >> $LOG_FILE 2>&1
    mri_segstats --seg ${SUBJECTS_DIR}/${subject}/mask/ref_composite_e2.nii.gz --i ${SUBJECTS_DIR}/${subject}/pet/registered_pet.nii.gz --avgwf ${SUBJECTS_DIR}/${subject}/stats/ref_composite_e2_summary_mean.txt --sum ${SUBJECTS_DIR}/${subject}/stats/ref_composite_e2_summary_stats.txt >> $LOG_FILE 2>&1
    
    echo "9. 计算SUVR值..." | tee -a $LOG_FILE
    
    # 检查文件是否存在
    if [[ -f ${SUBJECTS_DIR}/${subject}/stats/composite_summary_mean.txt ]]; then
        # 使用awk提取各个区域的平均值（第二列）
        composite=$(awk '{print $2}' ${SUBJECTS_DIR}/${subject}/stats/composite_summary_mean.txt)
        cerebellumgm=$(awk '{print $2}' ${SUBJECTS_DIR}/${subject}/stats/ref_cerebellumgm_summary_mean.txt)
        brainstem=$(awk '{print $2}' ${SUBJECTS_DIR}/${subject}/stats/ref_brainstem_summary_mean.txt)
        wholecerebellum=$(awk '{print $2}' ${SUBJECTS_DIR}/${subject}/stats/ref_wholecerebellum_summary_mean.txt)
        subcorticalwm=$(awk '{print $2}' ${SUBJECTS_DIR}/${subject}/stats/ref_subcorticalwm_fsm8_eroded07_summary_mean.txt)
        ref_composite=$(awk '{print $2}' ${SUBJECTS_DIR}/${subject}/stats/ref_composite_summary_mean.txt)
        ref_composite_e1=$(awk '{print $2}' ${SUBJECTS_DIR}/${subject}/stats/ref_composite_e1_summary_mean.txt)
        ref_composite_e2=$(awk '{print $2}' ${SUBJECTS_DIR}/${subject}/stats/ref_composite_e2_summary_mean.txt)
        
        # 将结果保存到文件
        RESULT_FILE=${SUBJECTS_DIR}/${subject}/stats/suvr_results.txt
        echo "# SUVr_summary - $(date)" > $RESULT_FILE
        echo "composite_cortical_original_mean: $composite" >> $RESULT_FILE
        echo "" >> $RESULT_FILE
        echo "reference_area_original_mean:" >> $RESULT_FILE
        echo "ref_cerebellumgm: $cerebellumgm" >> $RESULT_FILE
        echo "ref_brainstem: $brainstem" >> $RESULT_FILE
        echo "ref_wholecerebellum: $wholecerebellum" >> $RESULT_FILE
        echo "ref_subcorticalwm_eroded: $subcorticalwm" >> $RESULT_FILE
        echo "ref_composite: $ref_composite" >> $RESULT_FILE
        echo "ref_composite_e1: $ref_composite_e1" >> $RESULT_FILE
        echo "ref_composite_e2: $ref_composite_e2" >> $RESULT_FILE
        echo "" >> $RESULT_FILE
        echo "SUVr_values:" >> $RESULT_FILE
        
        # 计算使用不同参考区域的SUVR值
        suvr_cerebellumgm=$(echo "scale=4; $composite / $cerebellumgm" | bc)
        suvr_brainstem=$(echo "scale=4; $composite / $brainstem" | bc)
        suvr_wholecerebellum=$(echo "scale=4; $composite / $wholecerebellum" | bc)
        suvr_subcorticalwm=$(echo "scale=4; $composite / $subcorticalwm" | bc)
        suvr_ref_composite=$(echo "scale=4; $composite / $ref_composite" | bc)
        suvr_ref_composite_e1=$(echo "scale=4; $composite / $ref_composite_e1" | bc)
        suvr_ref_composite_e2=$(echo "scale=4; $composite / $ref_composite_e2" | bc)
        
        echo "ref_cerebellumgm: $suvr_cerebellumgm" >> $RESULT_FILE
        echo "ref_brainstem: $suvr_brainstem" >> $RESULT_FILE
        echo "ref_wholecerebellum: $suvr_wholecerebellum" >> $RESULT_FILE
        echo "ref_subcorticalwm_eroded: $suvr_subcorticalwm" >> $RESULT_FILE
        echo "ref_composite: $suvr_ref_composite" >> $RESULT_FILE
        echo "ref_composite_e1: $suvr_ref_composite_e1" >> $RESULT_FILE
        echo "ref_composite_e2: $suvr_ref_composite_e2" >> $RESULT_FILE
        
        # 应用判断规则
        # wholecerebellum判断规则: 阈值>=1.11
        if (( $(echo "$suvr_wholecerebellum >= 1.11" | bc -l) )); then
            wholecerebellum_status="+"
        else
            wholecerebellum_status="-"
        fi
        
        # composite判断规则: 阈值>=0.78
        if (( $(echo "$suvr_ref_composite >= 0.78" | bc -l) )); then
            composite_status="+"
        else
            composite_status="-"
        fi
        
        # composite_e1判断规则: 阈值>=0.78 (与composite相同)
        if (( $(echo "$suvr_ref_composite_e1 >= 0.78" | bc -l) )); then
            composite_e1_status="+"
        else
            composite_e1_status="-"
        fi
        
        # composite_e2判断规则: 阈值>=0.78 (与composite相同)
        if (( $(echo "$suvr_ref_composite_e2 >= 0.78" | bc -l) )); then
            composite_e2_status="+"
        else
            composite_e2_status="-"
        fi
        
        # 将SUVR结果及判断状态添加到汇总文件
        echo "${subject},$cerebellumgm,$suvr_cerebellumgm,$brainstem,$suvr_brainstem,$wholecerebellum,$suvr_wholecerebellum,$subcorticalwm,$suvr_subcorticalwm,$ref_composite,$suvr_ref_composite,$ref_composite_e1,$suvr_ref_composite_e1,$ref_composite_e2,$suvr_ref_composite_e2,$wholecerebellum_status,$composite_status,$composite_e1_status,$composite_e2_status" >> ${BASE_DIR}/all_subjects_suvr.csv
        
        echo "受试者 ${subject} SUVR计算完成! 结果已保存到 ${RESULT_FILE}" | tee -a $LOG_FILE
    else
        echo "警告: 无法找到平均值文件，跳过SUVR计算" | tee -a $LOG_FILE
    fi
    
    echo "受试者 ${subject} 处理完成!" | tee -a $LOG_FILE
    echo "====================================================="
done

# 记录处理结束时间和总时间
end_time=$(date +%s)
total_time=$((end_time - start_time))
hours=$((total_time / 3600))
minutes=$(( (total_time % 3600) / 60 ))
seconds=$((total_time % 60))

echo "====================================================="
echo "所有受试者处理完成!"
echo "处理了从 $start_id 到 $end_id 的受试者"
echo "总处理时间: ${hours}小时 ${minutes}分钟 ${seconds}秒"
echo "每个受试者的SUVR结果已保存到各自的 stats/suvr_results.txt 文件中"
echo "所有受试者的SUVR结果及判断结果已汇总到 ${BASE_DIR}/all_subjects_suvr.csv"
echo "====================================================="
