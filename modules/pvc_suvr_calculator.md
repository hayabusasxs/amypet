前面步骤使用mri_gtmpvc处理好了每一个受试者的每一个序列，现在我们把xx.output中的结果提取出来：

1. 你将读取“gtm.stats.dat”中的内容。对于每个患者每个pet变体对应的“gtm.stats.dat”，你将参考"pet_pvc_processor.py"。对于“gtm.stats.dat”的内容，描述如下：
gtm.stats.dat is an easy to read text file where each row is an ROI, something like: 
9 17 Left-Hippocampus subcort_gm 473 174.083 1.406 0.1216 9 = ninth row
17 = index for ROI
Left-Hippocampus = name of ROI
subcort_gm = tissue class
473 = number of PET voxels in the ROI
174 = variance reduction factor for ROI (based on GLM/SGTM)
1.406 = PVC uptake of ROI 
0.1216 = resdiual varaince across voxels in the ROI

2. 你将参考mask_processor.py中对每个区域（靶区与背景区）的定义，来计算这个区域的平均pvc uptake，计算方法为：假设roi 1包含a、b、c三个区域，roi 1的平均pvc uptake为：（a中pet体素总和与a中pvc uptake of ROI +b中pet体素总和与b中pvc uptake of ROI +c中pet体素总和与c中pvc uptake of ROI ）/（a、b、c三个区域的pet体素总和）。你如果有更好的方法或者认为我的方法不对你可以指出来。

3. mask中对每个感兴趣区的定义如下：（数字为index for ROI）
靶区：'frontal': [1003, 1012, 1014, 1018, 1019, 1020, 1027, 1028, 1032, 
                2003, 2012, 2014, 2018, 2019, 2020, 2027, 2028, 2032],
    'cingulate': [1002, 1010, 1023, 1026, 2002, 2010, 2023, 2026],
    'parietal': [1008, 1025, 1029, 1031, 2008, 2025, 2029, 2031],
    'temporal': [1009, 1015, 1030, 2009, 2015, 2030],
参考区：'cerebellumgm': [8, 47],
       'wholecerebellum': [7, 8, 46, 47],
        'brainstem': [16],
        'subcorticalwm': [2, 41]
}

4. 对于生成结果文件，你将参考suvr_calculator.py。但存在一些差异。差异如下：
    1）文件保存位置的差异：所有文件将保存在/path/to/amypet/data/sheet_8.0.0/pvc_results中；
    2）文件目录的微小差异：在pvc_results文件夹中，首先按照psf值进行分类。如，某个结果对应psf为6，则其所有结果文件应该保存在“psf_6”中。psf_6文件夹下的文件应该与suvr_calculator.py生成的文件相同
    3）每个表格中内容的微小差异：与suvr_calculator.py生成的结果表格相比，因为pvc pet没有对subcorticalwm进行腐蚀操作，因此就没有“SubcorticalWM_FSM8_Thr07、SubcorticalWM_E1、SubcorticalWM_E2、Composite_FSM8_Thr07、CompositeE1、CompositeE2”这几个参考区以及对应的感兴趣区内的值以及suvr。因此，每个表格中应该含有如下条目：
Subject	vTag1	vTag2	vTag3	Composite_Count	Cingulate_Count	Frontal_Count	Parietal_Count	Temporal_Count	CerebellumGM_Ref	Brainstem_Ref	WholeCerebellum_Ref	SubcorticalWM_Ref	Composite_Ref		CerebellumGM_SUVR	Brainstem_SUVR	WholeCerebellum_SUVR	SubcorticalWM_SUVR	Composite_SUVR  WholeCerebellum_Status	Composite_Status	Cingulate_WholeCerebellum_SUVR	Frontal_WholeCerebellum_SUVR	Parietal_WholeCerebellum_SUVR	Temporal_WholeCerebellum_SUVR。
对于这些条目对应的值的计算方法，你可以参考suvr_calculator.py。
    请你时刻牢记，pvc_suvr的计算方法是与suvr_calculator.py中的方法不同的。pvc_suvr直接读取的dat文件，而suvr_calculator中使用的是类似mri_stats命令。你千万不要原封不动地抄袭suvr_calculator的方法。

5. 当你完成这个模块后，应该与main函数衔接，使我能够通过如下命令成功运行：
python main.py -r 1-20 -s pvc_suvr