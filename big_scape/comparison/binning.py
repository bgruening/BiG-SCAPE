"""Contains classes and functions for generating bins of Regions to compare

At this level, the comparisons are referred to as pairs. Whenever anything talks about
pairs, it refers to things generated from these classes. This is distinct from what are
referred to as edges, which are pairs that have a (set of) distances between them and
may be present in the database.

TODO: this file is very long and is begging for refactoring. a lot of the classes
are very similar apart from the method in which they query the database. This could
almost certainly be abstracted somehow
"""

# from python
from __future__ import annotations
import logging
from itertools import combinations
from typing import Generator, Iterator, Optional
from sqlalchemy import select, func, or_

# from other modules
from big_scape.cli.constants import ANTISMASH_CLASSES
from big_scape.data import DB
from big_scape.genbank import BGCRecord, Region, ProtoCluster, ProtoCore
from big_scape.enums import SOURCE_TYPE, CLASSIFY_MODE

import big_scape.comparison as bs_comparison

# from this module


# weights are in the order JC, AI, DSS, Anchor boost
LEGACY_WEIGHTS = {
    "PKSI": {"weights": (0.22, 0.02, 0.76, 1.0)},
    "PKSother": {"weights": (0.0, 0.68, 0.32, 4.0)},
    "NRPS": {"weights": (0.0, 0.0, 1.0, 4.0)},
    "RiPP": {"weights": (0.28, 0.01, 0.71, 1.0)},
    "saccharide": {"weights": (0.0, 1.0, 0.0, 1.0)},
    "terpene": {"weights": (0.2, 0.05, 0.75, 2.0)},
    "PKS-NRP_Hybrids": {"weights": (0.0, 0.22, 0.78, 1.0)},
    "other": {"weights": (0.01, 0.02, 0.97, 4.0)},
    "mix": {"weights": (0.2, 0.05, 0.75, 2.0)},
}


