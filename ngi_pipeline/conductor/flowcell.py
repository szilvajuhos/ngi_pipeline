#!/usr/bin/env python

from __future__ import print_function



from ngi_pipeline.log import minimal_logger
from ngi_pipeline.utils.config import load_yaml_config, locate_ngi_config

LOG = minimal_logger(__name__)


## NOTE
## This is called the key function that needs to be called by Celery when  a new flowcell is delivered
## from Sthlm or Uppsala
def process_demultiplexed_flowcell(demux_fcid_dirs, restrict_to_projects=None, restrict_to_samples=None, config_file_path=None):
    demux_fcid_dirs = list(set(demux_fcid_dirs))
    if len(demux_fcid_dirs) > 1:
        error_message = ("Only one flowcell can be specified at this point"
                         "The following flowcells have been specified: "
                         "{} ".format(",".join(demux_fcid_dirs)))
        LOG.info(error_message)
        sys.exit("Quitting: " + error_message)

    process_demultiplexed_flowcells(demux_fcid_dirs, restrict_to_projects, restrict_to_samples, config_file_path)


def process_demultiplexed_flowcells(demux_fcid_dirs, restrict_to_projects=None, restrict_to_samples=None, config_file_path=None):
    """Sort demultiplexed Illumina flowcells into projects and launch their analysis.

    :param list demux_fcid_dirs: The CASAVA-produced demux directory/directories.
    :param list restrict_to_projects: A list of projects; analysis will be
                                      restricted to these. Optional.
    :param list restrict_to_samples: A list of samples; analysis will be
                                     restricted to these. Optional.
    :param str config_file_path: The path to the configuration file; can also be
                                 specified via environmental variable "NGI_CONFIG"
    """
    if not config_file_path: config_file_path = locate_ngi_config()
    if not restrict_to_projects: restrict_to_projects = []
    if not restrict_to_samples: restrict_to_samples = []
    demux_fcid_dirs_set = set(demux_fcid_dirs)
    config = load_yaml_config(config_file_path)
    # Sort/copy each raw demux FC into project/sample/fcid format -- "analysis-ready"
    projects_to_analyze = dict()
    for demux_fcid_dir in demux_fcid_dirs_set:
        # These will be a bunch of Project objects each containing Samples, FCIDs, lists of fastq files
        projects_to_analyze = setup_analysis_directory_structure(demux_fcid_dir,
                                                                 config,
                                                                 projects_to_analyze,
                                                                 restrict_to_projects,
                                                                 restrict_to_samples)
    if not projects_to_analyze:
        if restrict_to_projects:
            error_message = ("No projects found to process; the specified flowcells "
                             "({fcid_dirs}) do not contain the specified project(s) "
                             "({restrict_to_projects}) or there was an error "
                             "gathering required information.").format(
                                    fcid_dirs = ",".join(demux_fcid_dirs_set),
                                    restrict_to_projects = ",".join(restrict_to_projects))
        else:
            error_message = ("No projects found to process in flowcells {}"
                             "or there was an error gathering required "
                             "information.".format(",".join(demux_fcid_dirs_set)))
        LOG.info(error_message)
        sys.exit("Quitting: " + error_message)
    else:
        # Don't need the dict functionality anymore; revert to list
        projects_to_analyze = projects_to_analyze.values()
    ##project to analyse contained only in the current flowcell(s), I am ready to analyse the projects at flowcell level only
    launch_analysis_for_flowcells(projects_to_analyze)


