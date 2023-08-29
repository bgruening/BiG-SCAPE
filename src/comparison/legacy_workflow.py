"""Contains methods to run the legacy comparison workflow on a bin of BGC pairs"""

# from python
import logging
from math import ceil
from multiprocessing import cpu_count
from multiprocessing.connection import Connection, wait
from typing import Callable, Optional, cast

# from other modules
from src.distances import calc_jaccard_pair, calc_ai_pair, calc_dss_pair_legacy
from src.network import BSNetwork
from src.utility import start_processes

# from this module
from .binning import BGCBin, BGCPair
from .legacy_bins import LEGACY_BINS
from .legacy_extend import (
    legacy_needs_expand_pair,
    expand_glocal,
    check_expand,
    reset_expansion,
)
from .legacy_lcs import legacy_find_cds_lcs


def create_bin_network_edges(
    bin: BGCBin, network: BSNetwork, alignment_mode: str, cores: int
):  # pragma no cover
    logging.info("Using %d cores for distance calculation", cores)
    # first step is to calculate the Jaccard of all pairs. This is pretty fast, but
    # could be optimized by multiprocessing for very large bins
    logging.info("Calculating Jaccard for %d pairs", bin.num_pairs())

    related_pairs = calculate_jaccard_multiprocess(bin, network, cores)

    # any pair that had a jaccard of 0 are put into the network and should not be
    # processed again. If there are no more pairs left, leave the workflow
    if bin.num_pairs() == 0:
        return

    # next step is to perform LCS. We need to multiprocess this and that is a bit of a
    # hassle

    logging.info("Performing LCS for %d pairs with Jaccard > 0", len(related_pairs))
    pairs_need_expand, pairs_no_expand = get_lcs_multiprocess(
        related_pairs, alignment_mode, cores
    )

    if len(pairs_need_expand) > 0:
        # those regions which need expansion are now expanded. Expansion is expensive and
        # is also done through multiprocessing
        logging.info("Expanding regions for %d pairs", len(pairs_need_expand))

        expanded_pairs = []
        for pair in pairs_need_expand:
            expand_glocal(pair.comparable_region)

        logging.info("Checking expansion")
        for pair in pairs_need_expand:
            # if after expansion the region is still too small or does not contain any
            # biosynthetic genes, we reset back to the full region and add this pair
            # to the list of pairs that were not expanded
            if not check_expand(pair.comparable_region):
                reset_expansion(pair.comparable_region)
                pairs_no_expand.append(pair)
                continue

            pair.comparable_region.log_comparable_region("GLOCAL")

            jaccard = calc_jaccard_pair(pair)

            # any pair with a jaccard of 0 after expansion is also kicked out
            if jaccard == 0.0:
                network.add_edge_pair(pair, jc=0.0, ai=0.0, dss=0.0, dist=1.0)
                continue

            expanded_pairs.append(pair)

    # from here on the only things left to be done are distance calculation
    if len(pairs_no_expand) > 0:
        logging.info(
            "Calculating score for %d pairs that were reset or did not need expansion",
            len(pairs_no_expand),
        )
        calculate_scores_multiprocess(bin, pairs_no_expand, network, cores)

    if len(expanded_pairs) > 0:
        logging.info(
            "Calculating score for %d pairs that were expanded",
            len(expanded_pairs),
        )
        calculate_scores_multiprocess(bin, expanded_pairs, network, cores)


def get_lcs_worker_method(
    task: tuple[int, BGCPair], extra_data=None
) -> tuple[int, int, int, int, int, bool]:  # pragma no cover
    """Find LCS on pair and return the LCS coordinates

    Args:
        pair (BGCPair): Pair of BGC to find LCS on
        extra_data (Any): Not used

    Returns:
        tuple[int, int, int, int, bool]: pair_idx, a_start, a_stop, b_start, b_stop, reverse
    """
    pair_idx, pair = task
    return (pair_idx,) + legacy_find_cds_lcs(
        pair.region_a.get_cds_with_domains(), pair.region_b.get_cds_with_domains()
    )