class RecordPairGenerator:
    """Generator to generate all-vs-all comparisons form a list of BGC records

    Attributes:
        label (str): Label for this bin
        source_records (list[BGCRecord]): List of BGC records to generate pairs from
    """

    def __init__(self, label: str, edge_param_id: int, weights: Optional[str] = None):
        self.label = label
        self.edge_param_id = edge_param_id
        self.source_records: list[BGCRecord] = []
        self.record_ids: set[int] = set()
        if weights is None:
            weights = label
        self.weights = weights

    def generate_pairs(
        self, legacy_sorting=False
    ) -> Generator[tuple[int, int], None, None]:
        """Returns a generator for all vs all Region pairs in this bins

        This will always generate all pairs, and does not take into account any edges
        that already exist in the database

        Args:
            legacy_sorting (bool, optional): Whether to sort the BGC records by GBK file name.
            This is done in BiG-SCAPE 1.0 and can affect scoring depending on which of
            the BGC regions is region A in a pair. TODO: may be removed in the future

        Yields:
            Generator[tuple[int, int]]: Generator for Region pairs in this bin
        """
        for record_a, record_b in combinations(self.source_records, 2):
            if record_a.parent_gbk == record_b.parent_gbk:
                continue
            if legacy_sorting:
                sorted_a, sorted_b = sorted((record_a, record_b), key=sort_name_key)
                if sorted_a._db_id is None or sorted_b._db_id is None:
                    raise RuntimeError("generated pair is missing DB ids!")
                pair = (sorted_a._db_id, sorted_b._db_id)

            else:
                if record_a._db_id is None or record_b._db_id is None:
                    raise RuntimeError("generated pair is missing DB ids!")
                pair = (record_a._db_id, record_b._db_id)

            yield pair

    # TODO: check if can be removed
    def generate_batch(
        self, batch_size: int, legacy_sorting=False
    ) -> Generator[list[tuple[int, int]], None, None]:
        """Generator for batches of pairs in this bin

        Args:
            batch_size (int): The size of the batch to generate
            legacy_sorting (bool, optional): Whether to sort the BGC records by GBK file name.
            This is done in BiG-SCAPE 1.0 and can affect scoring depending on which of
            the BGC records is region A in a pair.

        Yields:
            Generator[list[RegionPair], None, None]]: Generator for Region pairs in this
            bin
        """
        batch = []
        while pair := next(self.generate_pairs(legacy_sorting), None):
            batch.append(pair)
            if len(batch) == batch_size:
                yield batch
                batch = []

    def num_pairs(self) -> int:
        """Return the number of pairs expected to be generated by the pairs Generator

        Returns:
            int: The number of pairs expected to be generated from the Generator
        """

        if len(self.source_records) < 2:
            return 0

        len_all_records = len(self.source_records)

        # (n*(n-1)) / 2
        num_all_pairs = int((len_all_records * (len_all_records - 1)) / 2)

        return num_all_pairs

    def add_records(self, record_list: list[BGCRecord]):
        """Adds BGC records to this bin and creates a generator for the pairs

        Args:
            record_list (list[BGCRecord]): List of BGC records to add to this bin
        """
        self.source_records.extend(record_list)
        self.record_ids.update([region._db_id or -1 for region in record_list])

        # throw a ValueError if any region db id is None, as we expect all regions to be
        # represented in the database
        if None in self.record_ids:
            raise ValueError("Region in bin has no db id!")

    def cull_singletons(self, cutoff: float):
        """Culls singletons for given cutoff, i.e. records which have either no edges
        in the database, or all edges have a distance above/equal to the cutoff"""

        if not DB.metadata:
            raise RuntimeError("DB.metadata is None")

        distance_table = DB.metadata.tables["distance"]

        # get all distances/edges in the table for the records in this bin and
        # with distances below the cutoff
        select_statement = (
            select(distance_table.c.record_a_id, distance_table.c.record_b_id)
            .where(distance_table.c.record_a_id.in_(self.record_ids))
            .where(distance_table.c.record_b_id.in_(self.record_ids))
            .where(distance_table.c.distance < cutoff)
            .where(distance_table.c.edge_param_id == self.edge_param_id)
        )

        edges = DB.execute(select_statement).fetchall()

        # get all record_ids in the edges
        filtered_record_ids: set[int] = set()
        for edge in edges:
            filtered_record_ids.update(edge)

        self.record_ids = filtered_record_ids
        self.source_records = [
            record
            for record in self.source_records
            if record._db_id in filtered_record_ids
        ]

    def __repr__(self) -> str:
        return (
            f"Bin '{self.label}': {self.num_pairs()} pairs from "
            f"{len(self.source_records)} BGC records"
        )


