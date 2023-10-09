"""Contains functions for computing the longest common subsequence between two lists
of domains or CDS in a RecordPair"""

# from python
from typing import Any
from difflib import Match, SequenceMatcher

# from other modules
import big_scape.genbank as bs_genbank
import big_scape.comparison as bs_comparison


def find_lcs(list_a: list[Any], list_b: list[Any]) -> tuple[Match, list[Match]]:
    """Detect longest common substring using sequencematcher

    Args:
        list_a (list[T]): A list of hashable objects
        list_b (list[T]): Second list of hashable objects

    Returns:
        tuple[int, int, int]: start, stop and length of longest common substring
    """
    seqmatch = SequenceMatcher(None, list_a, list_b)
    match = seqmatch.find_longest_match(0, len(list_a), 0, len(list_b))
    matching_blocks = seqmatch.get_matching_blocks()
    return match, matching_blocks


def find_protocore_distance(region: bs_genbank.ProtoCluster, idx: int) -> int:
    """Find the distance between a CDS and the closest protocore

    Args:
        protocluster (Region): protocluster
        idx (int): index of CDS

    Returns:
        int: distance to closest protocore
    """

    if not isinstance(region, bs_genbank.ProtoCluster):
        raise TypeError("region must be a protocluster")

    min_dist = None
    for protocore_idx in region.proto_core_cds_idx:
        dist = abs(protocore_idx - idx)
        if min_dist is None or dist < min_dist:
            min_dist = dist

    if min_dist is None:
        raise ValueError("No protocore found")

    return min_dist


def get_lcs_protocores(
    pair: bs_comparison.RecordPair, matching_blocks: list[Match], reverse: bool
) -> tuple[int, int, int, int, bool]:
    """Find the longest stretch of matching domains between two protocluster regions,
    preferring matches which are closest to a protocore

    Args:
        pair (RecordPair): RecordPair object
        matching_blocks (list[Match]): list of matching blocks
        reverse (bool): whether the match is in reverse

    Returns:
        tuple[int, int, int, int, bool, bool]: a_start, a_stop, b_start, b_stop,
        match in protocore
    """

    if not isinstance(pair.region_a, bs_genbank.ProtoCluster):
        raise TypeError("region_a must be a protocluster")

    if not isinstance(pair.region_b, bs_genbank.ProtoCluster):
        raise TypeError("region_b must be a protocluster")

    a_min_dist = None
    b_min_dist = None
    a_best = None
    b_best = None

    # we need to know if the domains are in the protocore, but all we have is the
    # pair.region_b.proto_core_cds_idx. we need to make a similar index on domain level
    a_proto_core_domain_idx = set()
    b_proto_core_domain_idx = set()
    domain_idx = 0
    for idx, cds in enumerate(pair.region_a.get_cds()):
        if idx not in pair.region_a.proto_core_cds_idx:
            domain_idx += len(cds.hsps)
            continue

        for _ in cds.hsps:
            a_proto_core_domain_idx.add(domain_idx)
            domain_idx += 1

    domain_idx = 0
    for idx, cds in enumerate(pair.region_b.get_cds()):
        if idx not in pair.region_b.proto_core_cds_idx:
            domain_idx += len(cds.hsps)
            continue

        for _ in cds.hsps:
            b_proto_core_domain_idx.add(domain_idx)
            domain_idx += 1

    for a_idx, b_idx, match_len in matching_blocks:
        # if match len > 1, check all the indexes in the match

        if reverse:
            b_idx = len(pair.region_b.get_cds()) - b_idx - match_len

        if match_len > 1:
            a_in_protocore = any(
                [
                    idx in pair.region_a.proto_core_cds_idx
                    for idx in range(a_idx, a_idx + match_len)
                ]
            )
            b_in_protocore = any(
                [
                    idx in pair.region_b.proto_core_cds_idx
                    for idx in range(b_idx, b_idx + match_len)
                ]
            )
        else:
            a_in_protocore = a_idx in pair.region_a.proto_core_cds_idx
            b_in_protocore = b_idx in pair.region_b.proto_core_cds_idx

        # exit early if both are in a protocore
        if a_in_protocore and b_in_protocore:
            # flip b_idx again
            if reverse:
                b_idx = len(pair.region_b.get_cds()) - b_idx - match_len
            return a_idx, a_idx + match_len, b_idx, b_idx + match_len, True

        # from this point we can assume we need to find the distance to the closest
        # protocore

        # if match_len > 1, use whichever is closest to a protocore
        if match_len > 1:
            left_dist = find_protocore_distance(pair.region_a, a_idx)
            right_dist = find_protocore_distance(pair.region_a, a_idx + match_len - 1)
            a_dist = min(left_dist, right_dist)

            left_dist = find_protocore_distance(pair.region_b, b_idx)
            right_dist = find_protocore_distance(pair.region_b, b_idx + match_len - 1)
            b_dist = min(left_dist, right_dist)
        else:
            a_dist = find_protocore_distance(pair.region_a, a_idx)
            b_dist = find_protocore_distance(pair.region_b, b_idx)

        a_better = False
        if a_min_dist is None or a_dist < a_min_dist:
            a_better = True

        b_better = False
        if b_min_dist is None or b_dist < b_min_dist:
            b_better = True

        if a_better and b_better:
            a_min_dist = a_dist
            b_min_dist = b_dist
            a_best = a_idx
            b_best = b_idx
            best_len = match_len

    # now we have the best pair of indexes, or the first one which is fine

    if a_best is None or b_best is None:
        raise ValueError("No match found")

    a_start = a_best
    a_stop = a_best + best_len
    b_start = b_best
    b_stop = b_best + best_len

    return a_start, a_stop, b_start, b_stop, False