def get_lcs_multiprocess(
    pairs: list[BGCPair],
    alignment_mode: str,
    num_processes: int = cpu_count(),
    batch_size=None,
    callback: Optional[Callable] = None,
) -> tuple[list[BGCPair], list[BGCPair]]:  # pragma no cover
    """Find the LCS using multiple processes and return two lists of pairs.

    The first list returned by this function is a list of pairs which need expansion.
    The second list returned by thris function is a list of pairs which do not need
    expansion

    Args:
        bin (BGCBin): Bin to get pairs from
        network: (BSNetwork): BiG-SCAPE network used to check if pair already has an
        edge
        num_processes (int): how many processes to use for this step. Defaults to the
        number of cores on the machine
        batch_size (int): size of the batches to send to the worker. IF set to none,
        evenly divides the task set into number of batches equal to num_processes
        callback (callable): A callback function that reports the number of pairs done
        after a batch is returned from a worker

    Returns:
        tuple[list[BGCPair], list[BGCPair]]: List of pairs to be expanded and list of
        pairs which does not need expansion
    """
    # lists to return
    need_expansion = []
    no_expansion = []

    # get worker proceses
    processes, connections = start_processes(num_processes, get_lcs_worker_method, None)

    # get automatic batch size
    if batch_size is None:
        batch_size = ceil(len(pairs) / num_processes)

    pair_idx = 0
    tasks_done = 0

    # main loop while connections are still alive
    while len(connections) > 0:
        # worker connections that are sending something
        available_connections = wait(connections)

        for connection in available_connections:
            connection = cast(Connection, connection)

            # get data. this is None on the first iteration
            output_data = connection.recv()

            # prepare to send data
            if pair_idx < len(pairs):
                # this is the batch of data to send
                num_tasks_to_send = min(batch_size, len(pairs) - pair_idx)

                input_data = []
                for task_pair_idx in range(pair_idx, pair_idx + num_tasks_to_send):
                    # the actual pair to send
                    pair = pairs[task_pair_idx]
                    input_data.append((task_pair_idx, pair))

                # update the sent pair number
                pair_idx += num_tasks_to_send
            else:
                input_data = None

            # send the data. If there are no more tasks, this will be None
            connection.send(input_data)

            # we can close the connection after sending None as the worker will termiante
            if input_data is None:
                connection.close()
                connections.remove(connection)

            # don't process any output if it is None (first iteration)
            if output_data is None:
                continue

            num_tasks = len(output_data)
            for output_result in output_data:
                (
                    result_pair_idx,
                    a_start,
                    a_stop,
                    b_start,
                    b_stop,
                    reverse,
                ) = output_result

                # get the original pair
                original_pair = pairs[result_pair_idx]

                # set the comparable region
                original_pair.comparable_region.a_start = a_start
                original_pair.comparable_region.a_stop = a_stop
                original_pair.comparable_region.b_start = b_start
                original_pair.comparable_region.b_stop = b_stop
                original_pair.comparable_region.reverse = reverse

                # check if the comparable region needs expanding. This is relatively fast
                # so it can be done in the main thread
                if legacy_needs_expand_pair(original_pair, alignment_mode):
                    need_expansion.append(original_pair)

                    continue

                reset_expansion(original_pair.comparable_region)
                no_expansion.append(original_pair)

            tasks_done += num_tasks

            # report progress for those interested
            if callback is not None:
                callback(tasks_done)

    # just to make sure, kill any remaining processes
    for process in processes:
        process.kill()

    return need_expansion, no_expansion


def calculate_jaccard_worker_method(
    task: BGCPair, extra_data=None
) -> float:  # pragma no cover
    """Calculate and return the scores for a pair

    Args:
        task: The task, in this case in the form of a tuple where the first item is a
        pair index relating to the original pair, and the second item is a copy of the
        pair object

    Returns:
        float: jaccard index
    """
    pair = task

    jaccard = calc_jaccard_pair(pair)

    return jaccard


def calculate_jaccard_multiprocess(
    bin: BGCBin,
    network: BSNetwork,
    num_processes: int = cpu_count(),
    callback: Optional[Callable] = None,
) -> list[BGCPair]:  # pragma no cover
    """Calculate the jaccard for a list of pairs by using subprocesses
    This returns a list of related pairs of which the jaccard index for the full list of
    CDS is > 0.0

    Any pairs with a jaccard of 0.0 are added to the network with a 1.0 distance edge

    Args:
        bin: (BGCBin): BGC Bin to calculate pair jaccards for
        network (BSNetwork): BSnetwork objects to add new edges to
        num_processes (int): number of cores to use. Defaults to number of cpus available
        callback (callable): A callback function that reports the number of pairs done
        after a batch is returned from a worker
    """

    bin_weights = LEGACY_BINS[bin.label]["weights"]
    jc_weight, ai_weight, dss_weight, anchor_boost = bin_weights

    # prepare processes
    # if we only have two pairs to process, we only need two processes. otherwise we
    # will use all of them
    needed_processes = min(bin.num_pairs(), num_processes)

    processes, connections = start_processes(
        needed_processes,
        calculate_jaccard_worker_method,
        extra_data=None,
        use_batches=False,
    )

    tasks_done = 0

    related_pairs: list[BGCPair] = []

    # we use this to retrieve the original object
    # TODO: investigate if we can use sharedmemory
    original_data: dict[Connection, Optional[BGCPair]] = {
        connection: None for connection in connections
    }

    pair_generator = bin.pairs(legacy_sorting=True)

    while len(connections) > 0:
        available_connections = wait(connections)

        for connection in available_connections:
            connection = cast(Connection, connection)

            output_data = connection.recv()
            original_pair = original_data[connection]

            input_data = next(pair_generator, None)
            original_data[connection] = input_data

            connection.send(input_data)

            if input_data is None:
                connection.close()
                connections.remove(connection)

            if output_data is None or original_pair is None:
                continue

            jc = output_data

            if jc == 0.0:
                network.add_edge_pair(original_pair, dist=1.0, jc=0.0, ai=0.0, dss=0.0)
            else:
                related_pairs.append(original_pair)

            tasks_done += 1

            if callback is not None:
                callback(tasks_done)

    # just to make sure, kill any remaining processes
    for process in processes:
        process.kill()

    return related_pairs


