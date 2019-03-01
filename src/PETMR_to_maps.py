#!/usr/bin/env python2.7 -W ignore::DeprecationWarning
# -*- coding: utf-8 -*-
import datetime
import os
from os.path import join, exists, isdir, dirname, basename, split
import shutil
from multiprocessing import Process
import pandas as pd

from utils import apple as ap
from utils import spm_tools as spm
from utils import resources as rsc

class PETMR_to_maps(object):
    """
    This class will create activity and attenuation maps from PET and MR images.
    Inputs are:
    spm_run: Command to run SPM (i.e. ../run_spm12.sh pathto/mcr/v901)
    maps_path: path where the maps will be stored
    log: logging file
    mri_path: .img of analyze file for mri
    pet_path: .img of analyze file for pet
    mode: STIR or SIMSET
    """

    def __init__(self, spm_run, maps_path, log, mri_path, pet_path, mode="STIR"):

        # Maps Paths
        self.analysis_path = maps_path
        self.mri_img = mri_path
        self.pet_img = pet_path
        # SPM
        self.spm_run = spm_run
        #Logging
        self.log_file = log

    def run(self):
            
        p1 = Process(target=self.mri_normalization)
        p2 = Process(target=self.mri_segmentation)

        p1.start()
        p2.start()
        p1.join()
        p2.join()

        act_map, att_map = self.atlas_generation()
        
        self.cleanup()

        return act_map, att_map
        
    def mri_normalization(self):
        """
        Normalizes image following the segmentation method (SPM12)
        """
        # Starts login
        message = 'MRi normalization...'
        print message
        # Runs SPM12 for new individual norm_spm files
        mfile = join(self.analysis_path, "mynorm_spm12.m")
        template_image = rsc.get_rsc("tpm_file", "image")
        atlas = rsc.get_rsc("hammers", "image")

        #Runs old_normalize of the data
        norm_mri, mri_transformation_matrix = spm.new_normalize(self.spm_run, mfile, self.mri_img, template_image, self.log_file)

        # Apply deformations on Atlases and Mask images
        images_to_deform =[]
        images_to_deform.append(atlas)
        
        mfile = join(self.analysis_path, "atlas_deformations.m")
        spm.new_deformations(self.spm_run, mfile, mri_transformation_matrix,self.mri_img, images_to_deform, self.analysis_path, 0, self.log_file)

    def mri_segmentation(self):
        """
        Segments image using SPM12
        """
        # Starts login
        message = 'MRi segmentation...'
        print message

        template_image = rsc.get_rsc("tpm_file", "image")

        mfile = os.path.join(self.analysis_path,"segment.m")
        spm.segment_mri_spm(self.spm_run, mfile, self.mri_img, template_image, self.log_file)
        
    def atlas_generation(self):
        """
        Runs Atlas-based Quantification to all ROIs and generates maps...
        """
        message = 'Atlas-based Quantification to all ROIs and generates maps...'
        print message

        # Getting the necesary resources
        cambia_formato = rsc.get_rsc('change_format', 'fruitcake')
        elimina_nan = rsc.get_rsc('erase_nans', 'fruitcake')
        calc_vm = rsc.get_rsc('calc_vm_voi', 'fruitcake')
        cambia_val_interval = rsc.get_rsc('change_interval', 'fruitcake')
        cambia_val = rsc.get_rsc('change_values', 'fruitcake')
        opera_imagen = rsc.get_rsc('operate_image', 'fruitcake')
        
        mri_basename = os.path.basename(self.mri_img)

        output_gm_hdr = ap.nii_analyze_convert(join(self.analysis_path, "c1" + mri_basename[0:-3] + "nii"))
        output_wm_hdr = ap.nii_analyze_convert(join(self.analysis_path, "c2" + mri_basename[0:-3] + "nii"))
        output_csf_hdr = ap.nii_analyze_convert(join(self.analysis_path, "c3" + mri_basename[0:-3] + "nii"))
        output_bone_hdr = ap.nii_analyze_convert(join(self.analysis_path, "c4" + mri_basename[0:-3] + "nii"))
        output_soft_hdr = ap.nii_analyze_convert(join(self.analysis_path, "c5" + mri_basename[0:-3] + "nii"))

        #Preformat Atlas
        atlas_hdr = join(self.analysis_path, "whammers.hdr")
        rcommand = '%s %s %s fl >> /dev/null' % (cambia_formato, atlas_hdr, atlas_hdr)
        ap.rsystem(rcommand, self.log_file)
        rcommand = '%s %s %s >> /dev/null' % (elimina_nan, atlas_hdr, atlas_hdr)
        ap.rsystem(rcommand, self.log_file)
        rcommand = '%s %s %s 45 49 0' % (cambia_val_interval, atlas_hdr, atlas_hdr)
        ap.rsystem(rcommand, self.log_file)

        #Preformat PET image
        pet_hdr = self.pet_img[0:-3] + "hdr"
        #Removes NaN from PET (just in case..)
        rcommand = '%s %s %s >> /dev/null' % (elimina_nan, pet_hdr, pet_hdr)
        ap.rsystem(rcommand, self.log_file)

        #Preparing PET_mask
        pet_mask = join(self.analysis_path, "pet_mask.hdr")
        img = nib.load(pet_hdr)
        data = img.get_data()[:, :, :]
        patient_vmax = np.amax(data)
        patient_vmin = np.amin(data)

        rcommand = '%s %s %s %s %s 0' % (cambia_val_interval, pet_hdr, pet_mask, patient_vmin, 0.01*patient_vmax)
        ap.rsystem(rcommand, self.log_file)

        rcommand = '%s %s %s %s %s 1' % (cambia_val_interval, pet_mask, pet_mask, 0.01*patient_vmax, patient_vmax)
        ap.rsystem(rcommand, self.log_file)
        

        # Priority of Gray is higher than White
        # GWSEGA = ATLAS.* (WSEG < 0.5 & GSEG >0.1 ) + 100.* (WSEG >= 0.5);

        for i in [output_gm_hdr, output_wm_hdr, output_csf_hdr, output_bone_hdr, output_soft_hdr]:
            rcommand = '%s %s %s %s fl multi' % (opera_imagen, i, pet_mask,i)
            ap.rsystem(rcommand, self.log_file)

        for i in [output_gm_hdr, output_bone_hdr]: # High priority tissues.
            rcommand = '%s %s %s 0.01 1 1' % (cambia_val_interval, i, i)
            ap.rsystem(rcommand, self.log_file)
            rcommand = '%s %s %s 0 0.01 0' % (cambia_val_interval, i, i)
            ap.rsystem(rcommand, self.log_file)

        for i in [output_wm_hdr, output_csf_hdr, output_soft_hdr]: # High priority tissues.
            rcommand = '%s %s %s 0.5 1 1' % (cambia_val_interval, i, i)
            ap.rsystem(rcommand, self.log_file)
            rcommand = '%s %s %s 0 0.5 0' % (cambia_val_interval, i, i)
            ap.rsystem(rcommand, self.log_file)
            rcommand = '%s -C -1 %s %s fl sumar' % (opera_imagen, i, join(self.analysis_path, i[0:-4] + "_mask.hdr"))
            ap.rsystem(rcommand, self.log_file)
            rcommand = '%s -C -1 %s %s fl multi' % (opera_imagen, join(self.analysis_path, i[0:-4] + "_mask.hdr"), join(self.analysis_path, i[0:-4] + "_mask.hdr"))
            ap.rsystem(rcommand, self.log_file)
        
        
        #Generates final GM using WM and CSF masks
        rcommand = '%s %s %s %s fl multi' % (opera_imagen, output_gm_hdr, join(self.analysis_path, output_wm_hdr[0:-4] + "_mask.hdr"),  output_gm_hdr)
        ap.rsystem(rcommand, self.log_file)
        rcommand = '%s %s %s %s fl multi' % (opera_imagen, output_gm_hdr, join(self.analysis_path, output_csf_hdr[0:-4] + "_mask.hdr"),  output_gm_hdr)
        ap.rsystem(rcommand, self.log_file)

        
        #Generates final bone tissue using CSF and soft tissue mask
        rcommand = '%s %s %s %s fl multi' % (opera_imagen, output_bone_hdr, join(self.analysis_path, output_csf_hdr[0:-4] + "_mask.hdr"),  output_bone_hdr)
        ap.rsystem(rcommand, self.log_file)
        rcommand = '%s %s %s %s fl multi' % (opera_imagen, output_bone_hdr, join(self.analysis_path, output_soft_hdr[0:-4] + "_mask.hdr"),  output_bone_hdr)
        ap.rsystem(rcommand, self.log_file)

        # Creating GM atlas
        grey_matter_atlas = join(self.analysis_path, "gm_hammers.hdr")
        rcommand = '%s %s %s %s fl multi' % (opera_imagen, atlas_hdr, output_gm_hdr,grey_matter_atlas)
        ap.rsystem(rcommand, self.log_file)

        segmented_pet_gm = join(self.analysis_path, "seg_pet_gm.hdr")
        ap.copy_analyze(grey_matter_atlas, segmented_pet_gm)

        # Creating WM atlas
        white_matter_atlas = join(self.analysis_path, "wm_hammers.hdr")
        rcommand = '%s %s %s %s fl multi' % (opera_imagen, atlas_hdr, output_wm_hdr,white_matter_atlas)
        ap.rsystem(rcommand, self.log_file)

        segmented_pet_wm = join(self.analysis_path, "seg_pet_wm.hdr")
        ap.copy_analyze(white_matter_atlas, segmented_pet_wm)
        
        # Reads the ROI files for the necessary images
        roi_file_name = rsc.get_rsc('hammers_csv', 'image')
        df_rois = pd.read_csv(roi_file_name, sep=';')
        rois_nums = df_rois['ROI_NUM'].values
        
        # First we calculate the mean values for each ROI
        for roi_num in rois_nums:

            if ap.verify_roi_exists(grey_matter_atlas, roi_num)==True:

                rcommand = '%s %s %s %s 0' % (calc_vm, pet_hdr, grey_matter_atlas, roi_num)
                patient_vm_gm = ap.rsystem(rcommand, self.log_file, catch_out=True)

                rcommand = '%s %s %s %s %s' % (cambia_val, segmented_pet_gm, segmented_pet_gm, roi_num, patient_vm_gm)
                ap.rsystem(rcommand, self.log_file)

            if ap.verify_roi_exists(white_matter_atlas, roi_num)==True:

                rcommand = '%s %s %s %s 0' % (calc_vm, pet_hdr, white_matter_atlas, roi_num)
                patient_vm_wm = ap.rsystem(rcommand, self.log_file, catch_out=True)

                rcommand = '%s %s %s %s %s' % (cambia_val, segmented_pet_wm, segmented_pet_wm, roi_num, patient_vm_wm)
                ap.rsystem(rcommand, self.log_file)

        # Creates Segmented soft tissue
        segmented_pet_soft = join(self.analysis_path, "seg_pet_soft.hdr")
        ap.copy_analyze(output_soft_hdr, segmented_pet_soft)
        rcommand = '%s %s %s %s 0' % (calc_vm, pet_hdr, output_soft_hdr, 1)
        patient_vm = ap.rsystem(rcommand, self.log_file, catch_out=True)
        rcommand = '%s %s %s %s %s' % (cambia_val, segmented_pet_soft, segmented_pet_soft, 1, patient_vm)
        ap.rsystem(rcommand, self.log_file)

        #Integrates everything to create segmented PET
        segmented_pet_final = join(self.analysis_path, "segmented_pet.hdr")
        rcommand = '%s %s %s %s fl sumar' % (opera_imagen, segmented_pet_gm, segmented_pet_wm,  segmented_pet_final)
        ap.rsystem(rcommand, self.log_file)
        rcommand = '%s %s %s %s fl sumar' % (opera_imagen, segmented_pet_final, segmented_pet_soft,  segmented_pet_final)
        ap.rsystem(rcommand, self.log_file)

        # Scaling to avoid problems....
        ap.operate_single_image(segmented_pet_final,"mult",1000,segmented_pet_final,self.log_file)
        ap.operate_single_image(pet_hdr,"mult",1000,pet_hdr,self.log_file)

        #Generating Attenuation map
        rcommand = '%s %s %s 1 %s' % (cambia_val, output_bone_hdr, output_bone_hdr[0:-4] + "_attindex.hdr", 0.135)
        ap.rsystem(rcommand, self.log_file)

        for k in [output_gm_hdr, output_wm_hdr, output_csf_hdr, output_soft_hdr]:
            rcommand = '%s %s %s 1 %s' % (cambia_val, k, k[0:-4] + "_attindex.hdr", 0.096)
            ap.rsystem(rcommand, self.log_file)
            rcommand = '%s %s %s %s fl sumar' % (opera_imagen, k[0:-4] + "_attindex.hdr", 
                                                 output_bone_hdr[0:-4] + "_attindex.hdr",output_bone_hdr[0:-4] + "_attindex.hdr")
            ap.rsystem(rcommand, self.log_file)

        rcommand = '%s %s %s 0.136 10 %s' % (cambia_val_interval, output_bone_hdr[0:-4] + "_attindex.hdr", output_bone_hdr[0:-4] + "_attindex.hdr", 0.096)
        ap.rsystem(rcommand, self.log_file)

        att_map = join(brainviset_dir, "attenuation_map.hdr")
        ap.copy_analyze(output_bone_hdr[0:-4] + "_attindex.hdr", image2=att_map)

        act_map = join(brainviset_dir,"activity_map.hdr")
        ap.copy_analyze(segmented_pet_final, image2=act_map)

        return act_map, att_map

    def cleanup(self):
        """
        Cleans all the crap generated during the process
        """
        message = 'Cleaning up the mesh...'
        print message
        os.system("rm %s/seg_*" % self.analysis_path)
        os.system("rm %s/c1* %s/c2* %s/c3* %s/c4* %s/c5*" % (self.analysis_path, self.analysis_path, self.analysis_path, self.analysis_path, self.analysis_path))
        os.system("rm %s/gm* %s/w* " % (self.analysis_path, self.analysis_path))
        os.system("rm %s/*txt" % self.analysis_path)
        os.system("rm %s/y_*" % self.analysis_path)