def find_cds_lcs_region(
    a_cds: list[bs_genbank.CDS], b_cds: list[bs_genbank.CDS]
) -> tuple[int, int, int, int, bool]:
    """Find the longest stretch of matching domains between two CDS lists

    If there are LCS of the same length, the LCS closest to the middle of the region
    is preferred (TODO)
    TODO: maybe this is not useful at all

    Args:
        a_cds (list[CDS]): List of CDS
        b_cds (list[CDS]): List of CDS

    Returns:
        tuple[int, int, int, int, bool]: a_start, a_stop, b_start, b_stop, reverse
    """
    # forward
    match, matching_blocks = find_lcs(a_cds, b_cds)
    a_start_fwd = match[0]
    b_start_fwd = match[1]
    fwd_match_len = match[2]

    # reverse
    match, matching_blocks_rev = find_lcs(a_cds, b_cds[::-1])
    a_start_rev = match[0]
    b_start_rev = match[1]
    rev_match_len = match[2]

    fwd_larger = fwd_match_len > rev_match_len
    rev_larger = fwd_match_len < rev_match_len

    if fwd_larger:
        reverse = False
        a_start = a_start_fwd
        a_stop = a_start_fwd + fwd_match_len

        b_start = b_start_fwd
        b_stop = b_start_fwd + fwd_match_len

        return a_start, a_stop, b_start, b_stop, reverse

    if rev_larger:
        reverse = True
        a_start = a_start_rev
        a_stop = a_start_rev + rev_match_len

        b_start = len(b_cds) - b_start_rev - rev_match_len
        b_stop = len(b_cds) - b_start_rev

        return a_start, a_stop, b_start, b_stop, reverse

    # equal lengths

    # length of 1. use the matching block with the most domains
    # if all equal, this returns the first
    # TODO: should probably return most central
    if fwd_match_len == 1:
        max = 0
        for a_idx, b_idx, match_len in matching_blocks:
            num_domains = len(a_cds[a_idx : a_idx + match_len])  # noqa
            if num_domains > max:
                max = num_domains

                reverse = False

                a_start = a_idx
                a_stop = a_idx + match_len

                b_start = b_idx
                b_stop = b_idx + match_len

        return a_start, a_stop, b_start, b_stop, reverse

    # equal length, but not 1
    # default to forward
    # default to first match
    # TODO: should probably return most central
    reverse = False
    a_start = a_start_fwd
    a_stop = a_start_fwd + fwd_match_len

    b_start = b_start_fwd
    b_stop = b_start_fwd + fwd_match_len

    return a_start, a_stop, b_start, b_stop, reverse


