# from python
import logging
import sys
from datetime import datetime

# from other modules
from src.file_input import load_dataset_folder
from src.genbank import SOURCE_TYPE
from src.hmm import HMMer
from src.parameters import cmd_parser, RunParameters

if __name__ == "__main__":
    parser = cmd_parser()
    parsed_args = parser.parse_args(sys.argv[1:])

    # run object
    run = RunParameters()
    run.parse(parsed_args)

    # quick timing stuff
    start_time = datetime.now()

    # logger
    # this tells the logger what the messages should look like
    # asctime = YYYY-MM-DD HH:MM:SS,fff
    # levelname = DEBUG/INFO/WARN/ERROR
    # message = whatever we pass, eg logging.debug("message")
    log_formatter = logging.Formatter("%(asctime)s %(levelname)-7.7s %(message)s")

    # get the built in logger
    root_logger = logging.getLogger()

    # TODO: add a check to run parse to make sure the optional stuff goes away
    if run.diagnostics is None:
        exit()
    if run.diagnostics.verbose is None:
        exit()

    if run.diagnostics.verbose:
        root_logger.level = logging.DEBUG
    else:
        root_logger.level = logging.INFO

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    # TODO: add a check to run parse to make sure the optional stuff goes away
    if run.input is None:
        exit()

    if run.input.gbk_path is None:
        exit()

    if run.input.pfam_path is None:
        exit()

    gbks = load_dataset_folder(run.input.gbk_path, SOURCE_TYPE.QUERY)

    HMMer.init(run.input.pfam_path)

    # TODO: mypy thinks the following list of genes may contain none values (because
    # its of type list[Optional[CDS]])
    # it's right. needs refactoring. but for now we can throw in an is none in the next
    # loop so that mypy knows for sure there are no Nones in this list
    all_genes = []
    for gbk in gbks:
        # TODO: related to the above. this inner loop is not really necessary
        for gene in gbk.genes:
            if gene is None:
                continue
            all_genes.append(gene)

    def callback(tasks_done):
        percentage = int(tasks_done / len(all_genes) * 100)
        logging.info("%d/%d (%d%%)", tasks_done, len(all_genes), percentage)

    all_hsps = list(HMMer.hmmsearch_multiprocess(all_genes, callback))

    logging.info("%d hsps", len(all_hsps))

    exec_time = datetime.now() - start_time
    logging.info("scan done at %f seconds", exec_time.total_seconds())

    HMMer.unload()

    HMMer.init(run.input.pfam_path, False)

    all_alignments = list(HMMer.align_simple(all_hsps))

    logging.info("%d alignments", len(all_alignments))

    exec_time = datetime.now() - start_time
    logging.info("align done at %f seconds", exec_time.total_seconds())
