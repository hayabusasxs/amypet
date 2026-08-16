当目标ROI包含皮层下结构、小脑或任何在gtmseg.mgz中已有明确整数ID的区域时，途径B是一种更为直接、高效且通用的方法。它完全在体积空间内操作，避免了表面与体积之间的转换。

1：使用mri_binarize生成统一的二值掩模：
mri_binarize --i /path/to/amypet/data/recon_8.0.0/001/mri/gtmseg.mgz \
             --match 1009 1015 1030 2009 2015 2030 \
             --o /path/to/amypet/data/recon_8.0.0/001/pvc_mask/temporal.mgz
 
2. 修订颜色查找表（LUT）：
2.1. 将“/path/to/amypet/data/recon_8.0.0/001/mri/gtmseg.ctab”拷贝到“/path/to/amypet/data/recon_8.0.0/001/pvc_mask”，并重命名为“custom.gtm.ctab”
……是否可以共用一个ctab？

3. 在原始分割中清零目标区域—创建一个背景卷，其中除了我们将要合并的区域（a1, a2, a3）外，其他所有结构都保持不变。这些待合并区域的体素值需要被设置为0（背景值）：
3.1. 创建反向掩模:
mri_binarize --i /path/to/amypet/data/recon_8.0.0/001/mri/gtmseg.mgz \
             --match 1009 1015 1030 2009 2015 2030 \
             --inv\
             --o /path/to/amypet/data/recon_8.0.0/001/pvc_mask/inverted_temporal.mgz
3.2. 应用掩模:
mri_mask /path/to/amypet/data/recon_8.0.0/001/mri/gtmseg.mgz \
        /path/to/amypet/data/recon_8.0.0/001/pvc_mask/inverted_temporal.mgz \
        /path/to/amypet/data/recon_8.0.0/001/pvc_mask/gtmseg_background.mgz

3.3. 为自定义掩模赋予新ID
mris_calc -o /path/to/amypet/data/recon_8.0.0/001/pvc_mask/temporal-5001.mgz /path/to/amypet/data/recon_8.0.0/001/pvc_mask/temporal.mgz mul 5001


3.4. 合并背景与新ROI
mris_calc -o /path/to/amypet/data/recon_8.0.0/001/pvc_mask/gtmseg_background+temporal.mgz  /path/to/amypet/data/recon_8.0.0/001/pvc_mask/gtmseg_background.mgz add /path/to/amypet/data/recon_8.0.0/001/pvc_mask/temporal-5001.mgz

mri_convert --no_scale 1 -odt int /path/to/amypet/data/recon_8.0.0/001/pvc_mask/gtmseg_background+temporal.mgz /path/to/amypet/data/recon_8.0.0/001/pvc_mask/gtmseg_background+temporal.mgz-int-noscale.mgz

将custom.gtm.ctab重命名为gtmseg_background+temporal.mgz-int-noscale.ctab
将/path/to/amypet/data/recon_8.0.0/001/mri/gtmseg.lta拷贝为/path/to/amypet/data/recon_8.0.0/001/pvc_mask/gtmseg_background+temporal.mgz-int-noscale.lta

4. 验证：

在pet_pvc目录下新建一个test文件夹，用于保存mri_gtmpvc结果

mri_gtmpvc --i /path/to/amypet/data/recon_8.0.0/001/pet/001_pet-1-1-0/001_pet-1-1-0.mgz --reg /path/to/amypet/data/recon_8.0.0/001/pet/001_pet-1-1-0/pet2mri.lta --psf 4 --seg /path/to/amypet/data/recon_8.0.0/001/pvc_mask/gtmseg_background+temporal.mgz-int-noscale.mgz --default-seg-merge --auto-mask 1 .01 --mgx .01 --o /path/to/amypet/data/recon_8.0.0/001/pet_pvc/test --no-rescale

不可以使用这个方法——为什么不采用这个方法？