def find_domain_lcs_region(
    a_cds: list[bs_genbank.CDS], b_cds: list[bs_genbank.CDS]
) -> tuple[int, int, int, int, bool]:
    """Find the longest stretch of matching domains between two lists of domains

    This takes CDS as arguments, but uses the domains within the CDS to find the LCS

    Args:
        a_cds (list[CDS]): List of CDS
        b_cds (list[CDS]): List of CDS

    Returns:
        tuple[int, int, int, int, bool]: a_start, a_stop, b_start, b_stop, reverse
    """

    a_domains = []
    b_domains = []
    for cds in a_cds:
        a_domains.extend(cds.hsps)
    for cds in b_cds:
        b_domains.extend(cds.hsps)
    # forward
    match, matching_blocks = find_lcs(a_domains, b_domains)
    a_start_fwd = match[0]
    b_start_fwd = match[1]
    fwd_match_len = match[2]

    # reverse
    match, matching_blocks_rev = find_lcs(a_domains, b_domains[::-1])
    a_start_rev = match[0]
    b_start_rev = match[1]
    rev_match_len = match[2]

    fwd_larger = fwd_match_len > rev_match_len
    rev_larger = fwd_match_len < rev_match_len

    if fwd_larger:
        reverse = False
        a_start = a_start_fwd
        a_stop = a_start_fwd + fwd_match_len

        b_start = b_start_fwd
        b_stop = b_start_fwd + fwd_match_len

        return a_start, a_stop, b_start, b_stop, reverse

    if rev_larger:
        reverse = True
        a_start = a_start_rev
        a_stop = a_start_rev + rev_match_len

        b_start = len(b_domains) - b_start_rev - rev_match_len
        b_stop = len(b_domains) - b_start_rev

        return a_start, a_stop, b_start, b_stop, reverse

    # equal lengths
    # match of length 1 means we pick something in the middle
    if fwd_match_len == 1:
        # first find which region is shorter in terms of cds
        a_cds_len = len(a_cds)
        b_cds_len = len(b_cds)

        # default to A. if B is shorter, use B
        if a_cds_len <= b_cds_len:
            use_cds = a_cds
            use_domains = a_domains
            matching_block_idx = 0
        else:
            use_cds = b_cds
            use_domains = b_domains
            matching_block_idx = 1

        # generate a CDS to index dict
        cds_idx_dict = {cds: i for i, cds in enumerate(use_cds)}

        # go through all LCS matches and find the one with the most central CDS
        middle = len(use_cds) / 2
        min = None
        for matching_block in matching_blocks:
            # I don't even know why there is a match of len 0 when there are matches
            # of len 1
            if matching_block[2] == 0:
                continue

            idx = matching_block[matching_block_idx]

            domain = use_domains[idx]
            cds_idx = cds_idx_dict[domain.cds]

            # find the distance to the middle
            distance = abs(middle - cds_idx)

            if min is None or distance < min:
                min = distance
                a_start = matching_block[0]
                a_stop = matching_block[0] + matching_block[2]
                b_start = matching_block[1]
                b_stop = matching_block[1] + matching_block[2]

        return a_start, a_stop, b_start, b_stop, False

    # equal length, but not 1
    # default to forward
    # default to first match
    # TODO: should probably return most central

    reverse = False
    a_start = a_start_fwd
    a_stop = a_start_fwd + fwd_match_len

    b_start = b_start_fwd
    b_stop = b_start_fwd + fwd_match_len

    return a_start, a_stop, b_start, b_stop, reverse