class QueryToRefRecordPairGenerator(RecordPairGenerator):
    """Describes a bin of BGC records to generate pairs from. Pair generation excludes
    ref <-> ref pairs
    """

    def __init__(self, label: str, edge_param_id: int, weights: str):
        super().__init__(label, edge_param_id, weights)
        self.reference_records: list[BGCRecord] = []
        self.query_records: list[BGCRecord] = []

    def generate_pairs(
        self, legacy_sorting=False
    ) -> Generator[tuple[int, int], None, None]:
        """Returns an Generator for Region pairs in this bin, all pairs are generated
        except for ref <-> ref pairs

        Args:
            legacy_sorting (bool, optional): Whether to sort the BGC records by GBK file name.
            This is done in BiG-SCAPE 1.0 and can affect scoring depending on which of
            the BGC records is region A in a pair.

        Yields:
            Generator[RegionPair]: Generator for Region pairs in this bin
        """
        for query_idx, record_a in enumerate(self.query_records):
            query_start = query_idx + 1
            for record_b in self.reference_records + self.query_records[query_start:]:
                if record_a == record_b:
                    continue

                if legacy_sorting:
                    sorted_a, sorted_b = sorted((record_a, record_b), key=sort_name_key)
                    if sorted_a._db_id is None or sorted_b._db_id is None:
                        raise RuntimeError("generated pair is missing DB ids!")
                    pair = (sorted_a._db_id, sorted_b._db_id)
                else:
                    if record_a._db_id is None or record_b._db_id is None:
                        raise RuntimeError("generated pair is missing DB ids!")
                    pair = (record_a._db_id, record_b._db_id)

                yield pair

    def num_pairs(self) -> int:
        """Returns the number of pairs expected to be generated by the pairs Generator,
        which excludes ref <-> ref pairs

        Returns:
            int: The number of pairs expected to be generated from the Generator
        """

        if len(self.source_records) < 2:
            return 0

        if len(self.reference_records) == 0:
            return 0

        if len(self.query_records) == 0:
            return 0

        query_to_ref_comps = len(self.query_records) * len(self.reference_records)

        query_to_query_comps = int(
            (len(self.query_records) * (len(self.query_records) - 1)) / 2
        )

        return query_to_ref_comps + query_to_query_comps

    def add_records(self, record_list: list[BGCRecord]) -> None:
        """Adds BGC records to this bin, additionaly splitting them into query and
        reference records

        Args:
            record_list (list[BGCRecord]): List of BGC records to add to this bin
        """
        for record in record_list:
            if (
                record.parent_gbk is not None
                and record.parent_gbk.source_type == SOURCE_TYPE.QUERY
            ):
                self.query_records.append(record)
            else:
                self.reference_records.append(record)

        super().add_records(record_list)