def setup_analysis_directory_structure(fc_dir, config, projects_to_analyze,
                                       restrict_to_projects=None, restrict_to_samples=None):
    """
    Copy and sort files from their CASAVA-demultiplexed flowcell structure
    into their respective project/sample/libPrep/FCIDs. This collects samples
    split across multiple flowcells.

    :param str fc_dir: The directory created by CASAVA for this flowcell.
    :param dict config: The parsed configuration file.
    :param set projects_to_analyze: A dict (of Project objects, or empty)
    :param list restrict_to_projects: Specific projects within the flowcell to process exclusively
    :param list restrict_to_samples: Specific samples within the flowcell to process exclusively

    :returns: A list of NGIProject objects that need to be run through the analysis pipeline
    :rtype: list

    :raises OSError: If the analysis destination directory does not exist or if there are permissions errors.
    :raises KeyError: If a required configuration key is not available.
    """
    LOG.info("Setting up analysis for demultiplexed data in source folder \"{}\"".format(fc_dir))
    if not restrict_to_projects: restrict_to_projects = []
    if not restrict_to_samples: restrict_to_samples = []
    analysis_top_dir = os.path.abspath(config["analysis"]["top_dir"])
    if not os.path.exists(analysis_top_dir):
        error_msg = "Error: Analysis top directory {} does not exist".format(analysis_top_dir)
        LOG.error(error_msg)
        raise OSError(error_msg)
    if not os.path.exists(fc_dir):
        LOG.error("Error: Flowcell directory {} does not exist".format(fc_dir))
        return []
    # Map the directory structure for this flowcell
    try:
        fc_dir_structure = parse_casava_directory(fc_dir)
    except RuntimeError as e:
        LOG.error("Error when processing flowcell dir \"{}\": {}".format(fc_dir, e))
        return []
    # From RunInfo.xml
    fc_date = fc_dir_structure['fc_date']
    # From RunInfo.xml (name) & runParameters.xml (position)
    fcid = fc_dir_structure['fc_name']
    fc_short_run_id = "{}_{}".format(fc_date, fcid)

    if not fc_dir_structure.get('projects'):
        LOG.warn("No projects found in specified flowcell directory \"{}\"".format(fc_dir))
    # Iterate over the projects in the flowcell directory
    for project in fc_dir_structure.get('projects', []):
        project_name = project['project_name']
        # If specific projects are specified, skip those that do not match
        if restrict_to_projects and project_name not in restrict_to_projects:
            LOG.debug("Skipping project {}".format(project_name))
            continue
        #now check if this project can be parsed via Charon
        try:
            ## NOTE NOTE NOTE that this means we have to be able to access Charon
            ##                to process things. I dislike this but I have no
            ##                other way to get the Project ID
            project_id = get_project_id_from_name(project_name)
        except (RuntimeError, ValueError) as e:
            error_msg = ('Cannot proceed with project "{}" due to '
                         'Charon-related error: {}'.format(project_name, e))
            LOG.error(error_msg)
            continue
        LOG.info("Setting up project {}".format(project.get("project_name")))
        # Create a project directory if it doesn't already exist, including
        # intervening "DATA" directory
        project_dir = os.path.join(analysis_top_dir, "DATA", project_name)
        if not os.path.exists(project_dir): safe_makedir(project_dir, 0770)
        try:
            project_obj = projects_to_analyze[project_dir]
        except KeyError:
            project_obj = NGIProject(name=project_name, dirname=project_name,
                                     project_id=project_id,
                                     base_path=analysis_top_dir)
            projects_to_analyze[project_dir] = project_obj
        # Iterate over the samples in the project
        for sample in project.get('samples', []):
            # Our SampleSheet.csv names are like Y__Mom_14_01 for some reason
            sample_name = sample['sample_name'].replace('__','.')
            # If specific samples are specified, skip those that do not match
            if restrict_to_samples and sample_name not in restrict_to_samples:
                LOG.debug("Skipping sample {}".format(sample_name))
                continue
            LOG.info("Setting up sample {}".format(sample_name))
            # Create a directory for the sample if it doesn't already exist
            sample_dir = os.path.join(project_dir, sample_name)
            if not os.path.exists(sample_dir): safe_makedir(sample_dir, 0770)
            # This will only create a new sample object if it doesn't already exist in the project
            sample_obj = project_obj.add_sample(name=sample_name, dirname=sample_name)
            # Get the Library Prep ID for each file
            pattern = re.compile(".*\.(fastq|fq)(\.gz|\.gzip|\.bz2)?$")
            fastq_files = filter(pattern.match, sample.get('files', []))
            seqrun_dir = None

            for fq_file in fastq_files:
                libprep_name = determine_library_prep_from_fcid(project_id, sample_name, fcid)
                libprep_object = sample_obj.add_libprep(name=libprep_name,
                                                        dirname=libprep_name)
                libprep_dir = os.path.join(sample_dir, libprep_name)
                if not os.path.exists(libprep_dir): safe_makedir(libprep_dir, 0770)
                seqrun_object = libprep_object.add_seqrun(name=fc_short_run_id,
                                                          dirname=fc_short_run_id)
                seqrun_dir = os.path.join(libprep_dir, fc_short_run_id)
                if not os.path.exists(seqrun_dir): safe_makedir(seqrun_dir, 0770)
                seqrun_object.add_fastq_files(fq_file)
            # rsync the source files to the sample directory
            #    src: flowcell/data/project/sample
            #    dst: project/sample/flowcell_run
            src_sample_dir = os.path.join(fc_dir_structure['fc_dir'],
                                          project['data_dir'],
                                          project['project_dir'],
                                          sample['sample_dir'])
            for libprep in sample_obj:
            #this function works at run_level, so I have to process a single run
            #it might happen that in a run we have multiple lib preps for the same sample
                #for seqrun in libprep:
                src_fastq_files = [ os.path.join(src_sample_dir, fastq_file)
                                    for fastq_file in seqrun_object.fastq_files ] ##MARIO: check this
                LOG.info("Copying fastq files from {} to {}...".format(sample_dir, seqrun_dir))
                do_rsync(src_fastq_files, seqrun_dir)
    return projects_to_analyze


