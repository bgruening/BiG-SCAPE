"""Contains code to calculate the DSS for a pair of BGCs. Also contains a helper
function to perform calculation for all BGCs in a bin using just-in-time execution of
HHMAlign
"""

# from python
from typing import Optional

# from dependencies
# from other modules
from src.comparison import BGCPair

# from this module


def get_distance_from_unshared(
    bgc_pair: BGCPair, anchor_domains: set[str]
) -> tuple[float, float]:
    """Get the distance for anchor and non-anchor domains for a pair of BGCs based upon
    the unshared domains. Each domain that is unshared adds 1.0 to either distance

    Args:
        bgc_pair (BGCPair): BGCPair object to calculate this distance metric for
        anchor_domains (set[str]): A set of strings corresponding to anchor domains.
        Unshared domains that match this strings add 1.0 to distance_anchor

    Returns:
        tuple[float, float]: Two scores for the distance of non-anchor domains and of
        anchor domains, respectively
    """
    # these are the cumulative distances for non-anchor and anchor domains
    distance_non_anchor = 0.0
    distance_anchor = 0.0

    # we will need both sets and lists in order to calculate the DSS
    a_domain_set, b_domain_set = bgc_pair.comparable_region.get_domain_sets()
    a_domain_list, b_domain_list = bgc_pair.comparable_region.get_domain_lists()

    # first lets get the distance generated by domains that are not shared between BGCs
    unshared_domains = a_domain_set.symmetric_difference(b_domain_set)

    # any such unshared domain is counted as a full miss (1.0 distance)
    for unshared_domain in unshared_domains:
        if unshared_domain in a_domain_set:
            unshared_count = a_domain_list.count(unshared_domain)

        if unshared_domain in b_domain_set:
            unshared_count = b_domain_list.count(unshared_domain)

        if unshared_domain in anchor_domains:
            distance_anchor += unshared_count
            continue

        distance_non_anchor += unshared_count

    return distance_non_anchor, distance_anchor


def calc_dss_pair(
    bgc_pair: BGCPair, anchor_domains: Optional[set[str]] = None
) -> float:
    # intialize an empty set of anchor domains if it is set to None
    if anchor_domains is None:
        anchor_domains = set()

    # initialize the distances by getting the distances from all unshared domains, which
    # all add 1 to the difference
    distance_anchor, distance_non_anchor = get_distance_from_unshared(
        bgc_pair, anchor_domains
    )

    return 0.0


def get_aligned_string_dist(string_a: str, string_b: str) -> float:
    """Calculate a simple distance between two strings of equal length from an MSA

    Strings must be equal lengths.

    Args:
        string_a (str): String to calculate distance for
        string_b (str): String to calculate distance for

    Raises:
        ValueError: Raised when string lengths do not match

    Returns:
        float: Simple distance of the two passed strings
    """
    if len(string_a) != len(string_b):
        raise ValueError(
            "String A and String B length difference in get_aligned_string_dist"
        )

    gaps = 0
    matches = 0

    for char_idx in range(len(string_a)):
        if string_a[char_idx] == string_b[char_idx]:
            if string_a[char_idx] == "-":
                gaps += 1
            else:
                matches += 1

    similarity = matches / (len(string_a) - gaps)

    return 1 - similarity