def calculate_scores_worker_method(
    task: tuple[int, BGCPair], anchor_boost: float
) -> tuple[int, float, float, float]:  # pragma no cover
    """Calculate and return the scores for a pair

    Args:
        task: The task, in this case in the form of a tuple where the first item is a
        pair index relating to the original pair, and the second item is a copy of the
        pair object
        anchor_boost (float): anchor_boost parameter for the dss calculation

    Returns:
        tuple[int, float, float, float]: index of pair, jaccard, AI, DSS
    """
    pair_idx, pair = task

    jaccard = calc_jaccard_pair(pair)

    adjacency = calc_ai_pair(pair)
    # mix anchor boost = 2.0
    dss = calc_dss_pair_legacy(pair, anchor_boost=anchor_boost)

    return pair_idx, jaccard, adjacency, dss


def calculate_scores_multiprocess(
    bin: BGCBin,
    pairs: list[BGCPair],
    network: BSNetwork,
    num_processes: int = cpu_count(),
    batch_size=None,
    callback: Optional[Callable] = None,
):  # pragma no cover
    """Calculate the scores for a list of pairs by using subprocesses

    Args:
        pairs (list[BGCPair]): list of pairs to perform score calution on
        network (BSNetwork): BSnetwork objects to add new edges to
        cpu_count (int): number of cores to use. Defaults to number of cpus available
        batch_size (int): size of the batches to send to the worker. IF set to none,
        evenly divides the task set into number of batches equal to num_processes
        callback (callable): A callback function that reports the number of pairs done
        after a batch is returned from a worker
    """

    bin_weights = LEGACY_BINS[bin.label]["weights"]
    jc_weight, ai_weight, dss_weight, anchor_boost = bin_weights

    # prepare processes
    # if we only have two pairs to process, we only need two processes. otherwise we
    # will use all of them
    needed_processes = min(len(pairs), num_processes)

    processes, connections = start_processes(
        needed_processes, calculate_scores_worker_method, anchor_boost
    )

    if batch_size is None:
        batch_size = ceil(len(pairs) / needed_processes)

    tasks_done = 0
    pair_idx = 0

    while len(connections) > 0:
        available_connections = wait(connections)

        for connection in available_connections:
            connection = cast(Connection, connection)

            output_data = connection.recv()

            # prepare to send data
            if pair_idx < len(pairs):
                # this is the batch of data to send
                num_tasks_to_send = min(batch_size, len(pairs) - pair_idx)

                input_data = []
                for task_pair_idx in range(pair_idx, pair_idx + num_tasks_to_send):
                    # the actual pair to send
                    pair = pairs[task_pair_idx]
                    input_data.append((task_pair_idx, pair))

                # update the sent pair number
                pair_idx += num_tasks_to_send
            else:
                input_data = None

            connection.send(input_data)

            if input_data is None:
                connection.close()
                connections.remove(connection)

            if output_data is None:
                continue

            num_received_tasks = len(output_data)
            for task_output in output_data:
                done_pair_idx, jc, ai, dss = task_output

                similarity = jc * jc_weight + ai * ai_weight + dss * dss_weight
                distance = 1 - similarity

                network.add_edge_pair(
                    pairs[done_pair_idx], dist=distance, jc=jc, ai=ai, dss=dss
                )

            tasks_done += num_received_tasks

            if callback is not None:
                callback(tasks_done)

    # just to make sure, kill any remaining processes
    for process in processes:
        process.kill()