class RefToRefRecordPairGenerator(RecordPairGenerator):
    """A generator for pairs of connected reference regions to unconected reference
    regions

    Args:
        label (str): Label for this bin
        source_records (list[BGCRecord]): List of BGC records to generate pairs from
    """

    def __init__(self, label: str, edge_param_id: int, weights: str):
        self.record_id_to_obj: dict[int, BGCRecord] = {}
        self.reference_record_ids: set[int] = set()
        self.done_record_ids: set[int] = set()
        super().__init__(label, edge_param_id, weights)

    def generate_pairs(
        self, legacy_sorting=False
    ) -> Generator[tuple[int, int], None, None]:
        """Returns an Generator for Region pairs in this bin, pairs are only generated between
        given nodes to all singleton ref nodes

        Args:
            network (BSNetwork): A network object to use for finding and sorting the nodes.
            all records in this bin must be in the network as nodes, with or without edges

            given_nodes (list[BGCRecord]): List of BGC records to generate pairs from

        Yields:
            Generator[RegionPair]: Generator for Region pairs in this bin
        """

        singleton_reference_records = self.get_singleton_reference_nodes()
        connected_reference_records = self.get_connected_reference_nodes()

        # update the done nodes with the connected nodes we're about to do
        for record in connected_reference_records:
            if record._db_id is None:
                continue
            self.done_record_ids.add(record._db_id)

        for record_a in connected_reference_records:
            for record_b in singleton_reference_records:
                if record_a.parent_gbk == record_b.parent_gbk:
                    continue
                if legacy_sorting:
                    sorted_a, sorted_b = sorted((record_a, record_b), key=sort_name_key)
                    if sorted_a._db_id is None or sorted_b._db_id is None:
                        raise RuntimeError("generated pair is missing DB ids!")
                    pair = (sorted_a._db_id, sorted_b._db_id)

                else:
                    if record_a._db_id is None or record_b._db_id is None:
                        raise RuntimeError("generated pair is missing DB ids!")
                    pair = (record_a._db_id, record_b._db_id)

                yield pair

    def num_pairs(self) -> int:
        """Returns the number of pairs expected to be generated by the pairs Generator,
        which includes only given node <-> singleton ref pairs

        Returns:
            int: The number of pairs expected to be generated from the Generator
        """
        num_connected = self.get_connected_reference_node_count()
        num_singletons = self.get_singleton_reference_node_count()

        num_pairs = num_connected * num_singletons

        return num_pairs

    def add_records(self, record_list: list[BGCRecord]):
        """Adds BGC records to this bin and creates a generator for the pairs

        also creates a dictionary of record id to record objects
        """
        for record in record_list:
            if record._db_id is None:
                raise ValueError("Region in bin has no db id!")

            self.record_id_to_obj[record._db_id] = record
            if record.parent_gbk is not None:
                if record.parent_gbk.source_type == SOURCE_TYPE.REFERENCE:
                    self.reference_record_ids.add(record._db_id)

        return super().add_records(record_list)

    def get_connected_reference_nodes(self) -> set[BGCRecord]:
        """Returns a set of reference nodes that are connected to other reference nodes

        Returns:
            set[BGCRecord]: A set of reference nodes that are connected to other reference nodes
        """

        if not DB.metadata:
            raise RuntimeError("DB.metadata is None")

        distance_table = DB.metadata.tables["distance"]
        bgc_record_table = DB.metadata.tables["bgc_record"]
        gbk_table = DB.metadata.tables["gbk"]

        select_statement = (
            select(
                bgc_record_table.c.id,
            )
            .where(
                or_(
                    bgc_record_table.c.id.in_(
                        select(distance_table.c.record_a_id)
                        .distinct()
                        .where(distance_table.c.distance < 1.0)
                        .where(distance_table.c.edge_param_id == self.edge_param_id)
                    ),
                    bgc_record_table.c.id.in_(
                        select(distance_table.c.record_b_id)
                        .distinct()
                        .where(distance_table.c.distance < 1.0)
                        .where(distance_table.c.edge_param_id == self.edge_param_id)
                    ),
                )
            )
            .where(bgc_record_table.c.id.notin_(self.done_record_ids))
            .where(bgc_record_table.c.id.in_(self.reference_record_ids))
            .join(gbk_table, bgc_record_table.c.gbk_id == gbk_table.c.id)
        )

        connected_reference_nodes = set()

        for row in DB.execute(select_statement).fetchall():
            region_id = row[0]

            if region_id in self.record_id_to_obj:
                connected_reference_nodes.add(self.record_id_to_obj[region_id])

        return connected_reference_nodes

    def get_connected_reference_node_count(self) -> int:
        """Returns the number of reference nodes that are not connected to other
        reference nodes

        Returns:
            int: The number of reference nodes that are not connected to other reference
            nodes
        """

        if not DB.metadata:
            raise RuntimeError("DB.metadata is None")

        distance_table = DB.metadata.tables["distance"]
        bgc_record_table = DB.metadata.tables["bgc_record"]
        gbk_table = DB.metadata.tables["gbk"]

        select_statement = (
            select(
                func.count(bgc_record_table.c.id),
            )
            .where(
                or_(
                    bgc_record_table.c.id.in_(
                        select(distance_table.c.record_a_id)
                        .distinct()
                        .where(distance_table.c.distance < 1.0)
                        .where(distance_table.c.edge_param_id == self.edge_param_id)
                    ),
                    bgc_record_table.c.id.in_(
                        select(distance_table.c.record_b_id)
                        .distinct()
                        .where(distance_table.c.distance < 1.0)
                        .where(distance_table.c.edge_param_id == self.edge_param_id)
                    ),
                )
            )
            .where(bgc_record_table.c.id.notin_(self.done_record_ids))
            .where(bgc_record_table.c.id.in_(self.reference_record_ids))
            .join(gbk_table, bgc_record_table.c.gbk_id == gbk_table.c.id)
        )

        connected_reference_node_count = DB.execute(select_statement).scalar_one()

        return connected_reference_node_count

    def get_singleton_reference_nodes(self) -> set[BGCRecord]:
        """Returns a set of reference nodes that are not connected to other reference
        nodes

        Returns:
            set[BGCRecord]: A set of reference nodes that are not connected to other
            reference nodes
        """

        if not DB.metadata:
            raise RuntimeError("DB.metadata is None")

        distance_table = DB.metadata.tables["distance"]
        bgc_record_table = DB.metadata.tables["bgc_record"]
        gbk_table = DB.metadata.tables["gbk"]

        select_statement = (
            select(
                bgc_record_table.c.id,
            )
            .where(
                bgc_record_table.c.id.notin_(
                    select(distance_table.c.record_a_id)
                    .distinct()
                    .where(distance_table.c.distance < 1.0)
                    .where(distance_table.c.edge_param_id == self.edge_param_id)
                )
            )
            .where(
                bgc_record_table.c.id.notin_(
                    select(distance_table.c.record_b_id)
                    .distinct()
                    .where(distance_table.c.distance < 1.0)
                    .where(distance_table.c.edge_param_id == self.edge_param_id)
                )
            )
            .where(bgc_record_table.c.id.in_(self.reference_record_ids))
            .join(gbk_table, bgc_record_table.c.gbk_id == gbk_table.c.id)
        )

        singleton_reference_nodes = set()

        for row in DB.execute(select_statement).fetchall():
            region_id = row[0]

            if region_id in self.record_id_to_obj:
                singleton_reference_nodes.add(self.record_id_to_obj[region_id])

        return singleton_reference_nodes

    def get_singleton_reference_node_count(self) -> int:
        """Returns the number of reference nodes that are not connected to other
        reference nodes

        Returns:
            int: The number of reference nodes that are not connected to other reference
            nodes
        """

        if not DB.metadata:
            raise RuntimeError("DB.metadata is None")

        distance_table = DB.metadata.tables["distance"]
        bgc_record_table = DB.metadata.tables["bgc_record"]
        gbk_table = DB.metadata.tables["gbk"]

        select_statement = (
            select(
                func.count(bgc_record_table.c.id),
            )
            .where(
                bgc_record_table.c.id.notin_(
                    select(distance_table.c.record_a_id)
                    .distinct()
                    .where(distance_table.c.distance < 1.0)
                )
            )
            .where(
                bgc_record_table.c.id.notin_(
                    select(distance_table.c.record_b_id)
                    .distinct()
                    .where(distance_table.c.distance < 1.0)
                )
            )
            .where(bgc_record_table.c.id.in_(self.reference_record_ids))
            .join(gbk_table, bgc_record_table.c.gbk_id == gbk_table.c.id)
        )

        singleton_reference_node_count = DB.execute(select_statement).scalar_one()

        return singleton_reference_node_count


