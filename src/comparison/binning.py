"""Contains classes and functions for generating bins of Regions to compare

At this level, the comparisons are referred to as pairs. Whenever anything talks about
pairs, it refers to things generated from these classes. This is distinct from what are
referred to as edges, which are pairs that have a (set of) distances between them and
may be present in the database.
"""

# from python
from __future__ import annotations
from itertools import combinations
from typing import Generator
from sqlalchemy import select, func, or_

# from other modules
from src.data import DB
from src.genbank import BGCRecord
from src.enums import SOURCE_TYPE

# from this module
from .comparable_region import ComparableRegion


class RecordPairGenerator:
    """Generator to generate all-vs-all comparisons form a list of BGC records

    Attributes:
        label (str): Label for this bin
        source_records (list[BGCRecord]): List of BGC records to generate pairs from
    """

    def __init__(self, label: str):
        self.label = label
        self.source_records: list[BGCRecord] = []
        self.record_ids: set[int] = set()

    def generate_pairs(self, legacy_sorting=False) -> Generator[RecordPair, None, None]:
        """Returns a generator for all vs all Region pairs in this bins

        This will always generate all pairs, and does not take into account any edges
        that already exist in the database

        Args:
            legacy_sorting (bool, optional): Whether to sort the BGC records by GBK file name.
            This is done in BiG-SCAPE 1.0 and can affect scoring depending on which of
            the BGC regions is region A in a pair. TODO: may be removed in the future

        Yields:
            Generator[RegionPair]: Generator for Region pairs in this bin
        """
        for record_a, record_b in combinations(self.source_records, 2):
            if legacy_sorting:
                sorted_a, sorted_b = sorted((record_a, record_b), key=sort_name_key)
                pair = RecordPair(sorted_a, sorted_b)

            else:
                pair = RecordPair(record_a, record_b)

            yield pair

    def generate_batch(
        self, batch_size: int, legacy_sorting=False
    ) -> Generator[list[RecordPair], None, None]:
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

    def __repr__(self) -> str:
        return (
            f"Bin '{self.label}': {self.num_pairs()} pairs from "
            f"{len(self.source_records)} BGC records"
        )


