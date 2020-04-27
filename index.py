import argparse
import re
import tarfile
import tempfile
import time
import os
import multiprocessing
import queue
import logging
import glob
import traceback

from var_utils import VarNormalizer
from assign_gene.utils import Result
import parse_data
import var_ner
import gene_ner
import assign_gene
import normalize_var
from utils import timeout
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ResultEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Result):
            return dict(zip(o._fields, vars(o)))
        return json.JSONEncoder.default(self, o)


def parse_args() -> argparse.Namespace:
    """
    Returns:
        arguments
    """
    parser = argparse.ArgumentParser()

    parser.add_argument("--n-process", type=int, default=1)
    parser.add_argument("--loglevel", type=str, default='INFO')
    parser.add_argument("--input", type=str, default='/app/data/pmc/**/*.tar.gz')

    parser.set_defaults(nxml_only=False)
    parser.add_argument("--nxml-only", action='store_true', dest='nxml_only')

    parser.set_defaults(table_detect=True)
    parser.add_argument("--no-table-detect", action='store_false', dest='table_detect')

    args = parser.parse_args()
    return args


@timeout(180)
def extract(_id, idx, data, var_extr, gene_extr):  # pylint: disable=too-many-locals
    """process a paper
    """
    body_var, table_var = var_ner.process(_id, data.body, data.tables, var_extr)
    body_gene, caption_gene, table_gene = gene_ner.process(_id, data.body, data.tables, gene_extr)

    body_results = assign_gene.process_body(idx, data.body, body_gene, body_var)
    table_results = assign_gene.process_table(idx, data.tables, body_gene, caption_gene,
                                              table_gene, table_var)
    results = body_results + table_results
    return results


def worker(jobs, args):  # pylint: disable=too-many-locals
    """worker for one process
    """
    var_extr = var_ner.pytmvar.Extractor()
    gene_extr = gene_ner.pygnormplus.Extractor()
    var_normalizer = VarNormalizer()

    logger.info('Process %s init OK', os.getpid())

    while True:
        try:
            job = jobs.get(timeout=10)
        except queue.Empty:
            continue

        if job == 'END':
            jobs.task_done()
            break
        else:
            _id, filename = job

        try:

            logger.info('Processing file %s', filename)

            with tempfile.TemporaryDirectory() as tmpdir:
                with tarfile.open(filename) as achieve:
                    achieve.extractall(tmpdir)

                parsed_data = parse_data.process(
                    _id, os.path.join(tmpdir, _id), nxml_only=args.nxml_only,
                    table_detect=args.table_detect, save_data=False
                )

                results = []
                for idx, filename, data in parsed_data:
                    try:
                        results += extract(_id, idx, data, var_extr, gene_extr)
                    except TimeoutError:
                        logger.warning(f'Timeout processing %s', filename)

                normalize_var.process(results, _id, var_normalizer)

        except Exception:
            logger.exception('Error processing %s', filename)
            continue
        finally:
            jobs.task_done()

    logger.info('Process %s end', os.getpid())


def main():
    """main function
    """
    args = parse_args()

    if args.loglevel:
        logging.getLogger().setLevel(getattr(logging, args.loglevel))

    jobs = multiprocessing.JoinableQueue(args.n_process * 10)

    for _ in range(args.n_process):
        multiprocessing.Process(target=worker, args=(jobs, args)).start()

    files = glob.iglob(args.input, recursive=True)

    while files is not None:
        while not jobs.full():
            try:
                filename = next(files)
            except StopIteration:
                for _ in range(args.n_process):
                    jobs.put('END')
                files = None
                break

            try:
                _id = re.findall(r'(PMC\d+)\.tar\.gz$', filename).pop(0)
            except IndexError:
                logger.error('Skip %s because PMC not found!', filename)
                continue

            jobs.put((_id, filename))

    jobs.join()


if __name__ == '__main__':
    main()