class ConnectedComponentPairGenerator(RecordPairGenerator):
    """Generator that takes as input a conected component and generates
    the pairs from the edges in the component"""

    def __init__(self, connected_component, label: str):
        # getting the first one, assume consistent edge param id for all cc
        edge_param_id = connected_component[0][6]
        weights = bs_comparison.get_edge_weight(edge_param_id)

        super().__init__(label, edge_param_id, weights)
        self.connected_component = connected_component
        self.record_id_to_obj: dict[int, BGCRecord] = {}

    def add_records(self, record_list: list[BGCRecord]):
        """Adds BGC records to this bin and creates a generator for the pairs

        also creates a dictionary of record id to record objects
        """
        cc_record_ids = set()
        cc_record_list = []

        for edge in self.connected_component:
            (
                record_a_id,
                record_b_id,
                dist,
                jacc,
                adj,
                dss,
                edge_param_id,
            ) = edge
            cc_record_ids.add(record_a_id)
            cc_record_ids.add(record_b_id)

        for record in record_list:
            if record._db_id is None:
                raise ValueError("Region in bin has no db id!")
            if record._db_id not in cc_record_ids:
                continue

            self.record_id_to_obj[record._db_id] = record
            cc_record_list.append(record)

        return super().add_records(cc_record_list)

    def generate_pairs(
        self, legacy_sorting=False
    ) -> Generator[tuple[int, int], None, None]:
        """Returns a Generator for all pairs in this bin"""

        for edge in self.connected_component:
            record_a_id, record_b_id, dist, jacc, adj, dss, edge_param_id = edge

            record_a = self.record_id_to_obj[record_a_id]
            record_b = self.record_id_to_obj[record_b_id]

            if record_a.parent_gbk == record_b.parent_gbk:
                continue

            if legacy_sorting:
                sorted_a, sorted_b = sorted((record_a, record_b), key=sort_name_key)
                if sorted_a._db_id is None or sorted_b._db_id is None:
                    raise RuntimeError("generated pair is missing DB ids!")
                pair = (sorted_a._db_id, sorted_b._db_id)
            else:
                if record_a._db_id is None or record_b._db_id is None:
                    raise RuntimeError("generated pair is missing DB ids!")
                pair = (record_a._db_id, record_b._db_id)

            yield pair