def find_domain_lcs_protocluster(
    pair: bs_comparison.RecordPair,
) -> tuple[int, int, int, int, bool]:
    """Find the longest stretch of matching domains between two protocluster regions,
    using domains

    Args:
        pair (RecordPair): RecordPair object

    Returns:
        tuple[int, int, int, int, bool]: a_start, a_stop, b_start, b_stop, reverse
    """

    # we really need protoclusters here
    if not isinstance(pair.region_a, bs_genbank.ProtoCluster):
        raise TypeError("region_a must be a protocluster")

    if not isinstance(pair.region_b, bs_genbank.ProtoCluster):
        raise TypeError("region_b must be a protocluster")

    a_cds = pair.region_a.get_cds()
    b_cds = pair.region_b.get_cds()

    a_domains = []
    b_domains = []
    for idx, cds in enumerate(a_cds):
        a_domains.extend(cds.hsps)
    for idx, cds in enumerate(b_cds):
        b_domains.extend(cds.hsps)

    # forward
    match, matching_blocks = find_lcs(a_domains, b_domains)
    a_start_fwd = match[0]
    b_start_fwd = match[1]
    fwd_match_len = match[2]

    # reverse
    match, matching_blocks_rev = find_lcs(a_domains, b_domains[::-1])
    a_start_rev = match[0]
    b_start_rev = match[1]
    rev_match_len = match[2]

    # forward
    forward_lcs = get_lcs_protocores(pair, matching_blocks, False)
    in_protocore_fwd = forward_lcs[4]

    # reverse
    reverse_lcs = get_lcs_protocores(pair, matching_blocks_rev, True)
    in_protocore_rev = reverse_lcs[4]

    # if a match is found both in reverse and forward that contains protocores in both
    # regions, use the longest match. if matches are equal length, use forward
    if in_protocore_fwd and in_protocore_rev:
        (
            a_start_fwd,
            a_stop_fwd,
            b_start_fwd,
            b_stop_fwd,
            in_protocore_fwd,
        ) = forward_lcs
        (
            a_start_rev,
            a_stop_rev,
            b_start_rev,
            b_stop_rev,
            in_protocore_rev,
        ) = reverse_lcs

        if a_stop_fwd - a_start_fwd >= a_stop_rev - a_start_rev:
            reverse = False
            return a_start_fwd, a_stop_fwd, b_start_fwd, b_stop_fwd, reverse
        else:
            reverse = True
            return a_start_rev, a_stop_rev, b_start_rev, b_stop_rev, reverse

    # if a match is found in forward, use that
    if in_protocore_fwd:
        (
            a_start_fwd,
            a_stop_fwd,
            b_start_fwd,
            b_stop_fwd,
            in_protocore_fwd,
        ) = forward_lcs
        reverse = False
        return a_start_fwd, a_stop_fwd, b_start_fwd, b_stop_fwd, reverse

    # if a match is found in reverse, use that
    if in_protocore_rev:
        (
            a_start_rev,
            a_stop_rev,
            b_start_rev,
            b_stop_rev,
            in_protocore_rev,
        ) = reverse_lcs
        reverse = True
        return a_start_rev, a_stop_rev, b_start_rev, b_stop_rev, reverse

    # if no match is found in either, use the longest match
    if fwd_match_len >= rev_match_len:
        reverse = False
        return (
            a_start_fwd,
            a_start_fwd + fwd_match_len,
            b_start_fwd,
            b_start_fwd + fwd_match_len,
            reverse,
        )
    else:
        reverse = True
        return (
            a_start_rev,
            a_start_rev + rev_match_len,
            b_start_rev,
            b_start_rev + rev_match_len,
            reverse,
        )