def parse_casava_directory(fc_dir):
    """
    Traverse a CASAVA-1.8-generated directory structure and return a dictionary
    of the elements it contains.
    The flowcell directory tree has (roughly) the structure:

    |-- Data
    |   |-- Intensities
    |       |-- BaseCalls
    |-- InterOp
    |-- Unaligned
    |   |-- Basecall_Stats_C2PUYACXX
    |-- Unaligned_16bp
        |-- Basecall_Stats_C2PUYACXX
        |   |-- css
        |   |-- Matrix
        |   |-- Phasing
        |   |-- Plots
        |   |-- SignalMeans
        |   |-- Temp
        |-- Project_J__Bjorkegren_13_02
        |   |-- Sample_P680_356F_dual56
        |   |   |-- <fastq files are here>
        |   |   |-- <SampleSheet.csv is here>
        |   |-- Sample_P680_360F_dual60
        |   |   ...
        |-- Undetermined_indices
            |-- Sample_lane1
            |   ...
            |-- Sample_lane8

    :param str fc_dir: The directory created by CASAVA for this flowcell.

    :returns: A dict of information about the flowcell, including project/sample info
    :rtype: dict

    :raises RuntimeError: If the fc_dir does not exist or cannot be accessed,
                          or if Flowcell RunMetrics could not be parsed properly.
    """
    projects = []
    fc_dir = os.path.abspath(fc_dir)
    LOG.info("Parsing flowcell directory \"{}\"...".format(fc_dir))
    parser = FlowcellRunMetricsParser(fc_dir)
    run_info = parser.parseRunInfo()
    runparams = parser.parseRunParameters()
    try:
        fc_name = run_info['Flowcell']
        fc_date = run_info['Date']
        fc_pos = runparams['FCPosition']
    except KeyError as e:
        raise RuntimeError("Could not parse flowcell information {} "
                           "from Flowcell RunMetrics in flowcell {}".format(e, fc_dir))
    # "Unaligned*" because SciLifeLab dirs are called "Unaligned_Xbp"
    # (where "X" is the index length) and there is also an "Unaligned" folder
    unaligned_dir_pattern = os.path.join(fc_dir,"Unaligned*")
    basecall_stats_dir_pattern = os.path.join(unaligned_dir_pattern,"Basecall_Stats_*")
    basecall_stats_dir = [os.path.relpath(d,fc_dir) for d in glob.glob(basecall_stats_dir_pattern)]
    # e.g. 131030_SN7001362_0103_BC2PUYACXX/Unaligned_16bp/Project_J__Bjorkegren_13_02/
    project_dir_pattern = os.path.join(unaligned_dir_pattern,"Project_*")
    for project_dir in glob.glob(project_dir_pattern):
        LOG.info("Parsing project directory \"{}\"...".format(project_dir.split(os.path.split(fc_dir)[0] + "/")[1]))
        project_samples = []
        sample_dir_pattern = os.path.join(project_dir,"Sample_*")
        # e.g. <Project_dir>/Sample_P680_356F_dual56/
        for sample_dir in glob.glob(sample_dir_pattern):
            LOG.info("Parsing samples directory \"{}\"...".format(sample_dir.split(os.path.split(fc_dir)[0] + "/")[1]))
            fastq_file_pattern = os.path.join(sample_dir,"*.fastq.gz")
            samplesheet_pattern = os.path.join(sample_dir,"*.csv")
            fastq_files = [os.path.basename(file) for file in glob.glob(fastq_file_pattern)]
            ## NOTE that we don't wind up using this SampleSheet for anything so far as I know
            ## TODO consider removing; however, some analysis engines that
            ##      we want to include in the future may need them.
            #samplesheet = glob.glob(samplesheet_pattern)
            #assert len(samplesheet) == 1, \
            #        "Error: could not unambiguously locate samplesheet in {}".format(sample_dir)
            sample_name = os.path.basename(sample_dir).replace("Sample_","").replace('__','.')
            project_samples.append({'sample_dir': os.path.basename(sample_dir),
                                    'sample_name': sample_name,
                                    'files': fastq_files,
            #                        'samplesheet': os.path.basename(samplesheet[0])})
                                   })
        project_name = os.path.basename(project_dir).replace("Project_","").replace('__','.')
        projects.append({'data_dir': os.path.relpath(os.path.dirname(project_dir),fc_dir),
                         'project_dir': os.path.basename(project_dir),
                         'project_name': project_name,
                         'samples': project_samples})
    return {'fc_dir': fc_dir,
            'fc_name': '{}{}'.format(fc_pos, fc_name),
            'fc_date': fc_date,
            'basecall_stats_dir': basecall_stats_dir,
            'projects': projects}