class MissingRecordPairGenerator(RecordPairGenerator):
    """Generator that wraps around another RecordPairGenerator to exclude any distances
    already in the database
    """

    def __init__(self, pair_generator):
        super().__init__(
            pair_generator.label, pair_generator.edge_param_id, pair_generator.weights
        )
        self.bin = pair_generator

    def num_pairs(self) -> int:
        if not DB.metadata:
            raise RuntimeError("DB.metadata is None")

        distance_table = DB.metadata.tables["distance"]

        # get all region._db_id in the bin where the record_a_id and record_b_id are in the
        # bin
        select_statement = (
            select(func.count(distance_table.c.record_a_id))
            .where(distance_table.c.record_a_id.in_(self.bin.record_ids))
            .where(distance_table.c.record_b_id.in_(self.bin.record_ids))
            .where(distance_table.c.edge_param_id == self.bin.edge_param_id)
        )

        # get count
        existing_distance_count = DB.execute(select_statement).scalar_one()

        # subtract from expected number of distances
        return self.bin.num_pairs() - existing_distance_count

    def generate_pairs(
        self, legacy_sorting=False
    ) -> Generator[tuple[int, int], None, None]:
        if not DB.metadata:
            raise RuntimeError("DB.metadata is None")

        distance_table = DB.metadata.tables["distance"]

        # get all region._db_id in the bin
        select_statement = (
            select(distance_table.c.record_a_id, distance_table.c.record_b_id)
            .where(distance_table.c.record_a_id.in_(self.bin.record_ids))
            .where(distance_table.c.record_b_id.in_(self.bin.record_ids))
            .where(distance_table.c.edge_param_id == self.bin.edge_param_id)
        )

        # generate a set of tuples of region id pairs
        existing_distances = set(DB.execute(select_statement).fetchall())

        for pair in self.bin.generate_pairs(legacy_sorting):
            # if the pair is not in the set of existing distances, yield it
            if pair not in existing_distances and pair[::-1] not in existing_distances:
                yield pair

    def add_records(self, _: list[BGCRecord]):
        raise NotImplementedError("Cannot add records to a PartialRecordPairGenerator")


def generate_mix_bin(
    record_list: list[BGCRecord], edge_param_id: int
) -> RecordPairGenerator:
    """Generate an all-vs-all bin of the supplied BGC records

    Args:
        bgc_list (list[BGCRecord]): BGC records to make into an all-vs-all bin

    Returns:
        BGCBin: The all-vs-all BGC bin
    """

    mix_bin = RecordPairGenerator(label="mix", edge_param_id=edge_param_id)

    mix_bin.add_records([record for record in record_list if record is not None])

    return mix_bin


def sort_name_key(record: BGCRecord) -> str:
    """Return the parent gbk file name without extension, or None if no parent gbk is
    assigned

    Args:
        record (BGCRecord): A BGCrecord

    Returns:
        str: the parent gbk file name without extension
    """
    if record.parent_gbk is None:
        return ""

    return record.parent_gbk.path.name[:-4]


