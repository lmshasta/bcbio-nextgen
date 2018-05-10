"""Qc for chipseq pipeline"""
import os
import shutil
import glob

from bcbio.log import logger
from bcbio import utils
from bcbio import bam
from bcbio.pipeline import config_utils
from bcbio.pipeline import datadict as dd
from bcbio.provenance import do
from bcbio.distributed.transaction import file_transaction, tx_tmpdir
from bcbio.log import logger


supported = ["hg19", "hg38", "mm10", "mm9", "rn4", "ce6", "dm3"]

def run(bam_file, sample, out_dir):
    """Standard QC metrics for chipseq"""
    out = {}
    work_dir = dd.get_work_dir(sample)
    sample_name = dd.get_sample_name(sample)
    # if "rchipqc" in dd.get_tools_on(sample):
    #    out = chipqc(bam_file, sample, out_dir)

    peaks = sample.get("peaks_files", []).get("main", "NULL")
    out.update(_reads_in_peaks(bam_file, peaks, dd.get_cores(sample), out_dir, sample['config']))
    return out

def _reads_in_peaks(bam_file, peaks_file, cores, out_dir, config):
    """Calculate number of reads in peaks"""
    cmd = "{samtools} stats -@ {cores} {bam_file} --target-regions {peaks_file} > {tx_out}"
    samtools = config_utils.get_program("samtools", config)
    out_file = os.path.join(out_dir, "reads_in_peaks.txt")
    if not peaks_file:
        return {}
    if not utils.file_exists(out_file):
        with file_transaction(out_file) as tx_out:
            do.run(cmd.format(**locals()), "Calculating RIP in %s" % bam_file)
    with open(out_file) as inh:
        for line in inh:
            if line.find("raw total sequences") > 0:
                reads_in = line.strip().split()[-1]
                break
    return {"base": out_file, "metrics": {"RiP": reads_in}}

def chipqc(bam_file, sample, out_dir):
    """Attempt code to run ChIPQC bioconductor packate in one sample"""
    work_dir = dd.get_work_dir(sample)
    sample_name = dd.get_sample_name(sample)
    logger.warning("ChIPQC is unstable right now, if it breaks, turn off the tool.")
    if utils.file_exists(out_dir):
        return _get_output(out_dir)
    with tx_tmpdir() as tmp_dir:
        rcode = _sample_template(sample, tmp_dir)
        # local_sitelib = utils.R_sitelib()
        rscript = utils.Rscript_cmd()
        do.run([rscript, rcode], "ChIPQC in %s" % sample_name, log_error=False)
        shutil.move(tmp_dir, out_dir)
    return _get_output(out_dir)

def _get_output(out_dir):
    return {'secondary': glob.glob(out_dir)}

def _sample_template(sample, out_dir):
    """R code to get QC for one sample"""
    bam_fn = dd.get_work_bam(sample)
    fragment_length = bam.estimate_fragment_size(bam_fn)
    genome = dd.get_genome_build(sample)
    if genome not in supported:
        genome = "NULL"
    peaks = sample.get("peaks_files", []).get("main", "NULL")
    r_code = ("library(ChIPQC);\n"
              "sample = ChIPQCsample(\"{bam_fn}\","
              "\"{peaks}\", "
              "annotation = \"{genome}\","
              "fragmentLength = \"{fragment_length}\""
              ");\n"
              "ChIPQCreport(sample);\n")
    r_code_fn = os.path.join(out_dir, "chipqc.r")
    with open(r_code_fn, 'w') as inh:
        print >>inh, r_code.format(**locals())

    return r_code_fn

def _template():
    r_code = ("library(ChIPQC);\n"
              "metadata = read.csv(\"metadata.csv\");\n"
              "qc = ChIPQC(metadata, annotation = {genome},"
              "     chromosomes = {chr}, fragmentLength = {fl});\n"
              "ChIPQCreport(qc, facetBy=c(\"{facet1}\", \"{facet2}\"));\n")