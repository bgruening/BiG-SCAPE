"""Contains test for GCF alignment and tree generation"""

# from python
from unittest import TestCase

# from other modules
from big_scape.genbank import GBK, BGCRecord, CDS
from big_scape.hmm import HSP, HSPAlignment
from big_scape.trees import generate_newick_tree
from big_scape.trees.newick_tree import generate_gcf_alignment
from big_scape.output.legacy_output import (
    adjust_lcs_to_family_reference,
    adjust_lcs_to_full_region,
)


class TestTrees(TestCase):
    """Contains alignment and tree generation tests"""

    def test_tree_gen_small(self):
        """Tests generated tree for families with less than three members"""

        records = [
            BGCRecord(GBK("", "", ""), 0, 0, 0, False, ""),
            BGCRecord(GBK("", "", ""), 0, 0, 0, False, ""),
        ]
        exemplar = 0
        mock_family = [0, 1]

        expected_tree = "(0:0.0,1:0.0):0.01;"
        tree = generate_newick_tree(records, exemplar, mock_family, "", "")

        self.assertEqual(tree, expected_tree)

    def test_gcf_alignment(self):
        """Tests alignment of GCF HSP alignments"""
        gbk_a = GBK("", "", "")
        gbk_b = GBK("", "", "")
        cds_a = CDS(0, 20)
        cds_a.strand = 1
        cds_b = CDS(0, 20)
        cds_b.strand = 1
        hsp_a = HSP(cds_a, "PF1", 1, 0, 10)
        hsp_b = HSP(cds_b, "PF1", 1, 0, 12)
        hsp_a.alignment = HSPAlignment(hsp_a, "TEST-PF1--")
        hsp_b.alignment = HSPAlignment(hsp_b, "TEST--P-F1")
        cds_a.hsps.append(hsp_a)
        cds_b.hsps.append(hsp_b)
        gbk_a.genes.append(cds_a)
        gbk_b.genes.append(cds_b)

        records = [
            BGCRecord(gbk_a, 0, 0, 100, False, ""),
            BGCRecord(gbk_b, 1, 0, 100, False, ""),
        ]
        exemplar = 0
        family_members = [0, 1]
        expected_alignment = ">0\nTEST-PF1--\n>1\nTEST--P-F1\n"
        algn = generate_gcf_alignment(records, exemplar, family_members)

        self.assertEqual(algn, expected_alignment)

    def test_lcs_adjust_fwd(self):
        """Tests adjusted lcs exemplar to member not reversed"""
        mock_result = {
            "record_a_id": 0,
            "record_b_id": 1,
            "lcs_domain_a_start": 4,
            "lcs_domain_a_stop": 7,
            "lcs_domain_b_start": 6,
            "lcs_domain_b_stop": 9,
            "reverse": False,
        }

        expected_lcs = (4, 6, False)

        new_lcs = adjust_lcs_to_family_reference(mock_result, 0, 10, 10)

        self.assertEqual(new_lcs, expected_lcs)

    def test_lcs_adjust_rev(self):
        """Tests adjusted lcs exemplar to member with reverse"""
        mock_result = {
            "record_a_id": 0,
            "record_b_id": 1,
            "lcs_domain_a_start": 4,
            "lcs_domain_a_stop": 7,
            "lcs_domain_b_start": 6,
            "lcs_domain_b_stop": 9,
            "reverse": True,
        }

        expected_lcs = (4, 3, True)

        new_lcs = adjust_lcs_to_family_reference(mock_result, 0, 10, 10)

        self.assertEqual(new_lcs, expected_lcs)

    def test_lcs_adjust_mem2ex_fwd(self):
        """Tests adjusted lcs member to exemplar not reversed"""
        mock_result = {
            "record_a_id": 0,
            "record_b_id": 1,
            "lcs_domain_a_start": 6,
            "lcs_domain_a_stop": 9,
            "lcs_domain_b_start": 4,
            "lcs_domain_b_stop": 7,
            "reverse": False,
        }

        expected_lcs = (4, 6, False)

        new_lcs = adjust_lcs_to_family_reference(mock_result, 1, 10, 10)

        self.assertEqual(new_lcs, expected_lcs)

    def test_lcs_adjust_mem2ex_rev(self):
        """Tests adjusted lcs member to exemplar with reverse"""
        mock_result = {
            "record_a_id": 0,
            "record_b_id": 1,
            "lcs_domain_a_start": 6,
            "lcs_domain_a_stop": 9,
            "lcs_domain_b_start": 4,
            "lcs_domain_b_stop": 7,
            "reverse": True,
        }

        # because the exemplar B was reversed, B is flipped back again, now
        # domain B3 corresponds to the stop in A which is corrected for exclusive start
        expected_lcs = (3, 8, True)

        new_lcs = adjust_lcs_to_family_reference(mock_result, 1, 10, 10)

        self.assertEqual(new_lcs, expected_lcs)

    def test_adjust_lcs_to_full_region_region(self):
        """Tests adjusted lcs to full regions for a region"""
        gbk_a = GBK("", "", "")
        cds_a = [CDS(100, 200), CDS(300, 550)]
        gbk_a.genes = cds_a

        region_a = BGCRecord(gbk_a, 0, 0, 600, "", "")

        gbk_b = GBK("", "", "")
        cds_b = [CDS(100, 200), CDS(300, 550), CDS(550, 700)]
        gbk_b.genes = cds_b

        region_b = BGCRecord(gbk_b, 1, 100, 700, "", "")

        a_start, b_start = (1, 1)

        expected_adjusted = (1, 1)

        actual_adjusted = adjust_lcs_to_full_region(
            a_start, b_start, region_a, region_b
        )

        self.assertEqual(expected_adjusted, actual_adjusted)

    def test_adjust_lcs_to_full_region_protocluster(self):
        """Tests adjusted lcs to full regions for a region"""
        gbk_a = GBK("", "", "")
        cds_a = [CDS(100, 200), CDS(300, 550)]
        gbk_a.genes = cds_a

        region_a = BGCRecord(gbk_a, 0, 0, 350, "", "")

        gbk_b = GBK("", "", "")
        cds_b = [CDS(100, 200), CDS(300, 550), CDS(550, 700)]
        gbk_b.genes = cds_b

        # region_b starts after the first cds
        region_b = BGCRecord(gbk_b, 1, 150, 700, "", "")

        a_start, b_start = (1, 1)

        expected_adjusted = (1, 2)

        actual_adjusted = adjust_lcs_to_full_region(
            a_start, b_start, region_a, region_b
        )

        self.assertEqual(expected_adjusted, actual_adjusted)