class QueryToRefRecordPairGenerator(RecordPairGenerator):
    """Describes a bin of BGC records to generate pairs from. Pair generation excludes
    ref <-> ref pairs
    """

    def __init__(self, label: str):
        super().__init__(label)
        self.reference_records: list[BGCRecord] = []
        self.query_records: list[BGCRecord] = []

    def generate_pairs(self, legacy_sorting=False) -> Generator[RecordPair, None, None]:
        """Returns an Generator for Region pairs in this bin, all pairs are generated
        except for ref <-> ref pairs

        Args:
            legacy_sorting (bool, optional): Whether to sort the BGC records by GBK file name.
            This is done in BiG-SCAPE 1.0 and can affect scoring depending on which of
            the BGC records is region A in a pair.

        Yields:
            Generator[RegionPair]: Generator for Region pairs in this bin
        """
        for query_idx, bgc_a in enumerate(self.query_records):
            query_start = query_idx + 1
            for bgc_b in self.reference_records + self.query_records[query_start:]:
                if bgc_a == bgc_b:
                    continue

                if legacy_sorting:
                    sorted_a, sorted_b = sorted((bgc_a, bgc_b), key=sort_name_key)
                    pair = RecordPair(sorted_a, sorted_b)
                else:
                    pair = RecordPair(bgc_a, bgc_b)

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

    def __init__(self, label: str):
        self.record_id_to_obj: dict[int, BGCRecord] = {}
        self.done_record_ids: set[int] = set()
        super().__init__(label)

    def generate_pairs(self, legacy_sorting=False) -> Generator[RecordPair, None, None]:
        """Returns an Generator for Region pairs in this bin, pairs are only generated between
        given nodes to all singleton ref nodes

        Args:
            network (BSNetwork): A network object to use for finding and sorting the nodes.
            all records in this bin must be in the network as nodes, with or without edges

            given_nodes (list[BGCRecord]): List of BGC records to generate pairs from

        Yields:
            Generator[RegionPair]: Generator for Region pairs in this bin
        """

        singleton_reference_regions = self.get_singleton_reference_nodes()
        connected_reference_regions = self.get_connected_reference_nodes()

        # update the done nodes with the connected nodes we're about to do
        for region in connected_reference_regions:
            if region._db_id is None:
                continue
            self.done_record_ids.add(region._db_id)

        for bgc_a in connected_reference_regions:
            for bgc_b in singleton_reference_regions:
                if legacy_sorting:
                    sorted_a, sorted_b = sorted((bgc_a, bgc_b), key=sort_name_key)
                    pair = RecordPair(sorted_a, sorted_b)

                else:
                    pair = RecordPair(bgc_a, bgc_b)

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

        return super().add_records(record_list)

    def get_connected_reference_nodes(self) -> set[BGCRecord]:
        """Returns a set of reference nodes that are connected to other reference nodes

        Returns:
            set[BGCRecord]: A set of reference nodes that are connected to other reference nodes
        """
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
                        select(distance_table.c.region_a_id)
                        .distinct()
                        .where(distance_table.c.distance < 1.0)
                    ),
                    bgc_record_table.c.id.in_(
                        select(distance_table.c.region_b_id)
                        .distinct()
                        .where(distance_table.c.distance < 1.0)
                    ),
                )
            )
            .where(bgc_record_table.c.id.notin_(self.done_record_ids))
            .where(gbk_table.c.source_type == SOURCE_TYPE.REFERENCE.value)
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
                        select(distance_table.c.region_a_id)
                        .distinct()
                        .where(distance_table.c.distance < 1.0)
                    ),
                    bgc_record_table.c.id.in_(
                        select(distance_table.c.region_b_id)
                        .distinct()
                        .where(distance_table.c.distance < 1.0)
                    ),
                )
            )
            .where(bgc_record_table.c.id.notin_(self.done_record_ids))
            .where(gbk_table.c.source_type == SOURCE_TYPE.REFERENCE.value)
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
        distance_table = DB.metadata.tables["distance"]
        bgc_record_table = DB.metadata.tables["bgc_record"]
        gbk_table = DB.metadata.tables["gbk"]

        select_statement = (
            select(
                bgc_record_table.c.id,
            )
            .where(
                bgc_record_table.c.id.notin_(
                    select(distance_table.c.region_a_id)
                    .distinct()
                    .where(distance_table.c.distance < 1.0)
                )
            )
            .where(
                bgc_record_table.c.id.notin_(
                    select(distance_table.c.region_b_id)
                    .distinct()
                    .where(distance_table.c.distance < 1.0)
                )
            )
            .where(gbk_table.c.source_type == SOURCE_TYPE.REFERENCE.value)
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
        distance_table = DB.metadata.tables["distance"]
        bgc_record_table = DB.metadata.tables["bgc_record"]
        gbk_table = DB.metadata.tables["gbk"]

        select_statement = (
            select(
                func.count(bgc_record_table.c.id),
            )
            .where(
                bgc_record_table.c.id.notin_(
                    select(distance_table.c.region_a_id)
                    .distinct()
                    .where(distance_table.c.distance < 1.0)
                )
            )
            .where(
                bgc_record_table.c.id.notin_(
                    select(distance_table.c.region_b_id)
                    .distinct()
                    .where(distance_table.c.distance < 1.0)
                )
            )
            .where(gbk_table.c.source_type == SOURCE_TYPE.REFERENCE.value)
            .join(gbk_table, bgc_record_table.c.gbk_id == gbk_table.c.id)
        )

        singleton_reference_node_count = DB.execute(select_statement).scalar_one()

        return singleton_reference_node_count


class MissingRecordPairGenerator(RecordPairGenerator):
    """Generator that wraps around another RecordPairGenerator to exclude any distances
    already in the database
    """

    def __init__(self, bin):
        super().__init__(bin.label)
        self.bin = bin

    def num_pairs(self) -> int:
        distance_table = DB.metadata.tables["distance"]

        # get all region._db_id in the bin where the region_a_id and region_b_id are in the
        # bin
        select_statement = (
            select(func.count(distance_table.c.region_a_id))
            .where(distance_table.c.region_a_id.in_(self.bin.record_ids))
            .where(distance_table.c.region_b_id.in_(self.bin.record_ids))
        )

        # get count
        existing_distance_count = DB.execute(select_statement).scalar_one()

        # subtract from expected number of distances
        return self.bin.num_pairs() - existing_distance_count

    def generate_pairs(self, legacy_sorting=False) -> Generator[RecordPair, None, None]:
        distance_table = DB.metadata.tables["distance"]

        # get all region._db_id in the bin
        select_statement = (
            select(distance_table.c.region_a_id, distance_table.c.region_b_id)
            .where(distance_table.c.region_a_id.in_(self.bin.record_ids))
            .where(distance_table.c.region_b_id.in_(self.bin.record_ids))
        )

        # generate a set of tuples of region id pairs
        existing_distances = set(DB.execute(select_statement).fetchall())

        for pair in self.bin.generate_pairs(legacy_sorting):
            # if the pair is not in the set of existing distances, yield it
            if (pair.region_a._db_id, pair.region_b._db_id) not in existing_distances:
                yield pair

    def add_records(self, _: list[BGCRecord]):
        raise NotImplementedError("Cannot add records to a PartialRecordPairGenerator")


class RecordPair:
    """Contains a pair of BGC records, which can be any type of BGCRecord

    This will also contain any other necessary information specific to this pair needed
    to generate the scores
    """

    def __init__(self, region_a: BGCRecord, region_b: BGCRecord):
        self.region_a = region_a
        self.region_b = region_b

        if region_a.parent_gbk is None or region_b.parent_gbk is None:
            raise ValueError("Region in pair has no parent GBK!")

        # comparable regions start at the full ranges
        a_len = len(region_a.parent_gbk.genes)
        b_len = len(region_b.parent_gbk.genes)

        self.comparable_region: ComparableRegion = ComparableRegion(
            self, 0, a_len, 0, b_len, False
        )

    def __repr__(self) -> str:
        return f"Pair {self.region_a} - {self.region_b}"

    def __hash__(self) -> int:
        a_hash = hash(self.region_a)
        b_hash = hash(self.region_b)

        # order doesn't matter
        return a_hash + b_hash

    def __eq__(self, _o) -> bool:
        if not isinstance(_o, RecordPair):
            return False

        if self.region_a == _o.region_a and self.region_b == _o.region_b:
            return True
        if self.region_a == _o.region_b and self.region_b == _o.region_a:
            return True

        return False


def generate_mix(bgc_list: list[BGCRecord]) -> RecordPairGenerator:
    """Generate an all-vs-all bin of the supplied BGC records

    Args:
        bgc_list (list[BGCRecord]): BGC records to make into an all-vs-all bin

    Returns:
        BGCBin: The all-vs-all BGC bin
    """
    mix_bin = RecordPairGenerator("mix")

    mix_bin.add_records(bgc_list)

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
