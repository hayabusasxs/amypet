下面以001号受试者的001_pet-zte序列举例子。文件的组织结构与前面已完成的项目相同：
1. “export SUBJECTS_DIR=/path/to/amypet/data/recon_8.0.0”
2. 对mr图像执行gtmseg: gtmseg --s 001
3. 执行mri_gtmpvc:
    mri_gtmpvc\ 
        --i /path/to/amypet/data/recon_8.0.0/001/pet/001_pet-zte/001_pet-zte.mgz\
        --reg /path/to/amypet/data/recon_8.0.0/001/pet/001_pet-zte/pet2mri.lta\
        --psf 6\
        --seg /path/to/amypet/data/recon_8.0.0/001/mri/gtmseg.mgz\
        --default-seg-merge\
        --auto-mask 1 .01\
        --mgx .01\
        --o /path/to/amypet/data/recon_8.0.0/001/pet_pvc/001_pet-zte/gtmpvc_psf6.output
        --no-rescale
注意，就像前面对pet图像的配准一样，你需要对每一个变体都处理。也就是：
    --i可能会有：/path/to/amypet/data/recon_8.0.0/001/pet/001_pet-1-2-3/001_pet-1-2-3.mgz，/path/to/amypet/data/recon_8.0.0/001/pet/001_pet-3-2-1/001_pet-3-2-1.mgz，等等；
与之对应的--reg文件也存放在相应的文件夹里，但lta文件的名称是相同的，只是存放在不同序列的文件夹中；
psf我们分别使用2，3，4，5，6，然后分别对应gtmpvc_psf2.output，gtmpvc_psf3.output，gtmpvc_psf4.output等输出文件夹；
--seg中，同一个受试者的所有pet变体使用的都是相同的gtmseg.mgz；
每一个变体对应一个输出文件夹，即：……/001_pet-1-2-3，/001_pet-3-2-1；如果我输入了多个受试者，每个受试者又会对应一个文件夹。
对于--o环节，你需要提前创建输出目录，否则mri_gtmpvc会报错：“Creating output directory /path/to/amypet/data/recon_8.0.0/001/pet_pvc/001_pet-zte/gtmpvc_psf6.bbregistrate.output
ERROR: creating directory /path/to/amypet/data/recon_8.0.0/001/pet_pvc/001_pet-zte/gtmpvc_psf6.bbregistrate.output”
请你考虑使用多线程操作，使效率最大化
最后请你与我的main衔接，使我在输入：
“python main.py -r 1-15 -s pvc”时，能运行这个模块