def as_class_bin_generator(
    all_records: list[BGCRecord], run: dict
) -> Iterator[RecordPairGenerator]:
    """Generate bins for each antiSMASH class

    Args:
        gbks (list[GBK]): List of GBKs to generate bins for
        category_weights (str): weights to use for each class

    Yields:
        Iterator[RecordPairGenerator]: Generator that yields bins. Order is not guarenteed to be
        consistent
    """
    if run["legacy_weights"]:
        weight_type = "legacy_weights"
    else:
        weight_type = "mix"

    classify_mode = run["classify"]

    class_idx: dict[str, list[BGCRecord]] = {}
    category_weights: dict[str, str] = {}

    for record in all_records:
        # get region class for bin label and index
        if classify_mode == CLASSIFY_MODE.CLASS:
            record_class = record.product

        if classify_mode == CLASSIFY_MODE.CATEGORY:
            record_class = get_record_category(record)

        if run["hybrids_off"]:
            record_classes = record_class.split(".")
        else:
            record_classes = [record_class]

        for record_class in record_classes:
            if record_class not in class_idx:
                class_idx[record_class] = [record]

            if record_class in class_idx and record not in class_idx[record_class]:
                class_idx[record_class].append(record)

            if weight_type == "legacy_weights":
                # get region category for weights
                region_weight_cat = get_weight_category(record)

                if record_class not in category_weights.keys():
                    category_weights[record_class] = region_weight_cat

            if weight_type == "mix":
                category_weights[record_class] = "mix"

    for class_name, records in class_idx.items():
        weight_category = category_weights[class_name]
        edge_param_id = bs_comparison.get_edge_param_id(run, weight_category)
        bin = RecordPairGenerator(class_name, edge_param_id, weight_category)
        bin.add_records(records)
        yield bin


def get_record_category(record: BGCRecord) -> str:
    """Get the category of a BGC based on its antiSMASH product(s)

    Args:
        region (Region): region object

    Returns:
        str: BGC category
    """

    categories: list[str] = []

    if isinstance(record, ProtoCluster) or isinstance(record, ProtoCore):
        if record.category is not None:
            categories.append(record.category)

    if isinstance(record, Region):
        # get categories from region object
        for idx, cand_cluster in record.cand_clusters.items():
            if cand_cluster is not None:
                for idx, protocluster in cand_cluster.proto_clusters.items():
                    if protocluster is not None and protocluster.category is not None:
                        pc_category = protocluster.category
                        # avoid duplicates, hybrids of the same kind count as one category
                        if pc_category not in categories:
                            categories.append(pc_category)

    if len(categories) == 0:
        return "Categoryless"

    if len(categories) == 1:
        return categories[0]

    return ".".join(categories)


def get_weight_category(record: BGCRecord) -> str:
    """Get the category of a BGC based on its antiSMASH product(s)
    and match it to the legacy weights classes

    Args:
        region (BGCRecord): region object

    Returns:
        str: class category to be used in weight selection
    """

    categories: list[str] = []

    if isinstance(record, ProtoCluster) or isinstance(record, ProtoCore):
        # T1PKS is the only case in which a antiSMASH category does not
        # correspond to a legacy_weights class
        if (
            record.category is not None
        ):  # for typing, we assume antismash 6 and up always have it
            if record.product == "T1PKS":
                categories.append(record.product)
            else:
                categories.append(record.category)

    if isinstance(record, Region):
        # get categories from region object
        for idx, cand_cluster in record.cand_clusters.items():
            if cand_cluster is not None:
                for idx, protocluster in cand_cluster.proto_clusters.items():
                    if protocluster is not None and protocluster.category is not None:
                        if protocluster.product == "T1PKS":
                            pc_category = protocluster.product
                        else:
                            pc_category = protocluster.category
                        # avoid duplicates, hybrids of the same kind use the same weight class
                        if pc_category not in categories:
                            categories.append(pc_category)

    # process into legacy_weights classes

    # for versions that dont have category information
    if len(categories) == 0:
        logging.warning(
            "No category found for %s",
            record,
            "This should not happen as long as antiSMASH is run with"
            "version 6 or up, consider whether there is something"
            "special about this region",
        )
        category = "other"

    if len(categories) == 1:
        category = categories[0]

    if len(categories) > 1:
        if "NRPS" and ("PKS" or "T1PKS") in categories:
            category = "PKS-NRP_Hybrids"

        if "PKS" or ("PKS" and "T1PKS") in categories:
            category = "PKSother"  # PKS hybrids

        else:
            category = "other"  # other hybrids

    return category


def legacy_bin_generator(
    all_records: list[BGCRecord], run: dict
) -> Iterator[RecordPairGenerator]:  # pragma no cover
    """Generate bins for each class as they existed in the BiG-SCAPE 1.0 implementation

    Args:
        gbks (list[GBK]): List of GBKs to generate bins for

    Yields:
        Iterator[BGCBin]: Generator that yields bins. Order is not guarenteed to be
        consistent
        TODO: should it be consistent?
    """
    # generate index
    class_idx: dict[str, list[BGCRecord]] = {}

    for record in all_records:
        if record is None:
            continue
        if record.product is None:
            continue

        product = record.product

        if run["hybrids_off"]:
            record_products = product.split(".")

        else:
            record_products = [product]

        for product in record_products:
            record_class = legacy_get_class(product)

            if record_class not in class_idx:
                class_idx[record_class] = [record]

            if record_class in class_idx and record not in class_idx[record_class]:
                class_idx[record_class].append(record)

    for class_name, records in class_idx.items():
        edge_param_id = bs_comparison.get_edge_param_id(run, class_name)
        bin = RecordPairGenerator(class_name, edge_param_id, class_name)
        bin.add_records(records)
        yield bin


# one of the few direct copy-and-pastes!
def legacy_get_class(product):  # pragma no cover
    """Sort BGC by its type. Uses AntiSMASH annotations
    (see https://docs.antismash.secondarymetabolites.org/glossary/#cluster-types)

    Args:
        product (str): product type

    Returns:
        str: product class
    """

    # PKS_Type I
    if product in ANTISMASH_CLASSES["pks1_products"]:
        return "PKSI"
    # PKS Other Types
    elif product in ANTISMASH_CLASSES["pksother_products"]:
        return "PKSother"
    # NRPs
    elif product in ANTISMASH_CLASSES["nrps_products"]:
        return "NRPS"
    # RiPPs
    elif product in ANTISMASH_CLASSES["ripps_products"]:
        return "RiPP"
    # Saccharides
    elif product in ANTISMASH_CLASSES["saccharide_products"]:
        return "saccharide"
    # Terpenes
    elif product == "terpene":
        return "terpene"
    # PKS/NRP hybrids
    elif len(product.split(".")) > 1:
        # print("  Possible hybrid: (" + cluster + "): " + product)
        # cf_fatty_acid category contains a trailing empty space

        subtypes = set(s.strip() for s in product.split("."))
        if (
            len(
                subtypes
                - (
                    ANTISMASH_CLASSES["pks1_products"]
                    | ANTISMASH_CLASSES["pksother_products"]
                    | ANTISMASH_CLASSES["nrps_products"]
                )
            )
            == 0
        ):
            if len(subtypes - ANTISMASH_CLASSES["nrps_products"]) == 0:
                return "NRPS"
            elif (
                len(
                    subtypes
                    - (
                        ANTISMASH_CLASSES["pks1_products"]
                        | ANTISMASH_CLASSES["pksother_products"]
                    )
                )
                == 0
            ):
                return "PKSother"  # pks hybrids
            else:
                return "PKS-NRP_Hybrids"
        elif len(subtypes - ANTISMASH_CLASSES["ripps_products"]) == 0:
            return "RiPP"
        elif len(subtypes - ANTISMASH_CLASSES["saccharide_products"]) == 0:
            return "saccharide"
        else:
            return "other"  # other hybrid
    # Others
    elif product in ANTISMASH_CLASSES["others_products"]:
        return "other"
    # ??
    elif product == "":
        # No product annotation. Perhaps not analyzed by antiSMASH
        return "other"
    else:
        logging.warning("unknown product %s", product)
        return "other"
